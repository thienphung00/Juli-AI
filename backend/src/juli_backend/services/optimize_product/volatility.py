"""Volatility-aware diagnosis and KPI for one product (D29). Pure.

Fujiwa's Thẻ sản phẩm moves ±26 % impressions and ±66 % CTOR a day, so a 7–14-day
gap against the shop median is mostly noise. D29 replaces "gap ≥ 20 %" with:

1. **Adaptive window (29.1).** Per metric, the shortest of ``windows`` (14 → 30 →
   60 days) holding ≥ ``min_events`` clicks (CTR) / SKU orders (CTOR, AOV, GMV);
   none → "ít dữ liệu" and that metric is not diagnosed. Hiển thị never is low-data.
2. **GMV first (29.2).** A product is a candidate only when its GMV/day over its
   window fell versus its earlier stable level (the same-length window just before)
   by more than its own window-mean GMV band (of the difference of the two means:
   both windows' bands combined). Then
   ``ln(GMV now / GMV before) = Σ ln(metric now / metric before)`` over Hiển thị/day,
   CTR, CTOR and AOV; the metric with the most negative term (not low-data) is the
   TARGET metric.
3. **Reference (29.3).** The higher of the shop median, the product's own earlier
   level and a category benchmark (a hook; ``None`` until a source exists).
4. **Stable first (29.5)** on the CV of daily impressions, **confidence (29.6)** from
   events and CV, **KPI (29.7)** = reference clamped to
   ``[current + min_mult × band, current + max_mult × band]``; a volatile product
   (CV > ``volatile_cv``) gets the KPI as a range, confidence low, judged at day 14
   only (29.10).

The band of a window MEAN is D28.1's (``services.ops.simulation.mean_band``:
``±Z_80 × stdev(daily) / √n``), reused here, never re-derived. A band below
:data:`MIN_BAND_PCT` is lifted to it: a perfectly flat series (fixtures, a product
selling the same count every day) would otherwise make every target equal the
current value.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from juli_backend.services.ops.simulation import CV_STABLE, mean_band
from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.tunables import DiagTunables

METRICS: tuple[str, ...] = ("impressions", "ctr", "ctor", "aov")
#: The count each metric's reliability rests on (D28.2); None: never low-data.
EVENT_KIND: Mapping[str, str | None] = {
    "impressions": None,
    "ctr": "click",
    "ctor": "order",
    "aov": "order",
    "gmv": "order",
}
#: Lower bound of a window-mean band, in % of the mean (see module docstring).
MIN_BAND_PCT = 1.0

STATUS_CANDIDATE = "candidate"
STATUS_LOW_DATA = "low_data"
STATUS_NO_REFERENCE = "no_reference"
STATUS_NO_DROP = "no_gmv_drop"
STATUS_NO_METRIC = "no_metric_explains"

STABILITY_ORDER: Mapping[str, int] = {"stable": 0, "medium": 1, "volatile": 2, "unknown": 3}

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
#: High confidence needs this many times the data minimum (and stable traffic).
HIGH_CONFIDENCE_EVENTS_MULT = 3


# --------------------------------------------------------------------------- windows


def _days(as_of: date, length: int, offset: int = 0) -> list[date]:
    last = as_of - timedelta(days=offset)
    return [last - timedelta(days=i) for i in range(length - 1, -1, -1)]


@dataclass(frozen=True)
class WindowCounts:
    """Sums over a calendar window plus the daily series the band is built on."""

    days: int
    days_with_data: int
    impressions: float
    clicks: float
    orders: float
    gmv: float
    daily: tuple[tuple[float, float, float, float], ...]  # (impr, clicks, orders, gmv) per day

    def value(self, metric: str) -> float | None:
        if self.days <= 0 or self.days_with_data == 0:
            return None
        if metric == "impressions":
            return self.impressions / self.days
        if metric == "gmv":
            return self.gmv / self.days
        if metric == "ctr":
            return self.clicks / self.impressions if self.impressions > 0 else None
        if metric == "ctor":
            return self.orders / self.clicks if self.clicks > 0 else None
        if metric == "aov":
            return self.gmv / self.orders if self.orders > 0 else None
        raise KeyError(metric)

    def events(self, metric: str) -> int | None:
        kind = EVENT_KIND[metric]
        if kind is None:
            return None
        return round(self.clicks if kind == "click" else self.orders)

    def daily_values(self, metric: str) -> list[float]:
        """One value per day: counts per calendar day (a missing day is 0), ratios
        only on days with a denominator."""
        out: list[float] = []
        for impressions, clicks, orders, gmv in self.daily:
            if metric == "impressions":
                out.append(impressions)
            elif metric == "gmv":
                out.append(gmv)
            elif metric == "ctr" and impressions > 0:
                out.append(clicks / impressions)
            elif metric == "ctor" and clicks > 0:
                out.append(orders / clicks)
            elif metric == "aov" and orders > 0:
                out.append(gmv / orders)
        return out


def window_counts(
    rows: Sequence[ProductDay], as_of: date, length: int, *, offset: int = 0
) -> WindowCounts:
    """The ``length`` days ending ``offset`` days before ``as_of`` (both included)."""
    by_day = {r.day: r for r in rows}
    daily: list[tuple[float, float, float, float]] = []
    present = 0
    for day in _days(as_of, length, offset):
        row = by_day.get(day)
        if row is None:
            daily.append((0.0, 0.0, 0.0, 0.0))
            continue
        present += 1
        daily.append(
            (float(row.impressions), float(row.clicks), float(row.sku_orders), float(row.gmv))
        )
    return WindowCounts(
        days=length,
        days_with_data=present,
        impressions=sum(d[0] for d in daily),
        clicks=sum(d[1] for d in daily),
        orders=sum(d[2] for d in daily),
        gmv=sum(d[3] for d in daily),
        daily=tuple(daily),
    )


def _half_width(values: Iterable[float]) -> float:
    band = mean_band(values)
    return 0.0 if band is None else band.p90 - band.mean


def window_band_pct(values: Iterable[float]) -> float | None:
    """D28.1's window-mean band (% of the mean), lifted to :data:`MIN_BAND_PCT`."""
    band = mean_band(values)
    if band is None or band.mean <= 0:
        return None
    pct = band.band_pct if band.band_pct is not None else 0.0
    return max(pct, MIN_BAND_PCT)


