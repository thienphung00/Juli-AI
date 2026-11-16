"""F11: one trigger detector for Shopee and TikTok. Pure: no DB, no platform imports.

Three trigger types (owner decision F11, 2026-11-16, ``docs/architecture/forecast-model.md`` 11):

1. **Problem** (TikTok's method, ``optimize_product/volatility.py`` D29.2 / 29.3, on both
   platforms). A product's GMV per day over its adaptive window (shortest of 14 / 30 / 60 days with
   enough orders; none = low data, no trigger) is below its reference by more than its F3 period
   band (:func:`services.forecast.noise.period_band`). The reference is
   ``max(shop median, own earlier level, category benchmark when provided)``. The fall against the
   own earlier level (the same-length window just before) is then split,
   ``ln(GMV now / before) = sum ln(metric now / before)`` over views per day, CTR, CTOR and AOV;
   the most negative term of a metric that is not low-data is the TARGET metric, and the adapter's
   levers for it are the trigger's levers. No negative term: no trigger (nothing explains it).
2. **Opportunity**. The product has no problem, but a lever's forecast P50 (ΔGMV over the card's
   period) is beyond the F3 band of the product's GMV over that period, with a positive Δprofit
   (ΔGMV when the profit is unknown). A band that cannot be measured (fewer than two days of
   history) never blocks an opportunity, as in F5.
3. **Rule**. Stock, listing_hide, voucher_cap and similar platform rules: the adapter supplies them
   and they pass through, outside the forecast.

The platform differences live in a :class:`TriggerAdapter`. :func:`rank` orders the result.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from juli_backend.services.forecast.noise import MIN_PCT, period_band

PROBLEM = "problem"
OPPORTUNITY = "opportunity"
RULE = "rule"

#: The funnel split of GMV = views x CTR x CTOR x AOV, in the order of the decomposition.
METRICS: tuple[str, ...] = ("views", "ctr", "ctor", "aov")
#: F2 / D29.1: the adaptive windows (days) and the data minimum behind a metric.
WINDOWS: tuple[int, ...] = (14, 30, 60)
MIN_EVENTS = 30
#: The count each metric's reliability rests on; None: never low-data (views).
EVENT_KIND: Mapping[str, str | None] = {
    "views": None,
    "ctr": "clicks",
    "ctor": "orders",
    "aov": "orders",
    "gmv": "orders",
}
#: A problem's value is the GMV it would win back over this many days (a month, as the cards'
#: ``money_per_month``), times the profit per GMV when known.
VALUE_DAYS = 30
#: Ranking: a problem is put ahead of an opportunity whose value is at most this share larger
#: (a problem worth 90 % or more of the opportunity's value goes first). Below that the value
#: decides. 10 % is inside the noise of the forecast P50 itself, so the two are "similar".
SIMILAR_VALUE_SHARE = 0.10


@dataclass(frozen=True)
class DayRow:
    """One product day. A day with no row is MISSING (F2), never zero."""

    day: date
    views: float
    clicks: float
    orders: float
    gmv: float


@dataclass(frozen=True)
class ProductSeries:
    product_id: str
    days: tuple[DayRow, ...]


@dataclass(frozen=True)
class Reference:
    """GMV per day the product is compared with besides its own earlier level."""

    shop_median: float | None = None
    benchmark: float | None = None


@dataclass(frozen=True)
class LeverForecast:
    """A lever's forecast over the card's period: ``dgmv_p50`` / ``dprofit_p50`` are totals over
    ``period_days`` (``dprofit_p50`` None = profit unknown); ``gmv_history`` is the product's own
    daily GMV in its F2 window (the F3 band is read from it)."""

    product_id: str
    lever: str
    target_metric: str | None
    dgmv_p50: float | None
    dprofit_p50: float | None
    period_days: int
    gmv_history: Sequence[float | None] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleTrigger:
    """A platform rule the adapter detected; ``urgency`` ranks rule cards among themselves
    (higher first), e.g. the fewer stock days left the larger."""

    rule: str
    product_id: str | None
    urgency: float = 0.0
    value: float = 0.0
    detail: Mapping[str, Any] = field(default_factory=dict)


class TriggerAdapter(Protocol):
    """What a platform supplies. Everything else is shared."""

    def reference(self, product_id: str) -> Reference: ...

    def levers_for(self, metric: str) -> tuple[str, ...]:
        """The levers allowed for a target metric (views / ctr / ctor / aov)."""
        ...

    def profit_per_gmv(self, product_id: str) -> float | None:
        """Profit per VND of GMV; None = profit unknown (values then are ΔGMV)."""
        ...

    def forecasts(self, product_id: str) -> Sequence[LeverForecast]:
        """The levers' forecasts for the product (opportunity candidates)."""
        ...

    def rule_triggers(self) -> Sequence[RuleTrigger]: ...


