"""Seller-facing copy rules for incremental impact readings — ADR-077
decision 4 (#1043).

**The rules (ADR-077 decision 4, verbatim):** every number hedged "ước
tính"; never causal language; an inline method disclaimer ("so với các sản
phẩm tương tự trong shop"); negative impact rendered as honestly as
positive. This module renders one sentence per ``TierOutcome``
(:mod:`juli_backend.services.impact.confidence`), not a raw label/value
dump — every string here is prose a seller reads directly, never
"Độ tin cậy: cao" (that colon-suffixed shape is itself a banned pattern,
``packages/contracts/seller-copy-banned-patterns.json`` id ``do_tin_cay``;
this module also never says "Độ tin cậy" at all, using "Mức tin cậy"
instead, to stay unambiguously clear of it).

**Hedging is structural, not incidental.** Every branch that renders a
number opens with "Ước tính" — the hedge is not appended as an
afterthought, it is the sentence's own subject, so it cannot be dropped by
a future edit that only touches the number-formatting tail.

**No causal language.** None of the templates below use a causal
connective ("do", "vì", "nhờ", "khiến", "gây ra", "dẫn đến", "nguyên
nhân") to explain *why* a number moved — every sentence states what was
*measured* relative to the estimate, never what *caused* it. This is a
narrower, ADR-077-specific concern than
``packages/contracts/seller-copy-banned-patterns.json`` (that shared list
does not cover causal language at all); the corresponding test in
``tests/unit/test_impact_copy.py`` keeps its own small causal-marker guard
for exactly this reason, distinct from — and in addition to — the shared
banned-pattern and dictionary-alias checks it also runs.

**Two disclaimers, not one — honesty about which method actually ran.**
The full control path really did compare the target product against
correlated sibling products, so it gets the ADR's literal disclaimer
(:data:`METHOD_DISCLAIMER_FULL_PATH`). The fallback path
(``control_pool.py``'s plain pre/post, triggered by too few eligible
siblings or too-low mean correlation) never built a sibling comparison at
all — claiming "so với các sản phẩm tương tự trong shop" on a fallback
reading would itself be a false claim about method, which is exactly what
ADR-077 decision 4 asks this module not to do. The fallback path instead
gets :data:`METHOD_DISCLAIMER_FALLBACK`, describing what fallback actually
computed: the product's own prior trend.

**Below-floor is a designed state, not an error message.** ``Chưa đủ dữ
liệu để ước tính`` (:data:`BELOW_FLOOR_MESSAGE`) is deliberately the same
calm, first-class register as every other outcome here — it does not read
as a failure.

**Negative impact rendered as honestly as positive.** The tiered-reading
template is a single code path for both signs: the only difference between
a positive and a negative render is the direction word ("tăng thêm" vs
"giảm") and the (always non-negative, via ``abs()``) magnitude — hedge,
disclaimer, and tier phrasing are identical either way. There is no
separate "bad news" branch that could be quietly softened or omitted.

**Number formatting is out of scope.** This module renders a plain-language
sentence structure with a ``Decimal`` magnitude formatted with thousands
separators — full currency/locale formatting (₫ symbols, unit suffixes per
metric) is a presentation-layer concern for whatever surface (#1044 or
later) consumes ``RenderedReadingCopy.text``, not this module's job, the
same scope boundary ``compute.py`` keeps around currency formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.impact.confidence import ConfidenceResult, TierOutcome
from juli_backend.services.impact.metric_map import (
    CONVERSION_RATE,
    CTR,
    GMV,
    GMV_PER_ORDER,
    IMPRESSIONS,
    ITEMS_SOLD,
    SKU_ORDERS,
    MetricSpec,
)

#: The designed "not enough data" state (ADR-077 decision 4) — a first-class
#: outcome, not an error. Kept as a module-level constant so every caller
#: checking for this exact state reads the same string, never a re-typed copy.
BELOW_FLOOR_MESSAGE = "Chưa đủ dữ liệu để ước tính"

#: The ADR's literal inline method disclaimer for a full-control-path
#: reading (real correlated-sibling comparison actually ran).
METHOD_DISCLAIMER_FULL_PATH = "so với các sản phẩm tương tự trong shop"

#: The honest disclaimer for a fallback-path reading (plain pre/post — no
#: sibling comparison ran; see the module docstring).
METHOD_DISCLAIMER_FALLBACK = "so với xu hướng trước đó của chính sản phẩm này"

_METRIC_LABELS_VI: dict[str, str] = {
    GMV.key: "doanh thu",
    SKU_ORDERS.key: "số đơn hàng",
    ITEMS_SOLD.key: "số sản phẩm bán ra",
    GMV_PER_ORDER.key: "giá trị đơn hàng trung bình",
    IMPRESSIONS.key: "lượt hiển thị",
    CTR.key: "tỷ lệ nhấp",
    CONVERSION_RATE.key: "tỷ lệ chuyển đổi",
}

_TIER_LABELS_VI: dict[str, str] = {
    "cao": "cao",
    "trung_binh": "trung bình",
    "thap": "thấp",
}


def metric_label_vi(metric: MetricSpec) -> str:
    """The seller-facing Vietnamese label for one metric.

    These labels are this module's own concern (impact-reading prose), kept
    local rather than added to ``dictionary.md`` because this module's
    write path does not include that file (issue #1043 hard constraint) —
    flagged in the PR body as a follow-up for whoever next touches
    ``dictionary.md`` in-scope.
    """
    try:
        return _METRIC_LABELS_VI[metric.key]
    except KeyError:
        raise KeyError(f"no Vietnamese label configured for metric {metric.key!r}") from None


def _format_number(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    return f"{quantized:,}"


@dataclass(frozen=True, slots=True)
class RenderedReadingCopy:
    """One rendered seller-facing sentence, tagged with the metric and
    outcome it was rendered for — plain data, no further formatting."""

    metric: str
    tier: TierOutcome
    text: str


def render_below_floor(metric: MetricSpec) -> RenderedReadingCopy:
    label = metric_label_vi(metric)
    text = f"{BELOW_FLOOR_MESSAGE} tác động {label}."
    return RenderedReadingCopy(metric=metric.key, tier="below_floor", text=text)


def render_suppressed(metric: MetricSpec) -> RenderedReadingCopy:
    label = metric_label_vi(metric)
    text = (
        f"Chưa thể ước tính tác động {label} cho lần chạy này — dữ liệu chưa đầy đủ để tính toán."
    )
    return RenderedReadingCopy(metric=metric.key, tier="suppressed", text=text)


def render_confounded(metric: MetricSpec) -> RenderedReadingCopy:
    label = metric_label_vi(metric)
    text = (
        f"Chưa thể ước tính tác động {label} cho lần chạy này — "
        "có một thay đổi khác của Juli trong cùng khoảng thời gian theo dõi."
    )
    return RenderedReadingCopy(metric=metric.key, tier="confounded", text=text)


def render_tiered_reading(
    metric: MetricSpec,
    tier: TierOutcome,
    incremental: Decimal,
    used_fallback: bool,
) -> RenderedReadingCopy:
    """Render a ``cao``/``trung_binh``/``thap`` reading — the single
    template both signs of ``incremental`` go through (see the module
    docstring's honesty note on negative impact).

    Raises ``ValueError`` if ``tier`` is not one of the three real tiers —
    the non-tier outcomes (``below_floor``/``suppressed``/``confounded``)
    have their own dedicated renderers above and never reach this one
    through :func:`render_reading`.
    """
    if tier not in ("cao", "trung_binh", "thap"):
        raise ValueError(f"render_tiered_reading requires a real tier, got {tier!r}")

    label = metric_label_vi(metric)
    direction = "tăng thêm" if incremental >= 0 else "giảm"
    magnitude = _format_number(abs(incremental))
    disclaimer = METHOD_DISCLAIMER_FALLBACK if used_fallback else METHOD_DISCLAIMER_FULL_PATH
    tier_label = _TIER_LABELS_VI[tier]

    text = (
        f"Ước tính {label} {direction} khoảng {magnitude} {disclaimer}. "
        f"Mức tin cậy của ước tính này ở mức {tier_label}."
    )
    return RenderedReadingCopy(metric=metric.key, tier=tier, text=text)


def render_reading(
    metric: MetricSpec,
    confidence: ConfidenceResult,
    incremental: Decimal | None,
) -> RenderedReadingCopy:
    """Dispatch a :class:`~juli_backend.services.impact.confidence.
    ConfidenceResult` to the right renderer above — the one call a future
    caller (#1044) needs after running ``compute_confidence``.
    """
    if confidence.tier == "confounded":
        return render_confounded(metric)
    if confidence.tier == "below_floor":
        return render_below_floor(metric)
    if confidence.tier == "suppressed":
        return render_suppressed(metric)
    if incremental is None:
        # assign_confidence never produces a real tier without a defined
        # incremental (it would have returned "suppressed" instead) — a
        # caller passing a mismatched pair is a caller bug worth failing
        # loudly on, not silently rendering a blank number.
        raise ValueError(
            f"render_reading got tier {confidence.tier!r} with incremental=None; "
            "a real tier always has a defined incremental"
        )
    return render_tiered_reading(metric, confidence.tier, incremental, confidence.used_fallback)