def daily_cv(values: Iterable[float]) -> float | None:
    band = mean_band(values)
    return None if band is None else band.cv


@dataclass(frozen=True)
class MetricWindow:
    """One metric read over its adaptive window (D29.1)."""

    metric: str
    window_days: int
    value: float | None
    band_pct: float | None
    events: int | None
    low_data: bool
    cv: float | None
    #: The same-length window just before: the product's own earlier level.
    earlier: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "window_days": self.window_days,
            "value": self.value,
            "band_pct": self.band_pct,
            "events": self.events,
            "low_data": self.low_data,
            "cv": self.cv,
            "earlier": self.earlier,
        }


def select_window(
    rows: Sequence[ProductDay], as_of: date, metric: str, tunables: DiagTunables
) -> MetricWindow:
    """The shortest window with enough events; the longest one, low-data, when none has."""
    windows = sorted(tunables.windows) or [14]
    chosen = windows[-1]
    low_data = EVENT_KIND[metric] is not None
    for length in windows:
        counts = window_counts(rows, as_of, length)
        events = counts.events(metric)
        if events is None or events >= tunables.min_events:
            chosen, low_data = length, False
            break
    counts = window_counts(rows, as_of, chosen)
    earlier_counts = window_counts(rows, as_of, chosen, offset=chosen)
    values = counts.daily_values(metric)
    return MetricWindow(
        metric=metric,
        window_days=chosen,
        value=counts.value(metric),
        band_pct=window_band_pct(values),
        events=counts.events(metric),
        low_data=low_data,
        cv=daily_cv(values),
        earlier=earlier_counts.value(metric) if earlier_counts.days_with_data else None,
    )


# --------------------------------------------------------------------------- KPI


@dataclass(frozen=True)
class Kpi:
    """The card's KPI (D29.7 / 29.10), in the metric's own unit."""

    metric: str
    current: float
    target: float
    target_min: float
    target_max: float
    display: str  # "point" | "range"
    band_pct: float
    window_days: int
    low_data: bool
    #: D29.10: a volatile product is judged at day 14 only.
    day14_only: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "current": self.current,
            "target": self.target,
            "target_min": self.target_min,
            "target_max": self.target_max,
            "display": self.display,
            "band_pct": self.band_pct,
            "window_days": self.window_days,
            "low_data": self.low_data,
            "day14_only": self.day14_only,
        }