@dataclass(frozen=True)
class Trigger:
    trigger_type: str
    product_id: str | None
    target_metric: str | None
    #: expected Δprofit (ΔGMV when profit is unknown) of the trigger
    value: float
    value_basis: str  # "profit" | "gmv"
    levers: tuple[str, ...] = ()
    rule: str | None = None
    urgency: float = 0.0
    detail: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- windows


@dataclass(frozen=True)
class _Window:
    days: int
    present: int
    views: float
    clicks: float
    orders: float
    gmv: float
    gmv_daily: tuple[float, ...]

    def value(self, metric: str) -> float | None:
        if self.present <= 0:
            return None
        if metric == "gmv":
            return self.gmv / self.present
        if metric == "views":
            return self.views / self.present
        if metric == "ctr":
            return self.clicks / self.views if self.views > 0 else None
        if metric == "ctor":
            return self.orders / self.clicks if self.clicks > 0 else None
        if metric == "aov":
            return self.gmv / self.orders if self.orders > 0 else None
        raise KeyError(metric)

    def events(self, metric: str) -> float | None:
        kind = EVENT_KIND[metric]
        if kind is None:
            return None
        return self.clicks if kind == "clicks" else self.orders


def _window(rows: Mapping[date, DayRow], as_of: date, length: int, offset: int = 0) -> _Window:
    last = as_of - timedelta(days=offset)
    found = [
        rows[d] for d in (last - timedelta(days=i) for i in range(length - 1, -1, -1)) if d in rows
    ]
    return _Window(
        days=length,
        present=len(found),
        views=sum(r.views for r in found),
        clicks=sum(r.clicks for r in found),
        orders=sum(r.orders for r in found),
        gmv=sum(r.gmv for r in found),
        gmv_daily=tuple(r.gmv for r in found),
    )


def _adaptive_window(
    rows: Mapping[date, DayRow], as_of: date, metric: str, windows: Sequence[int], min_events: int
) -> tuple[int, bool]:
    """The shortest window with enough events (F2). None has: the longest anyway (owner
    2026-11-16, F2 amendment 2: the wide F3 band decides); low-data only with no event at all."""
    ordered = sorted(windows)
    if EVENT_KIND[metric] is None:
        return ordered[0], False
    events: float | None = None
    for length in ordered:
        events = _window(rows, as_of, length).events(metric)
        if events is not None and events >= min_events:
            return length, False
    return ordered[-1], not events


def decompose(now: _Window, before: _Window) -> dict[str, float]:
    """``ln(metric now / metric before)`` per factor; a factor with no value on either side is
    left out (it explains nothing)."""
    out: dict[str, float] = {}
    for metric in METRICS:
        a, b = now.value(metric), before.value(metric)
        if a is None or b is None or a <= 0 or b <= 0:
            continue
        out[metric] = math.log(a / b)
    return out


def pick_target(contributions: Mapping[str, float], low_data: set[str]) -> str | None:
    """The most negative contribution among the metrics that are not low-data."""
    falling = [(v, m) for m, v in contributions.items() if v < 0 and m not in low_data]
    return min(falling)[1] if falling else None


def reference_level(
    shop_median: float | None, earlier: float | None, benchmark: float | None
) -> tuple[float | None, str | None]:
    """max(shop median, own earlier level, category benchmark when it exists)."""
    options = [
        (v, s)
        for v, s in (
            (shop_median, "shop_median"),
            (earlier, "own_earlier"),
            (benchmark, "category_benchmark"),
        )
        if v is not None and v > 0
    ]
    if not options:
        return None, None
    return max(options, key=lambda item: item[0])


# --------------------------------------------------------------------------- problem


def detect_problem(
    series: ProductSeries,
    reference: Reference,
    adapter: TriggerAdapter,
    *,
    as_of: date | None = None,
    windows: Sequence[int] = WINDOWS,
    min_events: int = MIN_EVENTS,
) -> Trigger | None:
    """The product's problem trigger, or None (no drop beyond the band, low data, no reference or
    no metric explains the fall)."""
    rows = {r.day: r for r in series.days}
    if not rows:
        return None
    end = as_of or max(rows)
    length, gmv_low = _adaptive_window(rows, end, "gmv", windows, min_events)
    if gmv_low:
        return None
    now = _window(rows, end, length)
    before = _window(rows, end, length, offset=length)
    now_day = now.value("gmv")
    if now_day is None:
        return None
    # the own earlier level needs at least half its days observed (volatility.py 29.2)
    earlier = before.value("gmv") if before.present * 2 >= length else None
    ref, source = reference_level(reference.shop_median, earlier, reference.benchmark)
    if ref is None:
        return None
    band = period_band(now.gmv_daily, length)
    half = max((band.p90 - band.p10) / 2, now.gmv * MIN_PCT)
    drop_total = (ref - now_day) * length
    if drop_total <= half:
        return None
    if earlier is None:
        return None
    contributions = decompose(now, before)
    low = {m for m in METRICS if _adaptive_window(rows, end, m, windows, min_events)[1]}
    target = pick_target(contributions, low)
    if target is None:
        return None
    margin = adapter.profit_per_gmv(series.product_id)
    lost = (ref - now_day) * VALUE_DAYS
    return Trigger(
        trigger_type=PROBLEM,
        product_id=series.product_id,
        target_metric=target,
        value=lost * margin if margin is not None else lost,
        value_basis="profit" if margin is not None else "gmv",
        levers=tuple(adapter.levers_for(target)),
        detail={
            "window_days": length,
            "gmv_per_day": now_day,
            "reference_per_day": ref,
            "reference_source": source,
            "band_half": half,
            "drop": drop_total,
            "contributions": dict(contributions),
        },
    )


