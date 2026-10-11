"""The OpenAI calls of the content analysis (fast track P15): transcription and vision.

- **Transcription** -- ``POST /v1/audio/transcriptions`` (multipart, plain
  ``httpx`` like the Responses adapter; no ``openai`` package). Vietnamese,
  the glossary (product name, brand, SEO words) as ``prompt``. ``whisper-1``
  returns segment and word timestamps (``verbose_json``); the
  ``gpt-4o*-transcribe`` models return text only, so the caller sends them
  short slices and uses the slice's own time. Cost = audio minutes × the
  per-minute price in ``config.ASR_USD_PER_MINUTE``.
- **Vision** -- keyframes (384 px JPEG, ``detail: low``) plus the product's
  own listing images go to ``gpt-5.4-nano`` through the Responses adapter with
  a JSON schema: per frame, the on-screen text and whether the product is
  visible. One call per batch of frames; near-identical consecutive frames are
  not sent twice (their reading is copied). Cost from the returned tokens.

Only keyframes and audio slices leave the server -- never the uploaded file.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np
from PIL import Image

from juli_backend.core.config import require_env
from juli_backend.services.agent.llm.blocks import FinalResponse, TextBlock, Usage
from juli_backend.services.agent.llm.config import LLMConfig, estimate_cost_usd
from juli_backend.services.content_analysis.config import asr_usd_per_minute

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com"
_TRANSCRIPTIONS_PATH = "/v1/audio/transcriptions"
#: whisper-1 reads at most ~224 prompt tokens; the glossary is kept well under.
MAX_GLOSSARY_CHARS = 600
VISION_BATCH = 8
#: Mean absolute luma difference (0-255, on a 32×18 thumbnail) under which a
#: keyframe counts as the same picture as the last one sent.
SAME_FRAME_DIFF = 3.0


class ProviderError(RuntimeError):
    """An OpenAI call failed (HTTP error, timeout, unreadable body). Retryable."""


def supports_timestamps(model: str) -> bool:
    return model.startswith("whisper")


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    seconds: float = 0.0
    cost_usd: float = 0.0


class Transcriber(Protocol):
    model: str

    async def transcribe(
        self, audio: Path, *, prompt: str, offset_s: float, duration_s: float
    ) -> Transcript: ...


class OpenAITranscriber:
    def __init__(
        self,
        model: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 300.0,
    ) -> None:
        self.model = model
        self._transport = transport
        self._base_url = base_url
        self._timeout = timeout_s

    async def transcribe(
        self, audio: Path, *, prompt: str, offset_s: float, duration_s: float
    ) -> Transcript:
        api_key = require_env("OPENAI_API_KEY")
        timestamps = supports_timestamps(self.model)
        data: dict[str, Any] = {
            "model": self.model,
            "language": "vi",
            "prompt": prompt[:MAX_GLOSSARY_CHARS],
            "response_format": "verbose_json" if timestamps else "json",
        }
        if timestamps:
            data["timestamp_granularities[]"] = ["segment", "word"]
        try:
            async with httpx.AsyncClient(
                transport=self._transport, base_url=self._base_url, timeout=self._timeout
            ) as client:
                response = await client.post(
                    _TRANSCRIPTIONS_PATH,
                    data=data,
                    files={"file": (audio.name, audio.read_bytes(), "audio/mp4")},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"transcription returned HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"transcription failed: {type(exc).__name__}") from exc
        return parse_transcription(body, offset_s=offset_s, duration_s=duration_s, model=self.model)


def parse_transcription(body: Any, *, offset_s: float, duration_s: float, model: str) -> Transcript:
    """The API's answer → segments / words in the upload's own time."""
    body = body if isinstance(body, dict) else {}
    segments: list[Segment] = []
    for raw in body.get("segments") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if text:
            segments.append(
                Segment(
                    start=round(offset_s + float(raw.get("start") or 0.0), 2),
                    end=round(offset_s + float(raw.get("end") or 0.0), 2),
                    text=text,
                )
            )
    words = [
        Word(
            start=round(offset_s + float(w.get("start") or 0.0), 2),
            end=round(offset_s + float(w.get("end") or 0.0), 2),
            text=str(w.get("word") or "").strip(),
        )
        for w in body.get("words") or []
        if isinstance(w, dict) and str(w.get("word") or "").strip()
    ]
    if not segments:
        text = str(body.get("text") or "").strip()
        if text:
            segments.append(
                Segment(start=round(offset_s, 2), end=round(offset_s + duration_s, 2), text=text)
            )
    return Transcript(
        segments=segments,
        words=words,
        seconds=duration_s,
        cost_usd=round(duration_s / 60.0 * asr_usd_per_minute(model), 6),
    )


# -- vision --------------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameRead:
    t: float
    text: str
    product_visible: bool | None
    #: True when the picture repeated the previous one and its reading was copied.
    reused: bool = False


@dataclass
class VisionResult:
    frames: list[FrameRead] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(0, 0))
    cost_usd: float = 0.0
    calls: int = 0


class VisionReader(Protocol):
    model: str

    async def read(
        self,
        frames: Sequence[tuple[float, Path]],
        *,
        product_name: str | None,
        product_images: Sequence[str],
    ) -> VisionResult: ...


VISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                    "product_visible": {"type": "boolean"},
                },
                "required": ["index", "text", "product_visible"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["frames"],
    "additionalProperties": False,
}

_VISION_SYSTEM = """\
Bạn đọc các khung hình của một video bán hàng trên TikTok Shop Việt Nam.
Với MỖI khung hình (theo số thứ tự), trả về:
- "text": toàn bộ chữ đang hiện trên màn hình (phụ đề, chữ chèn, giá, nhãn), giữ nguyên
  chính tả; chuỗi rỗng nếu không có chữ. Không mô tả hình ảnh.