def kpi_target(
    *,
    metric: str,
    current: float,
    band_pct: float,
    reference: float,
    window_days: int,
    tunables: DiagTunables,
    volatile: bool,
    low_data: bool = False,
    predicted: tuple[float, float] | None = None,
) -> Kpi:
    """Reference clamped to ``[current + min × band, current + max × band]``.

    ``predicted`` (D30.3, the metric range the Performance Prediction gives) narrows
    those bounds when it overlaps them; it never widens them -- below one band a
    change cannot be measured, above three it over-promises.
    """
    band_abs = current * band_pct / 100
    low = current + tunables.kpi_min_band_mult * band_abs
    high = current + tunables.kpi_max_band_mult * band_abs
    if predicted is not None:
        p_low, p_high = predicted
        n_low, n_high = max(low, p_low), min(high, p_high)
        if n_low <= n_high:
            low, high = n_low, n_high
    target = min(max(reference, low), high)
    return Kpi(
        metric=metric,
        current=current,
        target=target,
        target_min=low,
        target_max=high,
        display="range" if volatile else "point",
        band_pct=band_pct,
        window_days=window_days,
        low_data=low_data,
        day14_only=volatile,
    )


# --------------------------------------------------------------------------- assessment


def stability(cv: float | None, tunables: DiagTunables) -> str:
    if cv is None:
        return "unknown"
    if cv < CV_STABLE:
        return "stable"
    if cv <= tunables.volatile_cv:
        return "medium"
    return "volatile"


def confidence(
    *, events: int | None, cv: float | None, low_data: bool, tunables: DiagTunables
) -> str:
    """D29.6: low when volatile or thin; high when stable and ≥ 3× the minimum."""
    level = stability(cv, tunables)
    if low_data or level in ("volatile", "unknown"):
        return CONFIDENCE_LOW
    if (
        level == "stable"
        and events is not None
        and events >= HIGH_CONFIDENCE_EVENTS_MULT * tunables.min_events
    ):
        return CONFIDENCE_HIGH
    return CONFIDENCE_MEDIUM


def decompose(now: WindowCounts, before: WindowCounts) -> dict[str, float]:
    """``ln(metric now / metric before)`` per factor of GMV = Lượt hiển thị × CTR × CTOR × AOV.

    A factor with no value on either side is left out (it explains nothing).
    """
    out: dict[str, float] = {}
    for metric in METRICS:
        a, b = now.value(metric), before.value(metric)
        if a is None or b is None or a <= 0 or b <= 0:
            continue
        out[metric] = math.log(a / b)
    return out


def pick_target(contributions: Mapping[str, float], low_data: Iterable[str]) -> str | None:
    """The most negative contribution among the metrics that are not low-data."""
    blocked = set(low_data)
    falling = [(v, m) for m, v in contributions.items() if v < 0 and m not in blocked]
    if not falling:
        return None
    return min(falling)[1]


def reference_for(
    metric: str,
    *,
    shop_median: float | None,
    earlier: float | None,
    benchmark: float | None = None,
) -> tuple[float | None, str | None]:
    """D29.3: the higher of shop median, own earlier stable level and category benchmark."""
    options = [
        (value, source)
        for value, source in (
            (shop_median, "shop_median"),
            (earlier, "own_earlier"),
            (benchmark, "category_benchmark"),
        )
        if value is not None and value > 0
    ]
    if not options:
        return None, None
    value, source = max(options, key=lambda item: item[0])
    return value, source


@dataclass(frozen=True)
class Assessment:
    """D29.1–29.6 for one product."""

    product_id: str
    status: str
    window_days: int | None = None
    gmv_current: float | None = None
    gmv_earlier: float | None = None
    gmv_band_abs: float | None = None
    contributions: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, MetricWindow] = field(default_factory=dict)
    target_metric: str | None = None
    impressions_cv: float | None = None
    stability: str = "unknown"
    confidence: str = CONFIDENCE_LOW

    @property
    def candidate(self) -> bool:
        return self.status == STATUS_CANDIDATE

    @property
    def gmv_drop(self) -> float | None:
        if self.gmv_current is None or self.gmv_earlier is None:
            return None
        return self.gmv_earlier - self.gmv_current

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "window_days": self.window_days,
            "gmv_current_per_day": self.gmv_current,
            "gmv_earlier_per_day": self.gmv_earlier,
            "gmv_band_abs": self.gmv_band_abs,
            "contributions": dict(self.contributions),
            "target_metric": self.target_metric,
            "impressions_cv": self.impressions_cv,
            "stability": self.stability,
            "confidence": self.confidence,
            "metrics": {k: v.to_json() for k, v in self.metrics.items()},
        }


