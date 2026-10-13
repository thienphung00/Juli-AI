"""The metric-first trigger (D39.1, N1A; fast track P30). Pure.

D29.2 opened a card only when a product's GMV fell beyond its own band, so a
product whose CTOR fell 20 % while its impressions rose 25 % kept GMV flat and
was never proposed -- Fujiwa's best sellers got no card. D39.1 opens a
candidate when ANY funnel metric (Lượt hiển thị, CTR, CTOR, AOV) falls beyond
its own band, on its channel (D32), even when GMV holds:

1. **Window and channel.** Per metric, the D29.1 adaptive window
   (:func:`.volatility.select_window`, ``min_events`` kept) read on the channel
   the metric's levers act on (:func:`.kpi_channel.kpi_window`: Lượt hiển thị /
   CTR on Thẻ sản phẩm when that channel has enough data, else all channels;
   CTOR and AOV are all-channel, D32.2). A low-data metric is never a trigger.
2. **Beyond its band.** The window mean against the same-length window just
   before it (the product's own earlier level, at least half its days
   observed), a fall larger than 1 × the combined band of both window means
   (D31.7 ``√(a² + b²)``, the same 1 × the GMV gate used, so a "likely" fall is
   caught; certainty shows through "Độ tin cậy").
3. **What it costs.** The D29.2 decomposition (:func:`.volatility.decompose`)
   of that window, on that channel: ``c = ln(metric now / metric before)``. Had
   the metric held, GMV would be ``GMV now × e^(−c)`` with the other factors as
   they are, so the metric alone costs ``GMV now × (e^(−c) − 1)`` per day --
   the channel's GMV when the channel carries a sales breakdown, else the
   product's. Candidates are ranked on this cost; a product keeps the ONE
   metric that costs most (D29.4).
4. **GMV held?** Read product-wide, as D29.2 did (D32.3): GMV did not fall
   beyond its band -> "held", and the metric whose rise held it is the largest
   positive term of the product-wide decomposition. The card's copy says so.

The "growth" branch for products with no metric drop (a simulated winner,
D38 / D39.1) lives outside the backend; :func:`growth_candidates` is its seam.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from juli_backend.services.change_strength import LIKELY_MULT, combined_band
from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.kpi_channel import channel_gmv_per_day, kpi_window
from juli_backend.services.optimize_product.tunables import DiagTunables
from juli_backend.services.optimize_product.volatility import (
    METRICS,
    STATUS_CANDIDATE,
    STATUS_NO_DROP,
    STATUS_NO_METRIC,
    Assessment,
    decompose,
    window_band_pct,
    window_counts,
)

#: The lever whose channel a metric is read on when looking for a fall: Lượt
#: hiển thị moves through the title, CTR through the cover image (both Thẻ sản
#: phẩm); CTOR / AOV are all-channel whatever the lever (no per-channel orders).
DETECT_LEVER: dict[str, str] = {
    "impressions": "title",
    "ctr": "cover_image",
    "ctor": "description",
    "aov": "buy_more_save_more",
}

#: Skip reason (the plan's ``skips``) when no metric fell beyond its band.
STATUS_NO_METRIC_DROP = "no_metric_drop"

#: GMV read product-wide: held (no fall beyond its band), fell, or unknown.
GMV_HELD = "held"
GMV_FELL = "fell"
GMV_UNKNOWN = "unknown"


@dataclass(frozen=True)
class MetricDrop:
    """One funnel metric that fell beyond its own band (D39.1)."""

    metric: str
    channel: str
    window_days: int
    current: float
    earlier: float
    #: The fall, in % of the earlier level (positive = fell).
    drop_pct: float
    #: Both windows' window-mean bands combined (± %).
    band_pct: float
    #: ``ln(now / before)`` of the metric on its channel (D29.2 decomposition).
    contribution: float
    #: The GMV/day the cost is priced on (the channel's, else the product's).
    gmv_per_day: float
    #: What the fall alone costs, VND per day: ``gmv × (e^(−c) − 1)``.
    gmv_cost_per_day: float

    def to_json(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "channel": self.channel,
            "window_days": self.window_days,
            "current": self.current,
            "earlier": self.earlier,
            "drop_pct": round(self.drop_pct, 2),
            "band_pct": round(self.band_pct, 2),
            "contribution": round(self.contribution, 4),
            "gmv_per_day": round(self.gmv_per_day, 2),
            "gmv_cost_per_day": round(self.gmv_cost_per_day, 2),
        }


@dataclass(frozen=True)
class MetricTrigger:
    """Every metric of one product that fell beyond its band, costliest first."""

    drops: tuple[MetricDrop, ...]
    #: ``held`` / ``fell`` / ``unknown`` (product-wide GMV, D29.2's band).
    gmv: str = GMV_UNKNOWN
    #: Product-wide GMV change over the GMV window, % (negative = fell).
    gmv_change_pct: float | None = None
    #: The metric whose rise held GMV (largest positive product-wide term).
    held_by: str | None = None
    #: Product-wide ``ln`` terms over the GMV window (D29.2), for Ops.
    contributions: dict[str, float] | None = None

    @property
    def target(self) -> MetricDrop | None:
        return self.drops[0] if self.drops else None

    def to_json(self) -> dict[str, Any]:
        return {
            "trigger": "metric_first",
            "drops": [d.to_json() for d in self.drops],
            "gmv": self.gmv,
            "gmv_change_pct": (
                None if self.gmv_change_pct is None else round(self.gmv_change_pct, 2)
            ),
            "held_by": self.held_by,
            "contributions": {k: round(v, 4) for k, v in (self.contributions or {}).items()},
        }


def metric_drop(
    rows: Sequence[ProductDay],
    *,
    as_of: date,
    metric: str,
    tunables: DiagTunables,
    assessment: Assessment,
) -> MetricDrop | None:
    """``metric``'s fall beyond its band on its channel, else ``None`` (steps 1–3)."""
    total = assessment.metrics.get(metric)
    kw = kpi_window(
        rows,
        as_of=as_of,
        metric=metric,
        lever=DETECT_LEVER[metric],
        tunables=tunables,
        total=total,
    )
    window = kw.window
    now_value, earlier = window.value, window.earlier
    if window.low_data or now_value is None or now_value <= 0 or earlier is None or earlier <= 0:
        return None
    length = window.window_days
    now = window_counts(kw.rows, as_of, length)
    before = window_counts(kw.rows, as_of, length, offset=length)
    if before.days_with_data * 2 < length:
        return None
    combined = combined_band(window.band_pct, window_band_pct(before.daily_values(metric)))
    if combined is None:
        return None
    drop_pct = (earlier - now_value) / earlier * 100
    if drop_pct <= LIKELY_MULT * combined:
        return None
    contribution = decompose(now, before).get(metric)
    if contribution is None or contribution >= 0:
        return None
    gmv: float | None = None
    if kw.per_channel:
        gmv = channel_gmv_per_day(rows, kw.channel, as_of, length)
    if gmv is None:
        gmv = window_counts(rows, as_of, length).value("gmv") or 0.0
    return MetricDrop(
        metric=metric,
        channel=kw.channel,
        window_days=length,
        current=now_value,
        earlier=earlier,
        drop_pct=drop_pct,
        band_pct=combined,
        contribution=contribution,
        gmv_per_day=gmv,
        gmv_cost_per_day=gmv * (math.exp(-contribution) - 1),
    )


