"""P15 content analysis of seller-uploaded videos / LIVE recordings (contract p15).

Fixture media is GENERATED at test time with ffmpeg (``testsrc`` / ``color`` +
``sine``), never committed; tests needing it skip when ffmpeg is absent. OpenAI
is never called: transcription goes through ``httpx.MockTransport``, vision and
scoring through a recording fake adapter or fake collaborators.

- media: probe, sniff (a renamed non-video is refused before ffprobe), audio,
  gray frames → the two cuts of the fixture, keyframes every 2 s;
- the OpenAI wire: transcription multipart (model, ``vi``, glossary prompt,
  word timestamps), the adapter's image parts, vision batching / reuse;
- the result: numbers from signals, never from the model; banned suggestions
  dropped; claims in the seller's own video flagged; CTA by index;
- the pipeline (video, LIVE windows from ASR mentions), cost per stage, the file
  deleted after analysis, kept for a retry on a provider error, deleted after
  the last attempt; the monthly cap refusing before a paid step and at upload;
- uploads: slot, signed token, chunks / offsets, first-chunk sniff, expiry; the
  routes (201 / 200 / 403 / 404 / 402) and the enqueue;
- the task: idempotent, per-shop lock; the 24 h sweep;
- content runs: the best / weakest analyses reach the drafter's prompt.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from juli_backend.models.content_analysis import ContentAnalysis
from juli_backend.models.models import WorkflowRun
from juli_backend.models.run_changes import ShopRule
from juli_backend.services.agent.llm.blocks import AssistantTurn, FinalResponse, Usage
from juli_backend.services.content_analysis import (
    context,
    costs,
    media,
    pipeline,
    scoring,
    storage,
    uploads,
)
from juli_backend.services.content_analysis.config import settings
from juli_backend.services.content_analysis.cuts import detect_cuts
from juli_backend.services.content_analysis.openai_media import (
    FrameRead,
    OpenAITranscriber,
    OpenAIVision,
    ProviderError,
    Segment,
    Transcript,
    VisionResult,
    parse_transcription,
)
from juli_backend.services.content_analysis.pipeline import Collaborators, ProductInfo
from juli_backend.services.content_cards.guardrails import ContentRules
from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
from juli_backend.workers.tasks import content_analysis as task
from tests.support.lever_flows import api_client, seed_shop

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg/ffprobe not installed")
PRODUCT = "1729000000000000001"


# -- fixture media (generated, never committed) ------------------------------------------


def make_video(
    path: Path,
    *,
    segments: tuple[str, ...] = ("red", "testsrc", "blue"),
    seg_s: float = 2.0,
    audio: bool = True,
) -> Path:
    """A ``len(segments) × seg_s`` second MP4: hard cuts between segments, a sine tone."""
    args = ["ffmpeg", "-v", "error", "-y"]
    for seg in segments:
        source = (
            f"testsrc=s=320x240:d={seg_s}:r=25"
            if seg == "testsrc"
            else f"color=c={seg}:s=320x240:d={seg_s}:r=25"
        )
        args += ["-f", "lavfi", "-i", source]
    n = len(segments)
    total = n * seg_s
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={total}"]
    chain = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    args += ["-filter_complex", chain, "-map", "[v]"]
    if audio:
        args += ["-map", f"{n}:a", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(path)]
    subprocess.run(args, check=True, timeout=60)
    return path


@pytest.fixture
def conf(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_UPLOAD_SIGNING_SECRET", "test-secret-p15")
    return dataclasses.replace(settings(), upload_dir=str(tmp_path / "uploads"))


@pytest.fixture
def video(tmp_path) -> Path:
    if not FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    return make_video(tmp_path / "fixture.mp4")


# -- fakes ---------------------------------------------------------------------------------


class FakeTranscriber:
    model = "whisper-1"

    def __init__(self, lines: dict[float, str] | None = None, fail: bool = False) -> None:
        # absolute second → text
        self.lines = (
            lines
            if lines is not None
            else {
                0.2: "Da khô sau một tuần dùng mặt nạ đất sét này",
                3.0: "Bấm giỏ hàng vàng để đặt ngay",
            }
        )
        self.calls: list[tuple[float, float, str]] = []
        self.fail = fail

    async def transcribe(self, audio, *, prompt, offset_s, duration_s):
        assert audio.exists() and audio.suffix == ".m4a"  # an audio slice, never the upload
        self.calls.append((offset_s, duration_s, prompt))
        if self.fail:
            raise ProviderError("HTTP 500")
        segs = [
            Segment(start=t, end=t + 1.5, text=text)
            for t, text in sorted(self.lines.items())
            if offset_s <= t < offset_s + duration_s
        ]
        return Transcript(
            segments=segs, seconds=duration_s, cost_usd=round(duration_s / 60 * 0.006, 6)
        )


class FakeVision:
    model = "gpt-5.4-nano"

    def __init__(self, visible_from: float = 2.0) -> None:
        self.visible_from = visible_from
        self.seen: list[float] = []

    async def read(self, frames, *, product_name, product_images):
        self.seen += [t for t, _ in frames]
        for _t, path in frames:
            assert path.suffix == ".jpg"
        reads = [
            FrameRead(
                t=t, text="GIÁ 199K" if t >= 4 else "", product_visible=t >= self.visible_from
            )
            for t, _ in frames
        ]
        return VisionResult(frames=reads, usage=Usage(1000, 200), cost_usd=0.00013, calls=1)


class FakeScorer:
    model = "gpt-5.4-nano"

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        self.raw = raw or {
            "hook": {"verdict": "ok", "reason": "Mở bằng vấn đề da khô, nhưng chưa thấy sản phẩm."},
            "cta": {"source": "speech", "index": 1, "text": "Bấm giỏ hàng vàng để đặt ngay"},
            "issues": [{"code": "hook_weak", "text": "Câu mở chưa có chữ trên màn hình."}],
            "suggestions": [
                "Đưa sản phẩm vào khung hình ngay giây đầu.",
                "Nói đây là sản phẩm rẻ nhất thị trường.",  # banned claim → dropped
                "Thêm chữ trên màn hình cho câu mở.",
            ],
        }
        self.signals: list[scoring.Signals] = []

    async def score(self, signals, rules):
        self.signals.append(signals)
        return scoring.ScoreOutcome(self.model, Usage(800, 300), 0.00016, self.raw)


class FakeProducts:
    def __init__(self, info: ProductInfo | None = None) -> None:
        self.info = info or ProductInfo(
            name="Mặt nạ đất sét 100g",
            brand="Bùn Xanh",
            label="MN-015",
            images=["https://p16.example.com/mn015.jpg"],
            seo_words=["mặt nạ đất sét"],
        )

    async def read(self, session, shop_id, product_id):
        return self.info


def failing() -> Collaborators:
    return collab(transcriber=FakeTranscriber(fail=True))


def collab(**kw: Any) -> Collaborators:
    return Collaborators(
        transcriber=kw.get("transcriber") or FakeTranscriber(),
        vision=kw.get("vision") or FakeVision(),
        scorer=kw.get("scorer") or FakeScorer(),
        product_reader=kw.get("products") or FakeProducts(),
    )


async def _uploaded(
    session,
    shop,
    conf,
    path: Path,
    *,
    kind="video",
    chunk: int = 40_000,
    content_ref: str | None = "video:7300000000000000001",
) -> ContentAnalysis:
    data = path.read_bytes()
    row = await uploads.create_upload(
        session,
        shop_id=shop.id,
        user_id=shop.user_id,
        kind=kind,
        content_ref=content_ref if kind == "video" else "live:7400000000000000001",
        tiktok_product_id=PRODUCT,
        workflow_run_id=None,
        file_name=path.name,
        content_type="video/mp4",
        size_bytes=len(data),
        conf=conf,
    )
    for offset in range(0, len(data), chunk):
        uploads.receive_chunk(row, offset=offset, data=data[offset : offset + chunk], conf=conf)
    assert row.status == pipeline.STATUS_QUEUED
    await session.commit()
    return row


# -- media ---------------------------------------------------------------------------------


@needs_ffmpeg
def test_probe_audio_cuts_and_keyframes_on_the_generated_fixture(video, conf, tmp_path):
    info = media.probe(video, conf)
    assert 5.9 <= info.duration_s <= 6.1 and info.has_audio and info.width == 320
    gray = media.gray_frames(video, conf)
    assert gray.shape[1:] == (36, 64)
    cuts = detect_cuts(gray, media.CUT_FPS)
    assert [round(c.t) for c in cuts] == [2, 4] and all(c.kind == "hard" for c in cuts)
    frames = media.keyframes(video, tmp_path / "kf", conf)
    assert [t for t, _ in frames] == [0.0, 2.0, 4.0]
    audio = media.extract_audio(video, tmp_path / "a.m4a", conf)
    assert audio.stat().st_size > 1000


def test_a_renamed_non_video_is_refused_before_any_parser(tmp_path, conf):
    fake = tmp_path / "virus.mp4"
    fake.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 200)
    assert not media.sniff(fake)
    with pytest.raises(media.MediaError) as err:
        media.probe(fake, conf)
    assert err.value.code == "not_a_video"


@needs_ffmpeg
def test_a_file_without_a_video_stream_is_refused(tmp_path, conf):
    path = tmp_path / "audio_only.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=2",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        timeout=30,
    )
    with pytest.raises(media.MediaError) as err:
        media.probe(path, conf)
    assert err.value.code == "no_video_stream"


# -- OpenAI wire ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcription_request_is_vietnamese_with_the_glossary_and_word_timestamps(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "Bấm giỏ hàng",
                "segments": [{"start": 1.0, "end": 2.5, "text": " Bấm giỏ hàng "}],
                "words": [{"word": "Bấm", "start": 1.0, "end": 1.3}],
            },
        )

    audio = tmp_path / "slice.m4a"
    audio.write_bytes(b"\x00\x00\x00\x18ftypM4A ")
    client = OpenAITranscriber("whisper-1", transport=httpx.MockTransport(handler))
    out = await client.transcribe(
        audio, prompt="Mặt nạ đất sét, Bùn Xanh", offset_s=600.0, duration_s=60.0
    )
    body = seen["body"].decode("utf-8", "replace")
    assert seen["path"] == "/v1/audio/transcriptions" and seen["auth"] == "Bearer sk-test"
    for field in (
        'name="model"',
        "whisper-1",
        'name="language"',
        "vi",
        "Mặt nạ đất sét",
        "verbose_json",
        "timestamp_granularities[]",
        "word",
    ):
        assert field in body
    assert out.segments == [Segment(start=601.0, end=602.5, text="Bấm giỏ hàng")]
    assert out.words[0].start == 601.0
    assert out.cost_usd == pytest.approx(0.006)


@pytest.mark.asyncio
async def test_transcription_http_error_is_a_retryable_provider_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    audio = tmp_path / "slice.m4a"
    audio.write_bytes(b"x")
    client = OpenAITranscriber(
        "whisper-1", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    with pytest.raises(ProviderError) as err:
        await client.transcribe(audio, prompt="", offset_s=0, duration_s=1)
    assert "HTTP 500" in str(err.value)


def test_a_model_without_timestamps_gets_its_slice_time():
    out = parse_transcription(
        {"text": "chào"}, offset_s=30.0, duration_s=30.0, model="gpt-4o-mini-transcribe"
    )
    assert out.segments == [Segment(30.0, 60.0, "chào")]
    assert out.cost_usd == pytest.approx(0.0015)


def test_the_adapter_passes_image_parts_through():
    from juli_backend.services.agent.llm.openai_adapter import _translate_message

    parts = [
        {"type": "input_text", "text": "x"},
        {"type": "input_image", "image_url": "data:image/jpeg;base64,AA", "detail": "low"},
    ]
    assert _translate_message({"role": "user", "content": parts}) == {
        "role": "user",
        "content": parts,
    }
    assert (
        _translate_message({"role": "user", "content": "hi"})["content"][0]["type"] == "input_text"
    )


class RecordingAdapter:
    def __init__(self, reply) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AssistantTurn(
            blocks=(FinalResponse(content=self.reply(kwargs)),), usage=Usage(2000, 100)
        )


@needs_ffmpeg
@pytest.mark.asyncio
async def test_vision_sends_low_detail_keyframes_and_product_images_and_reuses_repeats(
    video, conf, tmp_path
):
    frames = media.keyframes(
        video, tmp_path / "kf", conf, every_s=1.0
    )  # 0..5: 2 red, 2 test, 2 blue

    def reply(kwargs):
        parts = kwargs["messages"][0]["content"]
        idx = [
            int(p["text"].split()[-1].rstrip(":"))
            for p in parts
            if p["type"] == "input_text" and p["text"].startswith("Khung hình số")
        ]
        return json.dumps(
            {
                "frames": [
                    {"index": i, "text": "SALE" if i else "", "product_visible": i >= 2}
                    for i in idx
                ]
            }
        )

    adapter = RecordingAdapter(reply)
    out = await OpenAIVision("gpt-5.4-nano", adapter=adapter).read(
        frames, product_name="Mặt nạ", product_images=["https://p16.example.com/a.jpg"]
    )
    parts = adapter.calls[0]["messages"][0]["content"]
    images = [p for p in parts if p["type"] == "input_image"]
    assert images[0]["image_url"] == "https://p16.example.com/a.jpg"
    assert all(p["detail"] == "low" for p in images)
    assert all(p["image_url"].startswith(("https://", "data:image/jpeg;base64,")) for p in images)
    assert adapter.calls[0]["response_format"].schema["required"] == ["frames"]
    assert len(out.frames) == len(frames)
    # The two red frames are one picture: the second is not sent again.
    assert out.frames[1].reused and not out.frames[0].reused
    assert out.cost_usd > 0 and out.calls == 1


# -- result --------------------------------------------------------------------------------


def _signals(**kw: Any) -> scoring.Signals:
    base = dict(
        kind="video",
        analysed_s=30.0,
        segments=[
            {"start": 0.2, "end": 1.5, "text": "Da khô sau một tuần"},
            {"start": 26.0, "end": 28.0, "text": "Bấm giỏ hàng vàng nhé"},
        ],
        screen=[{"t": 0.0, "text": "DA KHÔ?"}],
        cuts=[{"t": 3.0, "kind": "hard"}, {"t": 9.0, "kind": "hard"}],
        product_spans=[[6.0, 30.0]],
        product_first_s=6.0,
        product_checked=True,
    )
    base.update(kw)
    return scoring.Signals(**base)


def test_numbers_come_from_the_signals_and_words_are_checked():
    rules = ContentRules(tone="vui vẻ", banned_terms=("xịn xò",))
    raw = {
        "hook": {"verdict": "weak", "reason": "Chưa thấy sản phẩm."},
        "cta": {"source": "speech", "index": 1, "text": "Bấm giỏ hàng vàng nhé"},
        "issues": [{"code": "hook_weak", "text": "Mở đầu chưa có sản phẩm."}],
        "suggestions": ["Cầm sản phẩm ngay giây đầu.", "Gọi nó là hàng xịn xò.", "Rẻ nhất luôn!"],
    }
    result = scoring.build_result(_signals(), rules, raw)
    assert result["product_first_s"] == 6.0  # from the vision timeline
    assert result["cta"] == {
        "present": True,
        "at_s": 26.0,
        "text": "Bấm giỏ hàng vàng nhé",
        "line": "Có lời kêu gọi mua ở giây 26,0",
    }
    assert result["pacing"]["cuts_per_10s"] == 0.7
    assert result["suggestions"] == ["Cầm sản phẩm ngay giây đầu."]
    assert result["suggestions_dropped"] == 2
    codes = [i["code"] for i in result["issues"]]
    assert codes[:2] == ["product_late", "slow_pacing"] and "hook_weak" in codes
    assert result["hook"]["label"] == "Yếu"


def test_a_cta_index_that_does_not_exist_is_not_trusted_and_claims_are_flagged():
    raw = {
        "hook": {"verdict": "ok", "reason": ""},
        "cta": {"source": "speech", "index": 9, "text": "x"},
        "issues": [],
        "suggestions": [],
    }
    sig = _signals(segments=[{"start": 1.0, "end": 2.0, "text": "Cam kết 100 % chữa khỏi mụn"}])
    result = scoring.build_result(sig, ContentRules(), raw)
    assert result["cta"]["present"] is False and result["cta"]["at_s"] is None
    issue = next(i for i in result["issues"] if i["code"] == "banned_claim")
    assert "cam kết 100" in issue["text"] and "chữa khỏi" in issue["text"]


def test_the_scoring_prompt_carries_derived_signals_only():
    prompt = scoring.user_prompt(_signals(), ContentRules(tone="thân mật", banned_terms=("rẻ",)))
    data = json.loads(prompt.split("\n", 1)[1])
    assert set(data) >= {"lời_thoại", "chữ_trên_màn_hình", "cắt_cảnh", "sản_phẩm_trên_màn_hình"}
    assert data["quy_tắc_người_bán"] == {"giọng_văn": "thân mật", "từ_cấm": ["rẻ"]}
    assert "base64" not in prompt and ".mp4" not in prompt


# -- pipeline ------------------------------------------------------------------------------


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_video_is_analysed_costed_and_its_file_deleted(session, conf, video):
    shop, _product = await seed_shop(session)
    row = await _uploaded(session, shop, conf, video)
    path = storage.path_of(conf, row.storage_key)
    assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
    scorer, vision, asr = FakeScorer(), FakeVision(), FakeTranscriber()
    row.status = pipeline.STATUS_PROCESSING
    started = time.monotonic()
    await pipeline.analyze(
        session,
        row,
        collab=collab(scorer=scorer, vision=vision, transcriber=asr),
        conf=conf,
        rules=ContentRules(),
    )
    elapsed = time.monotonic() - started
    await session.commit()

    assert row.status == "done" and row.completed_at is not None
    assert not path.exists() and row.storage_key is None and row.file_deleted_at is not None
    assert not list(Path(conf.upload_dir).glob("work-*"))
    result = row.result
    assert result["product_first_s"] == 2.0
    assert result["cta"]["present"] and result["cta"]["at_s"] == 3.0
    assert result["pacing"]["cuts"] == 2
    assert result["suggestions"] == [
        "Đưa sản phẩm vào khung hình ngay giây đầu.",
        "Thêm chữ trên màn hình cho câu mở.",
    ]
    # ASR: one call over the whole 6 s, the glossary as prompt.
    assert len(asr.calls) == 1 and asr.calls[0][0] == 0.0
    assert "Mặt nạ đất sét 100g" in asr.calls[0][2] and "Bùn Xanh" in asr.calls[0][2]
    assert vision.seen == [0.0, 2.0, 4.0]
    # The scorer saw derived signals only.
    signals = scorer.signals[0]
    assert signals.cuts and signals.screen == [{"t": 4.0, "text": "GIÁ 199K"}]
    usage = row.usage
    assert set(usage) >= {"asr", "vision", "scoring", "timings_s"}
    assert float(row.cost_usd) == pytest.approx(0.0006 + 0.00013 + 0.00016, abs=1e-6)
    assert elapsed < 30
    view = uploads.view(row)
    assert view["status_label"] == "Đã phân tích" and view["file_deleted"] is True


@needs_ffmpeg
@pytest.mark.asyncio
async def test_a_live_is_analysed_only_around_the_product_mentions(session, conf, tmp_path):
    # 24 s "LIVE": 8 segments of 3 s; the host names the product at 13 s.
    path = make_video(
        tmp_path / "live.mp4",
        segments=("red", "green", "blue", "testsrc", "red", "green", "blue", "red"),
        seg_s=3.0,
    )
    conf = dataclasses.replace(conf, live_window_before_s=2.0, live_window_after_s=5.0)
    shop, _ = await seed_shop(session)
    row = await _uploaded(session, shop, conf, path, kind="live")
    asr = FakeTranscriber(
        {1.0: "Chào cả nhà", 13.0: "Giờ tới mặt nạ đất sét nè", 16.0: "Chốt đơn bấm giỏ hàng nha"}
    )
    vision = FakeVision(visible_from=13.0)
    await pipeline.analyze(
        session, row, collab=collab(transcriber=asr, vision=vision), conf=conf, rules=ContentRules()
    )
    assert row.status == "done"
    assert row.result["windows"] == [
        {"from_s": 11.0, "to_s": 18.0, "mention_s": 13.0, "source": "asr_mention"}
    ]
    assert all(11.0 <= t < 18.0 for t in vision.seen)  # keyframes only inside the window
    assert all(11.0 - 1 <= s["start"] <= 18.0 for s in row.signals["segments"])
    assert row.result["hook"]["from_s"] == 13.0


@needs_ffmpeg
@pytest.mark.asyncio
async def test_over_the_monthly_cap_the_asr_step_is_refused_and_nothing_is_spent(
    session, conf, video
):
    shop, product = await seed_shop(session)
    row = await _uploaded(session, shop, conf, video)
    session.add(
        ShopRule(
            shop_id=shop.id,
            rule_key="openai_monthly_cap_usd",
            value=0.5,
            set_by="team",
            set_at=datetime(2026, 10, 1),
        )
    )
    session.add(
        WorkflowRun(
            shop_id=shop.id,
            product_id=product.id,
            subject_ref="x",
            state={},
            status="completed",
            prompt_version="v",
            prompt_sha256="0" * 64,
            cost_usd=Decimal("0.4999"),
        )
    )
    await session.flush()
    asr = FakeTranscriber()
    with pytest.raises(costs.CostCapExceeded) as err:
        await pipeline.analyze(
            session, row, collab=collab(transcriber=asr), conf=conf, rules=ContentRules()
        )
    pipeline.refuse(row, conf, err.value)
    assert asr.calls == []
    assert row.status == "refused" and row.error_code == "cost_cap_reached"
    assert "hạn mức" in row.error_message and row.storage_key is None
    assert float(row.cost_usd) == 0.0


@pytest.mark.asyncio
async def test_the_cap_refuses_a_new_upload_with_a_vietnamese_402(session, conf, engine):
    shop, _ = await seed_shop(session)
    session.add(
        ShopRule(
            shop_id=shop.id,
            rule_key="openai_monthly_cap_usd",
            value=0,
            set_by="team",
            set_at=datetime(2026, 10, 1),
        )
    )
    await session.commit()
    async with api_client(engine, shop) as client:
        res = await client.post(
            "/v1/demo/content-analysis",
            json={
                "kind": "video",
                "file_name": "a.mp4",
                "content_type": "video/mp4",
                "size_bytes": 10,
            },
        )
    assert res.status_code == 402
    assert res.json()["detail"]["code"] == "cost_cap_reached"
    assert "hạn mức" in res.json()["detail"]["message"]


def test_the_month_starts_at_midnight_vietnam_time():
    assert costs.month_start_utc(datetime(2026, 10, 1, 1, 0, tzinfo=UTC)) == datetime(
        2026, 9, 30, 17
    )
    assert costs.month_start_utc(datetime(2026, 9, 30, 16, 59, tzinfo=UTC)) == datetime(
        2026, 8, 31, 17
    )


# -- uploads -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_slot_validation(session, conf):
    shop, _ = await seed_shop(session)
    kw = dict(
        shop_id=shop.id,
        user_id=None,
        content_ref=None,
        tiktok_product_id=PRODUCT,
        workflow_run_id=None,
        conf=conf,
    )
    bad = [
        (dict(kind="video", file_name="a.exe", content_type="video/mp4", size_bytes=10), 415),
        (dict(kind="video", file_name="a.mp4", content_type="application/zip", size_bytes=10), 415),
        (
            dict(kind="video", file_name="a.mp4", content_type="video/mp4", size_bytes=501 * 2**20),
            413,
        ),
        (dict(kind="tv", file_name="a.mp4", content_type="video/mp4", size_bytes=10), 422),
    ]
    for args, code in bad:
        with pytest.raises(uploads.UploadRefused) as err:
            await uploads.create_upload(session, **{**kw, **args})
        assert err.value.status == code
    with pytest.raises(uploads.UploadRefused) as err:
        await uploads.create_upload(
            session,
            **{**kw, "content_ref": "live:1"},
            kind="video",
            file_name="a.mp4",
            content_type="video/mp4",
            size_bytes=10,
        )
    assert err.value.code == "bad_content_ref"
    # A LIVE may be larger than a video.
    row = await uploads.create_upload(
        session,
        **kw,
        kind="live",
        file_name="../../etc/x.MOV",
        content_type="video/quicktime",
        size_bytes=2 * 2**30,
    )
    assert row.file_name == "x.MOV" and row.storage_key == f"{shop.id}/{row.id}.upload"
    await uploads.create_upload(
        session, **kw, kind="video", file_name="b.mp4", content_type="video/mp4", size_bytes=10
    )
    with pytest.raises(uploads.UploadRefused) as err:  # 2 in flight per shop
        await uploads.create_upload(
            session, **kw, kind="video", file_name="c.mp4", content_type="video/mp4", size_bytes=10
        )
    assert err.value.code == "too_many_uploads"


@pytest.mark.asyncio
async def test_chunks_offsets_first_box_and_expiry(session, conf):
    shop, _ = await seed_shop(session)
    payload = b"\x00\x00\x00\x18ftypisom" + b"x" * 100
    row = await uploads.create_upload(
        session,
        shop_id=shop.id,
        user_id=None,
        kind="video",
        content_ref=None,
        tiktok_product_id=PRODUCT,
        workflow_run_id=None,
        file_name="a.mp4",
        content_type="video/mp4",
        size_bytes=len(payload),
        conf=conf,
    )
    uploads.receive_chunk(row, offset=0, data=payload[:50], conf=conf)
    with pytest.raises(uploads.UploadRefused) as err:  # a resent first chunk
        uploads.receive_chunk(row, offset=0, data=payload[:50], conf=conf)
    assert err.value.code == "offset_mismatch" and err.value.extra["expected_offset"] == 50
    with pytest.raises(uploads.UploadRefused) as err:
        uploads.receive_chunk(row, offset=50, data=payload[50:] + b"extra", conf=conf)
    assert err.value.code == "size_mismatch"
    uploads.receive_chunk(row, offset=50, data=payload[50:], conf=conf)
    assert row.status == "queued" and storage.path_of(conf, row.storage_key).read_bytes() == payload

    exe = await uploads.create_upload(
        session,
        shop_id=shop.id,
        user_id=None,
        kind="video",
        content_ref=None,
        tiktok_product_id=PRODUCT,
        workflow_run_id=None,
        file_name="b.mp4",
        content_type="video/mp4",
        size_bytes=100,
        conf=conf,
    )
    with pytest.raises(uploads.UploadRefused) as err:
        uploads.receive_chunk(exe, offset=0, data=b"MZ\x90\x00" + b"\x00" * 96, conf=conf)
    assert err.value.status == 415 and exe.status == "failed" and exe.storage_key is None

    stale = await uploads.create_upload(
        session,
        shop_id=shop.id,
        user_id=None,
        kind="video",
        content_ref=None,
        tiktok_product_id=PRODUCT,
        workflow_run_id=None,
        file_name="c.mp4",
        content_type="video/mp4",
        size_bytes=100,
        conf=conf,
        now=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=7),
    )
    with pytest.raises(uploads.UploadRefused) as err:
        uploads.receive_chunk(stale, offset=0, data=payload[:10], conf=conf)
    assert err.value.status == 410 and stale.status == "expired"


def test_the_upload_token_binds_the_slot_and_expires(monkeypatch):
    monkeypatch.setenv("CONTENT_UPLOAD_SIGNING_SECRET", "s")
    a, shop = uuid.uuid4(), uuid.uuid4()
    later = datetime.now(UTC) + timedelta(hours=1)
    token = storage.sign(a, shop, later)
    assert storage.verify(token, a, shop)
    assert not storage.verify(token, uuid.uuid4(), shop)
    assert not storage.verify(token, a, uuid.uuid4())
    assert not storage.verify(token, a, shop, now=later.timestamp() + 1)
    assert not storage.verify("garbage", a, shop)


def test_storage_keys_cannot_escape_the_upload_dir(conf):
    with pytest.raises(ValueError) as err:
        storage.path_of(conf, "../../etc/passwd")
    assert "escapes" in str(err.value)


def test_the_sweep_deletes_files_older_than_a_day(conf):
    base = storage.root(conf)
    old, new = base / "s" / "old.upload", base / "s" / "new.upload"
    old.parent.mkdir()
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    assert storage.sweep(conf) == 1
    assert not old.exists() and new.exists()


# -- routes --------------------------------------------------------------------------------


@needs_ffmpeg
@pytest.mark.asyncio
async def test_the_routes_open_a_slot_take_chunks_queue_and_list(
    engine, session, conf, video, monkeypatch
):
    from juli_backend.api.routes import demo_content_analysis as routes

    monkeypatch.setattr(routes, "settings", lambda: dataclasses.replace(conf, chunk_bytes=50_000))
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(routes, "_enqueue", lambda a, s: queued.append(a) or "task-1")
    shop, _ = await seed_shop(session)
    other, _ = await seed_shop(session, "b")
    await session.commit()
    data = video.read_bytes()
    async with api_client(engine, shop) as client:
        res = await client.post(
            "/v1/demo/content-analysis",
            json={
                "kind": "video",
                "content_ref": "video:7300000000000000001",
                "tiktok_product_id": PRODUCT,
                "file_name": "fixture.mp4",
                "content_type": "video/mp4",
                "size_bytes": len(data),
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()["data"]
        url, up_token = body["upload"]["url"], body["upload"]["token"]
        assert (
            body["upload"]["chunk_bytes"] == 50_000
            and body["analysis"]["status"] == "awaiting_upload"
        )
        bad = await client.put(
            f"{url}?offset=0", content=data[:10], headers={"X-Upload-Token": "0.deadbeefdeadbeef"}
        )
        assert bad.status_code == 403
        too_big = await client.put(
            f"{url}?offset=0", headers={"X-Upload-Token": up_token}, content=data[:60_000]
        )
        assert too_big.status_code == 413
        last = None
        for offset in range(0, len(data), 50_000):
            last = await client.put(
                f"{url}?offset={offset}",
                headers={"X-Upload-Token": up_token},
                content=data[offset : offset + 50_000],
            )
            assert last.status_code == 200, last.text
        assert last is not None and last.json()["data"]["status"] == "queued"
        listed = await client.get(f"/v1/demo/content-analysis?tiktok_product_id={PRODUCT}")
        assert [a["status"] for a in listed.json()["data"]] == ["queued"]
    assert len(queued) == 1
    async with api_client(engine, other) as client:  # another shop: 404, never 403
        res = await client.get(f"/v1/demo/content-analysis/{queued[0]}")
        assert res.status_code == 404
        res = await client.get("/v1/demo/content-analysis")
        assert res.json()["data"] == []


# -- task ----------------------------------------------------------------------------------


@needs_ffmpeg
@pytest.mark.asyncio
async def test_the_task_is_idempotent_locked_per_shop_and_retries_provider_errors(
    engine, session, conf, video
):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    shop, _ = await seed_shop(session)
    row = await _uploaded(session, shop, conf, video)
    lock = InMemoryShopIngestLock()
    held = lock.try_acquire(str(shop.id), "content_analysis", ttl_seconds=60)
    out = await task.run_analysis(
        str(row.id),
        str(shop.id),
        session_factory=factory,
        lock=lock,
        collaborators=collab,
        conf=conf,
    )
    assert out == task.OUTCOME_LOCKED
    lock.release(str(shop.id), "content_analysis", held)

    out = await task.run_analysis(
        str(row.id),
        str(shop.id),
        session_factory=factory,
        lock=lock,
        collaborators=failing,
        conf=conf,
    )
    await session.refresh(row)
    assert out == task.OUTCOME_RETRY and row.status == "queued" and row.attempts == 1
    assert storage.path_of(conf, row.storage_key).is_file()  # kept for the retry

    out = await task.run_analysis(
        str(row.id),
        str(shop.id),
        session_factory=factory,
        lock=lock,
        collaborators=collab,
        conf=conf,
    )
    await session.refresh(row)
    assert out == task.OUTCOME_DONE and row.status == "done" and row.storage_key is None
    again = await task.run_analysis(
        str(row.id),
        str(shop.id),
        session_factory=factory,
        lock=lock,
        collaborators=collab,
        conf=conf,
    )
    assert again == task.OUTCOME_SKIPPED
    assert not lock.is_held(str(shop.id), "content_analysis")


@needs_ffmpeg
@pytest.mark.asyncio
async def test_the_last_failed_attempt_deletes_the_file(engine, session, conf, video):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    shop, _ = await seed_shop(session)
    row = await _uploaded(session, shop, conf, video)
    key = row.storage_key
    for _ in range(task.MAX_ATTEMPTS):
        out = await task.run_analysis(
            str(row.id),
            str(shop.id),
            session_factory=factory,
            lock=InMemoryShopIngestLock(),
            collaborators=failing,
            conf=conf,
        )
    await session.refresh(row)
    assert out == task.OUTCOME_FAILED and row.status == "failed"
    assert row.error_code == "provider_final" and not storage.path_of(conf, key).exists()


def test_the_tasks_are_routed_to_their_own_queue_and_the_worker_consumes_it():
    from juli_backend.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes[task.ANALYZE_TASK] == {"queue": "content_analysis"}
    assert routes[task.SWEEP_TASK] == {"queue": "content_analysis"}
    assert celery_app.conf.beat_schedule["content-analysis-sweep"]["task"] == task.SWEEP_TASK
    unit = Path(__file__).resolve().parents[2] / "infra/systemd/juli-celery-worker.service"
    exec_start = unit.read_text(encoding="utf-8").split("ExecStart=", 1)[1]
    assert "content_analysis" in exec_start.split("-Q ", 1)[1].split()[0].split(",")


# -- content runs --------------------------------------------------------------------------


def test_best_and_weakest_analyses_are_picked_by_the_tiktok_rate():
    best = {"ref": context.ref_hash("video:1"), "kind": "video", "mở_đầu": "Mạnh"}
    weak = {"ref": context.ref_hash("video:2"), "kind": "video", "mở_đầu": "Yếu"}
    loose = {"ref": None, "kind": "video", "mở_đầu": "Tạm được"}
    rates = {best["ref"]: 0.05, weak["ref"]: 0.01}
    picked = context.pick([weak, loose, best], rates)
    assert [p["nhóm"] for p in picked] == ["tốt nhất", "yếu nhất"]
    assert picked[0]["mở_đầu"] == "Mạnh" and "ref" not in picked[0]
    assert [p["nhóm"] for p in context.pick([loose], {})] == ["đã tải lên"]
    # Same hash the content tools give the row.
    from juli_backend.services.content_cards.tools import _ref

    assert context.ref_hash("video:123") == _ref("video", "123")


def test_the_drafter_prompt_carries_the_analyses_only_when_there_are_some():
    from juli_backend.services.content_cards import prompts
    from juli_backend.services.content_cards.guardrails import DraftFacts

    facts = DraftFacts(product_label="MN-015", product_title="Mặt nạ")
    plain = prompts.user_prompt(
        "video", facts, ContentRules(), performance={}, product={}, seo_words=[], examples=[]
    )
    assert "phân_tích_video" not in plain
    rich = prompts.user_prompt(
        "video",
        facts,
        ContentRules(),
        performance={},
        product={},
        seo_words=[],
        examples=[],
        analyses=[{"nhóm": "yếu nhất", "sản_phẩm_xuất_hiện": "giây 6,0"}],
    )
    assert "phân_tích_video_của_người_bán" in rich and "giây 6,0" in rich


@pytest.mark.asyncio
async def test_done_analyses_of_the_product_are_loaded_for_the_run(session, conf):
    shop, _ = await seed_shop(session)
    for status, ref in (("done", "video:1"), ("failed", "video:2")):
        session.add(
            ContentAnalysis(
                shop_id=shop.id,
                kind="video",
                content_ref=ref,
                tiktok_product_id=PRODUCT,
                status=status,
                file_name="a.mp4",
                content_type="video/mp4",
                size_bytes=1,
                upload_expires_at=datetime(2026, 10, 10),
                cost_usd=0,
                attempts=1,
                result={
                    "hook": {"label": "Yếu", "reason": "Không có sản phẩm"},
                    "product_line": "Sản phẩm xuất hiện lần đầu ở giây 6,0",
                    "cta": {"line": "Chưa có lời kêu gọi mua"},
                    "pacing": {"line": "2 lần cắt"},
                    "issues": [{"code": "no_cta", "text": "Chưa có lời kêu gọi"}],
                },
            )
        )
    await session.flush()
    loaded = await context.load_summaries(session, shop.id, PRODUCT, "video")
    assert len(loaded) == 1 and loaded[0]["mở_đầu"] == "Yếu — Không có sản phẩm"
    assert await context.load_summaries(session, shop.id, PRODUCT, "live") == []


# -- migration -----------------------------------------------------------------------------


def test_migration_082_chains_after_081_is_tenant_direct_and_the_cleanup_stays_last():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    root = Path(__file__).resolve().parents[2] / "backend/src/juli_backend/database/migrations"
    text = (root / "versions/082_content_analysis.py").read_text(encoding="utf-8")
    assert 'revision: str = "082_content_analysis"' in text
    assert 'down_revision: str | None = "081_order_cost_data"' in text
    assert len("082_content_analysis") <= 32
    deferred = (root / "deferred/074_users_placeholder_phone_cleanup.py").read_text("utf-8")
    # P16 083 and P17 084 chain after 082; the cleanup follows the head (084).
    assert 'down_revision: str | None = "084_onboarding_speed"' in deferred
    assert TABLE_CLASSIFICATION_MAP[("public", "content_analyses")] == "tenant_direct"
    for column in ContentAnalysis.__table__.columns:
        assert f'"{column.name}"' in text, column.name
    assert "ENABLE ROW LEVEL SECURITY" in text and "app_current_shop_id()" in text


# -- RLS (real Postgres, as the runtime role) -----------------------------------------------


def _seed_shop_with_analysis(engine, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    from sqlalchemy import text

    now = datetime.now(UTC).replace(tzinfo=None)
    user_id, shop_id, analysis_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, "
                "created_at, updated_at) VALUES (:id, :u, :n, :t, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "u": str(user_id),
                "n": label,
                "t": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.content_analyses (id, shop_id, kind, status, file_name, "
                "content_type, size_bytes, upload_expires_at) VALUES "
                "(:id, :s, 'video', 'done', 'a.mp4', 'video/mp4', 1, :now)"
            ),
            {"id": str(analysis_id), "s": str(shop_id), "now": now},
        )
    return shop_id, analysis_id


@pytest.mark.asyncio
async def test_content_analyses_are_isolated_per_shop_under_rls():
    from sqlalchemy import select as sa_select
    from sqlalchemy.exc import DBAPIError

    from juli_backend.database.tenant_context import with_shop_scope
    from tests.support.postgres import (
        juli_app_async_sessionmaker,
        owner_sync_engine,
        postgres_reachable,
    )

    if not postgres_reachable():
        pytest.skip("DATABASE_URL does not point at a Postgres database")
    with owner_sync_engine() as engine:
        shop_a, analysis_a = _seed_shop_with_analysis(engine, "rls-a")
        shop_b, analysis_b = _seed_shop_with_analysis(engine, "rls-b")

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            async with with_shop_scope(session, shop_a):
                ids = set((await session.execute(sa_select(ContentAnalysis.id))).scalars())
                assert analysis_a in ids and analysis_b not in ids
                listed = await uploads.list_for(session, shop_b)
                assert listed == []
        async with factory() as session:
            with pytest.raises(DBAPIError):
                async with with_shop_scope(session, shop_a):
                    session.add(
                        ContentAnalysis(
                            shop_id=shop_b,
                            kind="video",
                            status="done",
                            file_name="x.mp4",
                            content_type="video/mp4",
                            size_bytes=1,
                            upload_expires_at=datetime(2026, 10, 10),
                            cost_usd=0,
                            attempts=0,
                        )
                    )
                    await session.flush()


@pytest.mark.asyncio
async def test_an_upload_from_a_content_run_takes_the_runs_product(session, conf):
    from tests.support.lever_flows import seed_run

    shop, product = await seed_shop(session)
    run = await seed_run(session, shop, product)
    row = await uploads.create_upload(
        session,
        shop_id=shop.id,
        user_id=None,
        kind="video",
        content_ref=None,
        tiktok_product_id=None,
        workflow_run_id=run.id,
        file_name="a.mp4",
        content_type="video/mp4",
        size_bytes=10,
        conf=conf,
    )
    assert row.tiktok_product_id == product.tiktok_product_id and row.workflow_run_id == run.id
    other, _ = await seed_shop(session, "b")
    with pytest.raises(uploads.UploadRefused) as err:
        await uploads.create_upload(
            session,
            shop_id=other.id,
            user_id=None,
            kind="video",
            content_ref=None,
            tiktok_product_id=None,
            workflow_run_id=run.id,
            file_name="a.mp4",
            content_type="video/mp4",
            size_bytes=10,
            conf=conf,
        )
    assert err.value.status == 404
