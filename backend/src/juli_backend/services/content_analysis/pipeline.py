"""One analysis, end to end (fast track P15, D24.20).

``analyze`` runs on the ``content_analysis`` Celery queue (``workers/tasks/
content_analysis.py``) for one ``content_analyses`` row whose file is fully
uploaded, and fills the row: status, derived signals, the result, usage and
cost. The uploaded file and the work directory are deleted when it ends --
done, failed for good, or refused over the cap; a transient provider error
keeps the file for the task's retry (``sweep`` deletes it after 24 h at most).

Video (≤ 10 min): probe → audio → ASR (whole file) → cuts (10 fps luma) →
keyframes every 2 s → vision (on-screen text + product visible) → ONE scoring
call over the derived signals.

LIVE (≤ 3 h): probe → audio → find the windows around the product: TikTok's
product timing when the caller has it (no TikTok API gives per-product pin
times today -- A-26 per-minute metrics are shop-level, A-27 has no timing), else
the first ASR mentions of the product's name / brand / SKU, transcribing
10-minute slices from the start (at most ``CONTENT_ANALYSIS_LIVE_SCAN_MAX_MINUTES``);
window = mention − 2 min … + 5 min, at most 3 → transcript, cuts, keyframes,
vision and scoring of those windows only.

Before every paid step the shop's monthly OpenAI cap is checked
(``costs.check``) with that step's estimate.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.services.content_analysis import costs, media, storage
from juli_backend.services.content_analysis.config import (
    LIVE,
    AnalysisSettings,
    asr_usd_per_minute,
    max_seconds,
)
from juli_backend.services.content_analysis.cuts import detect_cuts
from juli_backend.services.content_analysis.openai_media import (
    Segment,
    Transcriber,
    VisionReader,
    supports_timestamps,
)
from juli_backend.services.content_analysis.scoring import (
    Scorer,
    Signals,
    build_result,
    product_spans,
    screen_lines,
)
from juli_backend.services.content_cards.guardrails import ContentRules

logger = logging.getLogger(__name__)

STATUS_AWAITING = "awaiting_upload"
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_REFUSED = "refused"
STATUS_EXPIRED = "expired"
TERMINAL = frozenset({STATUS_DONE, STATUS_FAILED, STATUS_REFUSED, STATUS_EXPIRED})

#: Transcription slice: whisper-1 takes 10 minutes of 48 kbps audio (~3.6 MB)
#: easily under the 25 MB limit; models without timestamps get 30 s slices so
#: each line keeps a usable time.
ASR_SLICE_S = 600.0
ASR_SLICE_NO_TIMESTAMPS_S = 30.0
#: Vision estimate per keyframe before the call (USD; ~1k tokens with the prompt).
VISION_USD_PER_FRAME_ESTIMATE = 0.0001
SCORING_USD_ESTIMATE = 0.002
DURATION_TOLERANCE_S = 2.0
MAX_STORED_SEGMENTS = 400
MAX_STORED_SCREEN = 200

ERROR_VI: dict[str, str] = {
    "not_a_video": "Tệp không phải video MP4 / MOV. Bạn xuất lại video dạng MP4 rồi tải lên.",
    "no_video_stream": "Tệp không có hình. Bạn chọn đúng tệp video.",
    "no_duration": "Juli không đọc được độ dài video. Bạn xuất lại video dạng MP4 rồi tải lên.",
    "media_unreadable": "Juli không đọc được video này. Bạn xuất lại video dạng MP4 rồi tải lên.",
    "media_timeout": "Video quá nặng để Juli đọc. Bạn thử bản ngắn hơn hoặc nhẹ hơn.",
    "ffmpeg_missing": "Juli chưa phân tích được video lúc này. Đội Juli đã được báo.",
    "too_long_video": "Video dài hơn 10 phút. Bạn tải lên video từ 10 phút trở xuống.",
    "too_long_live": "Bản ghi LIVE dài hơn 3 giờ. Bạn tải lên bản ghi từ 3 giờ trở xuống.",
    "file_missing": "Tệp video không còn trên máy chủ. Bạn tải lên lại.",
    "provider": "Juli chưa gọi được dịch vụ phân tích. Juli sẽ thử lại.",
    "provider_final": "Juli chưa phân tích được video sau nhiều lần thử. Bạn tải lên lại sau.",
}


@dataclass
class ProductInfo:
    name: str | None = None
    brand: str | None = None
    label: str | None = None
    images: list[str] = field(default_factory=list)
    seo_words: list[str] = field(default_factory=list)


class ProductReader(Protocol):
    async def read(
        self, session: AsyncSession, shop_id: uuid.UUID, product_id: str | None
    ) -> ProductInfo: ...


@dataclass
class Collaborators:
    transcriber: Transcriber
    vision: VisionReader
    scorer: Scorer
    product_reader: ProductReader


class AnalysisFailed(Exception):
    """A permanent failure: the row ends ``failed`` with ``code``'s message."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def fold(text: str) -> str:
    """Lower-case, accents stripped, đ→d, single spaces (mention matching)."""
    stripped = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    plain = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^\w]+", " ", plain).strip()