# --------------------------------------------------------------------------- opportunity


def clears_band(forecast: LeverForecast, profit_known: bool) -> bool:
    """F11 (2): the forecast P50 is beyond the F3 band (of the product's GMV over the card's
    period) and the value is positive (Δprofit when known, else ΔGMV)."""
    dgmv = forecast.dgmv_p50
    if dgmv is None or dgmv <= 0:
        return False
    if profit_known and forecast.dprofit_p50 is not None and forecast.dprofit_p50 <= 0:
        return False
    band = period_band(forecast.gmv_history, forecast.period_days)
    if band.band_pct is None:  # not measurable: never blocks (as F5)
        return True
    return dgmv > (band.p90 - band.p10) / 2


def detect_opportunities(
    product_id: str, adapter: TriggerAdapter, profit_known: bool
) -> list[Trigger]:
    out: list[Trigger] = []
    for f in adapter.forecasts(product_id):
        if not clears_band(f, profit_known):
            continue
        use_profit = profit_known and f.dprofit_p50 is not None
        value = f.dprofit_p50 if use_profit else f.dgmv_p50
        out.append(
            Trigger(
                trigger_type=OPPORTUNITY,
                product_id=product_id,
                target_metric=f.target_metric,
                value=float(value or 0.0),
                value_basis="profit" if use_profit else "gmv",
                levers=(f.lever,),
                detail=dict(f.detail),
            )
        )
    return out


# --------------------------------------------------------------------------- entry points


def detect(
    products: Sequence[ProductSeries],
    adapter: TriggerAdapter,
    *,
    as_of: date | None = None,
    windows: Sequence[int] = WINDOWS,
    min_events: int = MIN_EVENTS,
) -> list[Trigger]:
    """All triggers for ``products`` (unranked: problems, opportunities, then rules; call
    :func:`rank`). A product with a problem gets no opportunity triggers."""
    out: list[Trigger] = []
    for series in products:
        problem = detect_problem(
            series,
            adapter.reference(series.product_id),
            adapter,
            as_of=as_of,
            windows=windows,
            min_events=min_events,
        )
        if problem is not None:
            out.append(problem)
            continue
        out.extend(
            detect_opportunities(
                series.product_id, adapter, adapter.profit_per_gmv(series.product_id) is not None
            )
        )
    for r in adapter.rule_triggers():
        out.append(
            Trigger(
                trigger_type=RULE,
                product_id=r.product_id,
                target_metric=None,
                value=r.value,
                value_basis="profit",
                rule=r.rule,
                levers=(r.rule,),
                urgency=r.urgency,
                detail=dict(r.detail),
            )
        )
    return out


def rank(triggers: Sequence[Trigger]) -> list[Trigger]:
    """Rule cards first by their own urgency (a stock-out cannot wait for a forecast), then
    problems and opportunities by expected value, largest first. At a similar value (a problem
    worth at least ``1 - SIMILAR_VALUE_SHARE`` of the opportunity ahead of it) the problem goes
    first. Ties keep the input order."""
    rules = sorted((t for t in triggers if t.trigger_type == RULE), key=lambda t: -t.urgency)
    rest = sorted((t for t in triggers if t.trigger_type != RULE), key=lambda t: -t.value)
    moved = True
    while moved:
        moved = False
        for i in range(len(rest) - 1):
            a, b = rest[i], rest[i + 1]
            if (
                a.trigger_type == OPPORTUNITY
                and b.trigger_type == PROBLEM
                and b.value >= a.value * (1 - SIMILAR_VALUE_SHARE)
            ):
                rest[i], rest[i + 1] = b, a
                moved = True
    return [*rules, *rest]


def shop_median(values: Sequence[float]) -> float | None:
    """A helper for adapters: the median of the products' GMV per day."""
    clean = [v for v in values if v > 0]
    return statistics.median(clean) if clean else None


__all__ = [
    "MIN_EVENTS",
    "OPPORTUNITY",
    "PROBLEM",
    "RULE",
    "SIMILAR_VALUE_SHARE",
    "WINDOWS",
    "DayRow",
    "LeverForecast",
    "ProductSeries",
    "Reference",
    "RuleTrigger",
    "Trigger",
    "TriggerAdapter",
    "clears_band",
    "decompose",
    "detect",
    "detect_problem",
    "pick_target",
    "rank",
    "reference_level",
    "shop_median",
]