- "product_visible": true nếu SẢN PHẨM ĐANG BÁN (xem ảnh sản phẩm tham chiếu và tên sản
  phẩm) xuất hiện rõ trong khung hình (cầm trên tay, đặt trên bàn, cận cảnh bao bì);
  false nếu không.
Chỉ trả về JSON theo schema."""


def _data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _thumb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("L").resize((32, 18)), dtype=np.float32)


def distinct_frames(frames: Sequence[tuple[float, Path]]) -> list[int]:
    """Indexes of the frames worth sending: each differs from the last one kept."""
    kept: list[int] = []
    last: np.ndarray | None = None
    for i, (_t, path) in enumerate(frames):
        thumb = _thumb(path)
        if last is None or float(np.abs(thumb - last).mean()) >= SAME_FRAME_DIFF:
            kept.append(i)
            last = thumb
    return kept


def _turn_text(turn: Any) -> str:
    return "".join(
        b.content if isinstance(b, FinalResponse) else b.text
        for b in turn.blocks
        if isinstance(b, FinalResponse | TextBlock)
    )


class OpenAIVision:
    """Keyframes → on-screen text + product visible, via the Responses adapter."""

    def __init__(self, model: str, *, adapter: Any | None = None) -> None:
        self.model = model
        if adapter is None:
            from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter

            adapter = OpenAIResponsesAdapter()
        self._adapter = adapter

    async def _batch(
        self,
        batch: Sequence[tuple[int, Path]],
        *,
        product_name: str | None,
        product_images: Sequence[str],
    ) -> tuple[dict[int, tuple[str, bool]], Usage]:
        from juli_backend.services.agent.llm.openai_adapter import (
            JsonSchemaFormat,
            LLMProviderError,
        )

        parts: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": f"Sản phẩm đang bán: {product_name or 'không rõ tên'}. "
                + (
                    "Ảnh sản phẩm tham chiếu:"
                    if product_images
                    else "Không có ảnh tham chiếu: nhận biết theo tên sản phẩm."
                ),
            }
        ]
        parts += [
            {"type": "input_image", "image_url": url, "detail": "low"} for url in product_images[:2]
        ]
        for index, path in batch:
            parts.append({"type": "input_text", "text": f"Khung hình số {index}:"})
            parts.append({"type": "input_image", "image_url": _data_url(path), "detail": "low"})
        config = LLMConfig(
            model=self.model,
            max_output_tokens=1_500,
            temperature=0.0,
            request_timeout_seconds=90.0,
        )
        try:
            turn = await self._adapter.complete(
                messages=[{"role": "user", "content": parts}],
                system=_VISION_SYSTEM,
                tools=[],
                config=config,
                response_format=JsonSchemaFormat(name="keyframe_reads", schema=VISION_SCHEMA),
            )
        except LLMProviderError as exc:
            raise ProviderError(str(exc)[:200]) from exc
        try:
            data = json.loads(_turn_text(turn) or "{}")
        except ValueError:
            data = {}
        reads: dict[int, tuple[str, bool]] = {}
        items = data.get("frames") if isinstance(data, dict) else None
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                reads[int(item["index"])] = (
                    str(item.get("text") or "").strip()[:300],
                    bool(item.get("product_visible")),
                )
        return reads, turn.usage

    async def read(
        self,
        frames: Sequence[tuple[float, Path]],
        *,
        product_name: str | None,
        product_images: Sequence[str],
    ) -> VisionResult:
        result = VisionResult()
        if not frames:
            return result
        kept = distinct_frames(frames)
        reads: dict[int, tuple[str, bool]] = {}
        input_tokens = output_tokens = 0
        for start in range(0, len(kept), VISION_BATCH):
            batch = [(i, frames[i][1]) for i in kept[start : start + VISION_BATCH]]
            got, usage = await self._batch(
                batch, product_name=product_name, product_images=product_images
            )
            reads.update(got)
            input_tokens += usage.input_tokens
            output_tokens += usage.output_tokens
            result.calls += 1
        last: tuple[str, bool] | None = None
        kept_set = set(kept)
        for i, (t, _path) in enumerate(frames):
            if i in kept_set:
                last = reads.get(i)
                text, visible = last if last else ("", None)
                result.frames.append(FrameRead(t=t, text=text, product_visible=visible))
            else:
                text, visible = last if last else ("", None)
                result.frames.append(
                    FrameRead(t=t, text=text, product_visible=visible, reused=True)
                )
        result.usage = Usage(input_tokens, output_tokens)
        result.cost_usd = round(estimate_cost_usd(self.model, result.usage), 6)
        return result


__all__ = [
    "FrameRead",
    "OpenAITranscriber",
    "OpenAIVision",
    "ProviderError",
    "Segment",
    "Transcriber",
    "Transcript",
    "VISION_SCHEMA",
    "VisionReader",
    "VisionResult",
    "Word",
    "distinct_frames",
    "parse_transcription",
    "supports_timestamps",
]
