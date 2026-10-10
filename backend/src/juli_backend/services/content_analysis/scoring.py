"""The ONE scoring call over derived signals, and the seller-facing result (fast track P15).

D24 principle: rules and arithmetic produce every number; the model only
writes words. So:

- **Numbers come from the signals** (``Signals``): the product's first second
  on screen (vision timeline), cuts per 10 s (cut detection), the CTA's second
  (the transcript segment / on-screen line the model points at, by index).
- **The model** (``gpt-5.4-nano``, structured output, ``SCORING_SCHEMA``) reads
  ONLY those derived signals -- transcript lines, on-screen text, cut times, the
  product-on-screen timeline, the seller's tone and banned words -- never the
  video, never a frame. It returns the hook verdict + reason, which line is the
  CTA (if any), issues and suggestions in the seller's tone.
- **Checks after the call**: a suggestion that uses a banned claim or one of
  the seller's banned words is dropped; rule-based issues (product late, no
  CTA, pacing, a banned claim *in the seller's own video*) are always added,
  whatever the model said.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from juli_backend.services.agent.llm.blocks import FinalResponse, TextBlock, Usage
from juli_backend.services.agent.llm.config import LLMConfig, estimate_cost_usd
from juli_backend.services.content_analysis.config import LIVE, VIDEO
from juli_backend.services.content_cards.guardrails import ContentRules, check_banned

logger = logging.getLogger(__name__)

PROMPT_VERSION = "p15-content-analysis-v1"
HOOK_S = 3.0
LIVE_HOOK_S = 30.0
PRODUCT_BY_S = 3.0
#: Pacing band for a short selling video (cuts per 10 s).
SLOW_PACING = 1.0
FAST_PACING = 6.0
MAX_ISSUES = 6
MAX_SUGGESTIONS = 5
MAX_TEXT = 300
MAX_SEGMENTS_IN_PROMPT = 120
MAX_SCREEN_LINES = 60

#: Claims a seller's own video must not make (legal / platform), checked on the
#: transcript and the on-screen text. The script voice rules of P14
#: ("các bạn ơi", …) are NOT applied to the seller's own words.
CLAIM_PATTERNS: tuple[str, ...] = (
    "cam kết 100",
    "hiệu quả 100",
    "100 % hiệu quả",
    "tốt nhất thị trường",
    "số 1 việt nam",
    "rẻ nhất",
    "duy nhất trên thị trường",
    "chữa khỏi",
    "trị dứt điểm",
    "khỏi hẳn",
    "thần kỳ",
    "thần dược",
)

ISSUE_CODES = (
    "hook_weak",
    "product_late",
    "no_cta",
    "cta_late",
    "slow_pacing",
    "fast_pacing",
    "no_speech",
    "no_text_on_screen",
    "banned_claim",
    "off_tone",
    "other",
)

SCORING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hook": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["strong", "ok", "weak"]},
                "reason": {"type": "string"},
            },
            "required": ["verdict", "reason"],
            "additionalProperties": False,
        },
        "cta": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["speech", "screen", "none"]},
                "index": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["source", "index", "text"],
            "additionalProperties": False,
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "enum": list(ISSUE_CODES)},
                    "text": {"type": "string"},
                },
                "required": ["code", "text"],
                "additionalProperties": False,
            },
        },
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hook", "cta", "issues", "suggestions"],
    "additionalProperties": False,
}

_SYSTEM = """\
Bạn là người biên tập video bán hàng cho NGƯỜI BÁN trên TikTok Shop Việt Nam.
Bạn KHÔNG xem video. Bạn chỉ có các tín hiệu đã trích xuất: lời thoại (có thời điểm), chữ trên
màn hình (có thời điểm), các lần cắt cảnh, và các khoảng sản phẩm xuất hiện trên màn hình.
Nhận xét dựa trên đúng các tín hiệu đó. Không tự đặt con số mới: mọi con số (giây, số lần cắt)
đã có trong DỮ LIỆU và hệ thống tự hiển thị chúng.

Trả về JSON theo schema:
- "hook": đánh giá {mở_đầu} ("strong" | "ok" | "weak") và một câu lý do ngắn.
- "cta": lời kêu gọi mua (bấm giỏ hàng, đặt hàng, chốt đơn...). "source" = "speech" nếu ở
  lời thoại, "screen" nếu ở chữ trên màn hình, "none" nếu không có; "index" = số thứ tự "i"
  của dòng đó trong DỮ LIỆU (-1 nếu không có); "text" = trích nguyên câu (rỗng nếu không có).