def mention_terms(product: ProductInfo) -> list[str]:
    """What a host says when talking about the product: the name's first words, brand, SKU."""
    terms: list[str] = []
    name_words = [w for w in fold(product.name or "").split() if not w.isdigit()]
    if len(name_words) >= 2:
        terms.append(" ".join(name_words[:3]))
        terms.append(" ".join(name_words[:2]))
    elif name_words:
        terms.append(name_words[0])
    for extra in (product.brand, product.label):
        folded = fold(extra or "")
        if len(folded) >= 3:
            terms.append(folded)
    return [t for t in dict.fromkeys(terms) if len(t) >= 3]


def glossary(product: ProductInfo) -> str:
    """The ASR prompt: product name, brand, SEO words (helps spelling, not content)."""
    parts = [product.name, product.brand, product.label, *product.seo_words[:8]]
    return ", ".join(dict.fromkeys(p.strip() for p in parts if p and p.strip()))


def find_mentions(segments: Sequence[Segment], terms: Sequence[str]) -> list[float]:
    if not terms:
        return []
    out = []
    for seg in segments:
        text = f" {fold(seg.text)} "
        if any(f" {term} " in text for term in terms):
            out.append(seg.start)
    return sorted(out)


def windows_from(
    times: Sequence[float], *, duration: float, conf: AnalysisSettings, source: str
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for t in sorted(times):
        lo = max(0.0, t - conf.live_window_before_s)
        hi = min(duration, t + conf.live_window_after_s)
        if windows and lo <= windows[-1]["to_s"]:
            windows[-1]["to_s"] = round(max(windows[-1]["to_s"], hi), 2)
            continue
        if len(windows) >= conf.live_max_windows:
            break
        windows.append(
            {
                "from_s": round(lo, 2),
                "to_s": round(hi, 2),
                "mention_s": round(t, 2),
                "source": source,
            }
        )
    return windows


@dataclass
class _Run:
    """Accumulates usage and cost as stages complete (saved even on a refusal)."""

    analysis: ContentAnalysis
    usage: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    spent: float = 0.0

    def add(self, stage: str, usd: float, **fields: Any) -> None:
        entry = self.usage.setdefault(stage, {"usd": 0.0})
        entry["usd"] = round(float(entry["usd"]) + usd, 6)
        for key, value in fields.items():
            if isinstance(value, int | float) and isinstance(entry.get(key), int | float):
                entry[key] = round(entry[key] + value, 3)
            else:
                entry[key] = value
        self.spent = round(self.spent + usd, 6)
        self.flush()

    def time(self, stage: str, started: float) -> None:
        self.timings[stage] = round(self.timings.get(stage, 0.0) + time.monotonic() - started, 3)
        self.flush()

    def flush(self) -> None:
        self.analysis.cost_usd = Decimal(str(round(self.spent, 6)))
        self.analysis.usage = {**self.usage, "timings_s": dict(self.timings)}


async def _check(session: AsyncSession, run: _Run, estimate: float) -> None:
    # This analysis's own spend so far is on the row (``run.flush``), which the
    # session autoflushes before ``costs.check`` sums the month.
    await costs.check(session, run.analysis.shop_id, estimate_usd=estimate)


async def _transcribe_slice(
    session: AsyncSession,
    run: _Run,
    collab: Collaborators,
    audio: Path,
    work: Path,
    start: float,
    length: float,
    prompt: str,
    conf: AnalysisSettings,
) -> list[Segment]:
    model = collab.transcriber.model
    await _check(session, run, length / 60.0 * asr_usd_per_minute(model))
    step = ASR_SLICE_S if supports_timestamps(model) else ASR_SLICE_NO_TIMESTAMPS_S
    segments: list[Segment] = []
    t = start
    while t < start + length - 0.05:
        piece = min(step, start + length - t)
        started = time.monotonic()
        clip = await asyncio.to_thread(
            media.cut_audio, audio, work / f"asr_{int(t * 1000):010d}.m4a", t, piece, conf
        )
        run.time("audio_slices", started)
        started = time.monotonic()
        transcript = await collab.transcriber.transcribe(
            clip, prompt=prompt, offset_s=t, duration_s=piece
        )
        run.time("asr", started)
        run.add("asr", transcript.cost_usd, model=model, seconds=round(piece, 2), calls=1)
        segments += transcript.segments
        t += piece
    return segments


async def analyze(
    session: AsyncSession,
    analysis: ContentAnalysis,
    *,
    collab: Collaborators,
    conf: AnalysisSettings,
    rules: ContentRules,
    live_timing_s: Sequence[float] | None = None,
) -> None:
    """Run the pipeline for ``analysis`` (status ``processing``); fills the row."""
    run = _Run(analysis)
    if not analysis.storage_key:
        raise AnalysisFailed("file_missing")
    path = storage.path_of(conf, analysis.storage_key)
    if not path.is_file():
        raise AnalysisFailed("file_missing")
    work = storage.work_dir(conf, analysis.id)
    try:
        started = time.monotonic()
        try:
            info = await asyncio.to_thread(media.probe, path, conf)
        except media.MediaError as exc:
            raise AnalysisFailed(exc.code, exc.detail) from exc
        run.time("probe", started)
        analysis.duration_s = round(info.duration_s, 2)
        if info.duration_s > max_seconds(analysis.kind, conf) + DURATION_TOLERANCE_S:
            raise AnalysisFailed("too_long_live" if analysis.kind == LIVE else "too_long_video")

        product = await collab.product_reader.read(
            session, analysis.shop_id, analysis.tiktok_product_id
        )
        prompt = glossary(product)

        audio: Path | None = None
        if info.has_audio:
            started = time.monotonic()
            try:
                audio = await asyncio.to_thread(media.extract_audio, path, work / "audio.m4a", conf)
            except media.MediaError as exc:
                logger.warning("content_analysis_audio_failed", extra={"code": exc.code})
                audio = None
            run.time("audio", started)

        segments: list[Segment] = []
        windows: list[dict[str, Any]] = []
        if analysis.kind == LIVE:
            segments, windows = await _live_windows(
                session,
                run,
                collab,
                audio,
                work,
                info.duration_s,
                product,
                prompt,
                conf,
                live_timing_s,
            )
        else:
            if audio is not None:
                segments = await _transcribe_slice(
                    session, run, collab, audio, work, 0.0, info.duration_s, prompt, conf
                )
            windows = [{"from_s": 0.0, "to_s": round(info.duration_s, 2)}]

        spans_in = [(float(w["from_s"]), float(w["to_s"])) for w in windows]
        analysed = sum(hi - lo for lo, hi in spans_in)

        # Cuts and keyframes inside the windows only.
        cuts: list[dict[str, Any]] = []
        frames: list[tuple[float, Path]] = []
        for lo, hi in spans_in:
            started = time.monotonic()
            gray = await asyncio.to_thread(
                media.gray_frames, path, conf, start=lo, duration=hi - lo
            )
            cuts += [
                {"t": c.t, "kind": c.kind} for c in detect_cuts(gray, media.CUT_FPS, offset_s=lo)
            ]
            run.time("cuts", started)
            started = time.monotonic()
            frames += await asyncio.to_thread(
                media.keyframes, path, work / "frames", conf, start=lo, duration=hi - lo
            )
            run.time("keyframes", started)

        reads: list[Any] = []
        product_checked = bool(product.name or product.images)
        if frames:
            await _check(session, run, len(frames) * VISION_USD_PER_FRAME_ESTIMATE)
            started = time.monotonic()
            vision = await collab.vision.read(
                frames, product_name=product.name, product_images=product.images
            )
            run.time("vision", started)
            run.add(
                "vision",
                vision.cost_usd,
                model=collab.vision.model,
                frames=len(frames),
                sent=sum(1 for f in vision.frames if not f.reused),
                calls=vision.calls,
                input_tokens=vision.usage.input_tokens,
                output_tokens=vision.usage.output_tokens,
            )
            reads = vision.frames
        spans, first = (
            product_spans(reads, conf.keyframe_every_s) if product_checked else ([], None)
        )

        signals = Signals(
            kind=analysis.kind,
            analysed_s=analysed,
            segments=[
                {"start": s.start, "end": s.end, "text": s.text}
                for s in segments
                if any(lo - 1 <= s.start <= hi for lo, hi in spans_in)
            ],
            screen=screen_lines(reads),
            cuts=cuts,
            product_spans=spans,
            product_first_s=first,
            product_checked=product_checked,
            windows=windows if analysis.kind == LIVE else [],
            product_name=product.name,
            brand=product.brand,
        )

        raw: dict[str, Any] | None = None
        if analysed > 0:
            await _check(session, run, SCORING_USD_ESTIMATE)
            started = time.monotonic()
            outcome = await collab.scorer.score(signals, rules)
            run.time("scoring", started)
            run.add(
                "scoring",
                outcome.cost_usd,
                model=outcome.model,
                input_tokens=outcome.usage.input_tokens,
                output_tokens=outcome.usage.output_tokens,
                calls=1,
                error=outcome.error,
            )
            raw = outcome.raw
        result = build_result(signals, rules, raw)
        if analysis.kind == LIVE and not windows:
            result["issues"].insert(
                0,
                {
                    "code": "other",
                    "text": "Juli không tìm thấy lúc người dẫn nói về sản phẩm trong "
                    f"{conf.live_scan_max_minutes} phút đầu của bản ghi.",
                },
            )
        analysis.signals = {
            "segments": signals.segments[:MAX_STORED_SEGMENTS],
            "screen": signals.screen[:MAX_STORED_SCREEN],
            "cuts": cuts,
            "product_spans": spans,
            "product_first_s": first,
            "windows": windows,
            "keyframes": len(frames),
            "has_audio": info.has_audio,
            "video": {"width": info.width, "height": info.height, "codec": info.video_codec},
        }
        analysis.result = result
        analysis.status = STATUS_DONE
        analysis.completed_at = _now()
        run.flush()
        finish(analysis, conf)
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def _live_windows(
    session: AsyncSession,
    run: _Run,
    collab: Collaborators,
    audio: Path | None,
    work: Path,
    duration: float,
    product: ProductInfo,
    prompt: str,
    conf: AnalysisSettings,
    live_timing_s: Sequence[float] | None,
) -> tuple[list[Segment], list[dict[str, Any]]]:
    """The LIVE windows (TikTok timing, else ASR mentions) and their transcript."""
    segments: list[Segment] = []
    done: set[int] = set()

    async def slice_at(index: int) -> None:
        if audio is None or index in done:
            return
        start = index * ASR_SLICE_S
        if start >= duration:
            return
        done.add(index)
        segments.extend(
            await _transcribe_slice(
                session,
                run,
                collab,
                audio,
                work,
                start,
                min(ASR_SLICE_S, duration - start),
                prompt,
                conf,
            )
        )

    if live_timing_s:
        windows = windows_from(live_timing_s, duration=duration, conf=conf, source="tiktok")
    else:
        terms = mention_terms(product)
        limit = min(duration, conf.live_scan_max_minutes * 60.0)
        index = 0
        windows = []
        while index * ASR_SLICE_S < limit and audio is not None and terms:
            await slice_at(index)
            windows = windows_from(
                find_mentions(sorted(segments, key=lambda s: s.start), terms),
                duration=duration,
                conf=conf,
                source="asr_mention",
            )
            index += 1
            if len(windows) >= conf.live_max_windows and windows[-1]["to_s"] <= index * ASR_SLICE_S:
                break
    # Every window fully transcribed.
    for window in windows:
        first = int(window["from_s"] // ASR_SLICE_S)
        last = int(max(window["from_s"], window["to_s"] - 0.01) // ASR_SLICE_S)
        for index in range(first, last + 1):
            await slice_at(index)
    segments.sort(key=lambda s: s.start)
    return segments, windows


def finish(analysis: ContentAnalysis, conf: AnalysisSettings) -> None:
    """Delete the uploaded file; keep only derived data."""
    storage.delete(conf, analysis.storage_key)
    if analysis.storage_key:
        analysis.file_deleted_at = _now()
    analysis.storage_key = None


def fail(
    analysis: ContentAnalysis, conf: AnalysisSettings, code: str, *, delete: bool = True
) -> None:
    analysis.status = STATUS_FAILED
    analysis.error_code = code[:50]
    analysis.error_message = ERROR_VI.get(code, ERROR_VI["media_unreadable"])
    analysis.completed_at = _now()
    if delete:
        finish(analysis, conf)


def refuse(analysis: ContentAnalysis, conf: AnalysisSettings, exc: costs.CostCapExceeded) -> None:
    analysis.status = STATUS_REFUSED
    analysis.error_code = exc.code
    analysis.error_message = exc.message_vi
    analysis.completed_at = _now()
    finish(analysis, conf)


__all__ = [
    "ERROR_VI",
    "STATUS_AWAITING",
    "STATUS_DONE",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_PROCESSING",
    "STATUS_QUEUED",
    "STATUS_REFUSED",
    "TERMINAL",
    "AnalysisFailed",
    "Collaborators",
    "ProductInfo",
    "ProductReader",
    "analyze",
    "fail",
    "find_mentions",
    "finish",
    "fold",
    "glossary",
    "mention_terms",
    "refuse",
    "windows_from",
]