def assess_product(
    product_id: str,
    rows: Sequence[ProductDay],
    *,
    as_of: date,
    tunables: DiagTunables,
) -> Assessment:
    """D29.1 + 29.2 + 29.5/29.6 for one product's daily rows."""
    metrics = {m: select_window(rows, as_of, m, tunables) for m in METRICS}
    gmv = select_window(rows, as_of, "gmv", tunables)
    window = gmv.window_days
    now = window_counts(rows, as_of, window)
    before = window_counts(rows, as_of, window, offset=window)
    impressions_cv = daily_cv(now.daily_values("impressions"))
    level = stability(impressions_cv, tunables)
    base: dict[str, Any] = {
        "product_id": product_id,
        "window_days": window,
        "metrics": metrics,
        "impressions_cv": impressions_cv,
        "stability": level,
    }
    if gmv.low_data:
        return Assessment(status=STATUS_LOW_DATA, **base)
    # The earlier stable level needs at least half its days observed.
    if before.days_with_data * 2 < window or before.value("gmv") is None:
        return Assessment(status=STATUS_NO_REFERENCE, **base)
    gmv_now, gmv_before = now.value("gmv") or 0.0, before.value("gmv") or 0.0
    # The fall is a difference of two window means, so its band combines both
    # windows' window-mean bands (√(a² + b²)); one window's band alone would call
    # ~1 in 5 flat products "fallen" on noise.
    # D31.7 note: the same combined band as ``services.change_strength``, but in VND
    # (not %), floored at MIN_BAND_PCT, with a 1 × multiplier: a fall > 1 × combined,
    # i.e. at least "likely". Candidate selection keeps 1 × rather than the 2 × of
    # "clear" on purpose, so a real fall is not missed.
    half = math.hypot(_half_width(now.daily_values("gmv")), _half_width(before.daily_values("gmv")))
    half = max(half, gmv_now * MIN_BAND_PCT / 100)
    base.update(gmv_current=gmv_now, gmv_earlier=gmv_before, gmv_band_abs=half)
    if gmv_before - gmv_now <= half:
        return Assessment(status=STATUS_NO_DROP, **base)
    contributions = decompose(now, before)
    base["contributions"] = contributions
    target = pick_target(contributions, (m for m, w in metrics.items() if w.low_data))
    if target is None:
        return Assessment(status=STATUS_NO_METRIC, **base)
    target_window = metrics[target]
    events = target_window.events if target_window.events is not None else gmv.events
    return Assessment(
        status=STATUS_CANDIDATE,
        target_metric=target,
        confidence=confidence(
            events=events, cv=impressions_cv, low_data=target_window.low_data, tunables=tunables
        ),
        **base,
    )


def guard_bands(
    rows: Sequence[ProductDay],
    *,
    as_of: date,
    tunables: DiagTunables,
    metrics: Iterable[str],
) -> dict[str, float]:
    """D29.9: each metric's default hold threshold (± %) = guard_mult × its window-mean band.

    Keys are this module's metric names plus ``gmv``; a metric with no band is left out.
    """
    out: dict[str, float] = {}
    for metric in metrics:
        window = select_window(rows, as_of, metric, tunables)
        if window.band_pct is not None:
            out[metric] = round(window.band_pct * tunables.guard_band_mult, 2)
    return out


__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "METRICS",
    "MIN_BAND_PCT",
    "STABILITY_ORDER",
    "STATUS_CANDIDATE",
    "STATUS_LOW_DATA",
    "STATUS_NO_DROP",
    "STATUS_NO_METRIC",
    "STATUS_NO_REFERENCE",
    "Assessment",
    "Kpi",
    "MetricWindow",
    "WindowCounts",
    "assess_product",
    "confidence",
    "decompose",
    "guard_bands",
    "kpi_target",
    "pick_target",
    "reference_for",
    "select_window",
    "stability",
    "window_band_pct",
    "window_counts",
]