- "issues": tối đa 5 vấn đề quan trọng nhất, mỗi vấn đề một câu ngắn, cụ thể, dùng mã phù hợp.
- "suggestions": tối đa 5 gợi ý sửa, mỗi gợi ý một câu hành động, viết bằng giọng văn của người
  bán (xem "giọng_văn"), không dùng từ trong "từ_cấm", không hứa hẹn doanh số hay lượt xem,
  không dùng lời quảng cáo tuyệt đối (cam kết 100 %, tốt nhất, số 1, rẻ nhất, chữa khỏi).
Viết tiếng Việt, ngắn gọn."""


@dataclass
class Signals:
    """Everything the scoring sees (derived; never the media)."""

    kind: str
    analysed_s: float
    segments: list[dict[str, Any]] = field(default_factory=list)  # {start, end, text}
    screen: list[dict[str, Any]] = field(default_factory=list)  # {t, text}
    cuts: list[dict[str, Any]] = field(default_factory=list)  # {t, kind}
    product_spans: list[list[float]] = field(default_factory=list)
    product_first_s: float | None = None
    product_checked: bool = False
    windows: list[dict[str, Any]] = field(default_factory=list)  # LIVE
    product_name: str | None = None
    brand: str | None = None

    def hook_end(self) -> float:
        if self.kind == LIVE and self.windows:
            return float(self.windows[0]["mention_s"]) + LIVE_HOOK_S
        return HOOK_S

    def hook_start(self) -> float:
        if self.kind == LIVE and self.windows:
            return float(self.windows[0]["mention_s"])
        return 0.0


def screen_lines(frames: Sequence[Any]) -> list[dict[str, Any]]:
    """On-screen text per keyframe → one line per change (consecutive repeats merged)."""
    out: list[dict[str, Any]] = []
    last = None
    for frame in frames:
        text = (getattr(frame, "text", "") or "").strip()
        if text and text != last:
            out.append({"t": float(frame.t), "text": text[:MAX_TEXT]})
        last = text or None
    return out


def product_spans(frames: Sequence[Any], step_s: float) -> tuple[list[list[float]], float | None]:
    spans: list[list[float]] = []
    first: float | None = None
    for frame in frames:
        if frame.product_visible:
            t = float(frame.t)
            first = t if first is None else min(first, t)
            if spans and t - spans[-1][1] <= step_s + 0.01:
                spans[-1][1] = round(t + step_s, 2)
            else:
                spans.append([round(t, 2), round(t + step_s, 2)])
    return spans, first


def pacing(signals: Signals) -> float | None:
    if signals.analysed_s <= 0:
        return None
    return round(len(signals.cuts) * 10.0 / signals.analysed_s, 1)


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def user_prompt(signals: Signals, rules: ContentRules) -> str:
    segments = signals.segments[:MAX_SEGMENTS_IN_PROMPT]
    data: dict[str, Any] = {
        "loại": "video ngắn"
        if signals.kind == VIDEO
        else "LIVE (chỉ các đoạn quanh lúc nói về sản phẩm)",
        "sản_phẩm": {"tên": signals.product_name, "thương_hiệu": signals.brand},
        "mở_đầu_tính_từ_s": signals.hook_start(),
        "mở_đầu_đến_s": signals.hook_end(),
        "lời_thoại": [
            {"i": i, "từ_s": s["start"], "đến_s": s["end"], "câu": _clip(s["text"], 200)}
            for i, s in enumerate(segments)
        ],
        "chữ_trên_màn_hình": [
            {"i": i, "t_s": line["t"], "chữ": _clip(line["text"], 150)}
            for i, line in enumerate(signals.screen[:MAX_SCREEN_LINES])
        ],
        "cắt_cảnh": {
            "số_lần": len(signals.cuts),
            "mỗi_10_giây": pacing(signals),
            "thời_điểm_s": [c["t"] for c in signals.cuts[:80]],
        },
        "sản_phẩm_trên_màn_hình": {
            "đã_kiểm_tra": signals.product_checked,
            "lần_đầu_s": signals.product_first_s,
            "các_khoảng_s": signals.product_spans[:30],
        },
        "thời_lượng_đã_phân_tích_s": round(signals.analysed_s, 1),
        "quy_tắc_người_bán": {
            "giọng_văn": rules.tone or "chưa đặt (thân thiện, rõ ràng)",
            "từ_cấm": list(rules.banned_terms),
        },
    }
    if signals.kind == LIVE:
        data["các_đoạn_live"] = signals.windows
    return "DỮ LIỆU (chỉ dùng những gì có ở đây):\n" + json.dumps(data, ensure_ascii=False)


@dataclass
class ScoreOutcome:
    model: str
    usage: Usage
    cost_usd: float
    raw: dict[str, Any] | None
    error: str | None = None


class Scorer(Protocol):
    model: str

    async def score(self, signals: Signals, rules: ContentRules) -> ScoreOutcome: ...


def _turn_text(turn: Any) -> str:
    return "".join(
        b.content if isinstance(b, FinalResponse) else b.text
        for b in turn.blocks
        if isinstance(b, FinalResponse | TextBlock)
    )


class OpenAIScorer:
    def __init__(self, model: str, *, adapter: Any | None = None) -> None:
        self.model = model
        if adapter is None:
            from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter

            adapter = OpenAIResponsesAdapter()
        self._adapter = adapter

    async def score(self, signals: Signals, rules: ContentRules) -> ScoreOutcome:
        from juli_backend.services.agent.llm.openai_adapter import (
            JsonSchemaFormat,
            LLMProviderError,
        )
        from juli_backend.services.content_analysis.openai_media import ProviderError

        config = LLMConfig(
            model=self.model,
            max_output_tokens=1_500,
            temperature=0.2,
            request_timeout_seconds=90.0,
        )
        try:
            turn = await self._adapter.complete(
                messages=[{"role": "user", "content": user_prompt(signals, rules)}],
                system=_SYSTEM,
                tools=[],
                config=config,
                response_format=JsonSchemaFormat(name="content_analysis", schema=SCORING_SCHEMA),
            )
        except LLMProviderError as exc:
            raise ProviderError(str(exc)[:200]) from exc
        cost = round(estimate_cost_usd(self.model, turn.usage), 6)
        try:
            raw = json.loads(_turn_text(turn) or "")
        except ValueError:
            return ScoreOutcome(self.model, turn.usage, cost, None, error="schema")
        if not isinstance(raw, dict):
            return ScoreOutcome(self.model, turn.usage, cost, None, error="schema")
        return ScoreOutcome(self.model, turn.usage, cost, raw)


# -- result ------------------------------------------------------------------------------

HOOK_VERDICT_VI = {"strong": "Mạnh", "ok": "Tạm được", "weak": "Yếu"}


def _secs(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 60:
        minutes, seconds = divmod(int(round(value)), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    return f"giây {value:.1f}".replace(".", ",")


def _claims(texts: Sequence[str], rules: ContentRules) -> list[str]:
    joined = "\n".join(texts).lower()
    hits = [p for p in CLAIM_PATTERNS if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", joined)]
    hits += [
        t
        for t in rules.banned_terms
        if t.strip() and re.search(rf"(?<!\w){re.escape(t.lower())}(?!\w)", joined)
    ]
    return list(dict.fromkeys(hits))


def _list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    return value if isinstance(value, list) else []


def _cta_time(signals: Signals, cta: Mapping[str, Any]) -> float | None:
    index = cta.get("index")
    if not isinstance(index, int) or index < 0:
        return None
    if cta.get("source") == "speech" and index < len(signals.segments):
        return float(signals.segments[index]["start"])
    if cta.get("source") == "screen" and index < len(signals.screen):
        return float(signals.screen[index]["t"])
    return None


def build_result(
    signals: Signals, rules: ContentRules, raw: Mapping[str, Any] | None
) -> dict[str, Any]:
    """The stored / served result: numbers from the signals, words from the model (checked)."""
    raw = raw or {}
    hook_raw: Mapping[str, Any] = raw["hook"] if isinstance(raw.get("hook"), Mapping) else {}
    verdict_raw = str(hook_raw.get("verdict") or "")
    verdict = verdict_raw if verdict_raw in HOOK_VERDICT_VI else None
    cta_raw: Mapping[str, Any] = raw["cta"] if isinstance(raw.get("cta"), Mapping) else {}
    cta_present = cta_raw.get("source") in ("speech", "screen")
    cta_at = _cta_time(signals, cta_raw) if cta_present else None
    if cta_present and cta_at is None:
        cta_present = False  # pointed at a line that does not exist: not trusted
    rate = pacing(signals)

    issues: list[dict[str, str]] = []

    def add(code: str, text: str) -> None:
        if all(i["code"] != code for i in issues):
            issues.append({"code": code, "text": _clip(text)})

    # Rule-based issues first: they hold whatever the model says.
    hook_lo, hook_hi = signals.hook_start(), signals.hook_end()
    if signals.product_checked:
        if signals.product_first_s is None:
            add("product_late", "Không thấy sản phẩm rõ trên màn hình trong phần đã phân tích.")
        elif signals.product_first_s - hook_lo > PRODUCT_BY_S:
            add(
                "product_late",
                f"Sản phẩm xuất hiện lần đầu ở {_secs(signals.product_first_s)}, "
                f"muộn hơn {PRODUCT_BY_S:g} giây đầu.",
            )
    if not cta_present:
        add("no_cta", "Chưa có lời kêu gọi bấm giỏ hàng / đặt hàng.")
    if signals.kind == VIDEO and rate is not None:
        if rate < SLOW_PACING and signals.analysed_s >= 15:
            add("slow_pacing", "Nhịp cắt chậm: ít hơn 1 lần cắt mỗi 10 giây.")
        elif rate > FAST_PACING:
            add("fast_pacing", "Nhịp cắt rất nhanh: hơn 6 lần cắt mỗi 10 giây.")
    if not signals.segments:
        add("no_speech", "Không nghe thấy lời thoại trong phần đã phân tích.")
    claims = _claims(
        [s["text"] for s in signals.segments] + [line["text"] for line in signals.screen], rules
    )
    if claims:
        add("banned_claim", "Video có từ không nên dùng: " + ", ".join(claims[:5]) + ".")
    for item in _list(raw, "issues"):
        if isinstance(item, Mapping) and str(item.get("code")) in ISSUE_CODES:
            text = str(item.get("text") or "").strip()
            if text and check_banned([text], rules).ok:
                add(str(item["code"]), text)
    suggestions: list[str] = []
    dropped = 0
    for item in _list(raw, "suggestions"):
        text = _clip(str(item or ""))
        if not text:
            continue
        if check_banned([text], rules).ok:
            if text not in suggestions:
                suggestions.append(text)
        else:
            dropped += 1

    first = signals.product_first_s
    return {
        "kind": signals.kind,
        "analysed_s": round(signals.analysed_s, 1),
        "hook": {
            "verdict": verdict,
            "label": HOOK_VERDICT_VI.get(verdict or "", "Chưa đánh giá"),
            "from_s": hook_lo,
            "to_s": hook_hi,
            "reason": _clip(str(hook_raw.get("reason") or "")) or None,
        },
        "product_first_s": first,
        "product_line": (
            f"Sản phẩm xuất hiện lần đầu ở {_secs(first)}"
            if first is not None
            else (
                "Không thấy sản phẩm rõ trên màn hình"
                if signals.product_checked
                else "Chưa kiểm tra (không có thông tin sản phẩm)"
            )
        ),
        "cta": {
            "present": cta_present,
            "at_s": cta_at,
            "text": _clip(str(cta_raw.get("text") or "")) if cta_present else None,
            "line": (
                f"Có lời kêu gọi mua ở {_secs(cta_at)}"
                if cta_present
                else "Chưa có lời kêu gọi mua"
            ),
        },
        "pacing": {
            "cuts": len(signals.cuts),
            "cuts_per_10s": rate,
            "line": (
                f"{len(signals.cuts)} lần cắt · {str(rate).replace('.', ',')} lần / 10 giây"
                if rate is not None
                else "—"
            ),
        },
        "issues": issues[:MAX_ISSUES],
        "suggestions": suggestions[:MAX_SUGGESTIONS],
        "suggestions_dropped": dropped,
        "windows": signals.windows,
        "prompt_version": PROMPT_VERSION,
    }


__all__ = [
    "CLAIM_PATTERNS",
    "ISSUE_CODES",
    "PROMPT_VERSION",
    "SCORING_SCHEMA",
    "OpenAIScorer",
    "ScoreOutcome",
    "Scorer",
    "Signals",
    "build_result",
    "pacing",
    "product_spans",
    "screen_lines",
    "user_prompt",
]