def metric_trigger(
    rows: Sequence[ProductDay],
    *,
    as_of: date,
    tunables: DiagTunables,
    assessment: Assessment,
) -> MetricTrigger:
    """D39.1 for one product: its falling metrics, costliest first, and its GMV."""
    drops = [
        drop
        for metric in METRICS
        if (
            drop := metric_drop(
                rows, as_of=as_of, metric=metric, tunables=tunables, assessment=assessment
            )
        )
        is not None
    ]
    drops.sort(key=lambda d: (-d.gmv_cost_per_day, d.contribution, d.metric))
    if assessment.status == STATUS_NO_DROP:
        gmv = GMV_HELD
    elif assessment.status in (STATUS_CANDIDATE, STATUS_NO_METRIC):
        gmv = GMV_FELL
    else:
        gmv = GMV_UNKNOWN
    change: float | None = None
    if assessment.gmv_current is not None and assessment.gmv_earlier:
        change = (assessment.gmv_current / assessment.gmv_earlier - 1) * 100
    contributions: dict[str, float] | None = None
    held_by: str | None = None
    if gmv != GMV_UNKNOWN and assessment.window_days:
        length = assessment.window_days
        contributions = decompose(
            window_counts(rows, as_of, length), window_counts(rows, as_of, length, offset=length)
        )
        target = drops[0].metric if drops else None
        rising = [(v, m) for m, v in contributions.items() if v > 0 and m != target]
        if gmv == GMV_HELD and rising:
            held_by = max(rising)[1]
    return MetricTrigger(
        drops=tuple(drops),
        gmv=gmv,
        gmv_change_pct=change,
        held_by=held_by,
        contributions=contributions,
    )


def growth_candidates(*_args: Any, **_kwargs: Any) -> list[Any]:
    """The "growth" branch for products with NO metric drop -- not built here.

    TODO(D39.1): a product whose funnel metrics all hold gets a card only from a
    simulated winner (D38 champion beating the original beyond the A/A noise):
    "Độ tin cậy" Thấp, target = current + 1 × band. The simulator lives outside
    the backend (the local pilot folder, D36.6 / D38), so there is nothing to
    read yet; this seam returns no proposals until its results are stored.
    """
    return []


__all__ = [
    "DETECT_LEVER",
    "GMV_FELL",
    "GMV_HELD",
    "GMV_UNKNOWN",
    "STATUS_NO_METRIC_DROP",
    "MetricDrop",
    "MetricTrigger",
    "growth_candidates",
    "metric_drop",
    "metric_trigger",
]
