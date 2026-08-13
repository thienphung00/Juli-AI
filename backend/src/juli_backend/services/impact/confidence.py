"""Confidence tiers, per-metric volume floors, and suppression — ADR-077
decision 4 (#1043).

**Scope.** This module answers the question #1041/#1042 explicitly left
open: given a computed ``MetricReading`` (compute.py's numbers) and a
``ControlPoolResult`` (control_pool.py's control-cohort selection), what
confidence tier — ``cao`` / ``trung_binh`` / ``thap`` — does the seller-
facing surface show, and when is a reading not shown as a number at all
(``below_floor``, ``suppressed``, ``confounded``)? Neither upstream module
answers this; ``reading.py``'s ``MetricReading.status`` only ever
distinguishes ``"ok"`` from ``"confounded"`` by its own docstring's design.

**The six outcomes.** ``TierOutcome`` has six values, not three: the three
real tiers (``cao``/``trung_binh``/``thap``) plus three distinct *reasons* a
tier cannot be assigned at all — ``below_floor`` (not enough pre-period
traffic to trust any estimate — the designed "Chưa đủ dữ liệu để ước tính"
state, a first-class outcome, not an error), ``suppressed`` (there *was*
enough traffic, but the numbers needed to place a tier — the incremental
value itself, or the noise band — could not be computed; a data-
completeness gap distinct from a traffic-volume gap) and ``confounded``
(mirrored straight from ``reading.MetricReading.status`` — a second Juli run
touched the window, so the reading is not trustworthy at all, at any tier).
Precedence, checked in this order, is: ``confounded`` first (nothing
overrides it), then ``below_floor`` (a volume gate applied before any signal
is even examined), then ``suppressed`` (signal/band missing), then the tier
boundaries below. A fallback-path reading (``ControlPoolResult.used_fallback``)
that clears all three gates is capped at ``thap`` unconditionally — it can
never reach ``cao`` or even ``trung_binh``, both of which require the full
control path by ADR-077's own definition.

**Volume floors — config, not inline literals (acceptance criterion).**
``VOLUME_FLOORS`` is keyed per :class:`MetricFamily`, not per individual
metric and not re-declared at each call site: ≥1 order/day for the
revenue/orders family, ≥50 impressions/day for impressions/CTR, ≥20
visitors/day for conversion. ``volume_floor_for`` is the single resolution
path every caller (this module's own ``assign_confidence``, and any future
caller) must go through.

**Which raw column is "volume"?** The floor is a *count* of underlying
events (orders, impressions, visitors), not the reading metric's own value
— comparing "≥1 order/day" against a GMV reading's own currency value would
be nonsensical (nearly every product clears "$1/day"). So the volume
indicator per family is a fixed raw column, independent of which specific
metric in that family is being read:

- revenue/orders (``gmv``, ``sku_orders``, ``items_sold``, ``gmv_per_order``)
  → ``sku_orders`` (the literal order count all four ultimately derive from
  or correlate with).
- impressions/CTR (``impressions``, ``ctr``) → ``impressions``.
- conversion (``conversion_rate``) → ``visitors`` — a real, distinct column
  on ``AnalyticsPerformanceInterval``/``RawDailyRecord``, exactly matching
  ADR-077 decision 4's literal "≥20 visitors/day" wording. This is *not*
  the same column impressions/CTR reads: visitors and impressions differ by
  roughly the click-through ratio (impressions are typically one to two
  orders of magnitude larger), so substituting impressions here would apply
  a far weaker gate than the ADR specifies — a reading could clear "≥20"
  on impressions while its real visitor volume sits nowhere near 20,
  skipping the "Chưa đủ dữ liệu để ước tính" state the floor exists to
  produce. (An earlier revision of this module made exactly that
  substitution, believing no visitors column existed; it does, at
  ``AnalyticsPerformanceInterval.visitors`` — see
  ``TestConversionFloorUsesVisitorsNotImpressions`` in
  ``tests/unit/test_impact_confidence.py`` for the regression guard.)

**Interface contract with #1042 (control_pool.py).** ``control_pool.py``'s
own ``volume_floor`` parameter (ADR-077 decision 3) is a *different*
concern — it gates whether a *candidate sibling product* qualifies to join
the control cohort at all, checked there against the mean of the candidate's
own pre-period series **for the metric being evaluated** (i.e. for a GMV
reading, a candidate's own daily GMV, not its order count). That is a
narrower, already-committed contract this module does not rewrite. The two
floors happen to share the same *config values* (this module is their single
source), but are applied to different series by design — this module's own
below-floor gate is always evaluated against the volume indicator above, on
the *target* product, independent of how control_pool.py separately screens
candidates.

**Noise band — the heuristic z-analogue, explicitly not a credible
interval.** ADR-077 decision 4: "the stddev of the daily treated-vs-expected
gap during the pre-period — how wrong the counterfactual already was when
nothing had happened." Implemented in :func:`compute_noise_band` as: scale
the control series into the target's own level using
``scale = mean(target_pre) / mean(control_pre)`` (a pre-period-only ratio —
never the post-window ``growth`` from ``compute.py``, which would leak
post-window information into a pre-period noise estimate); for each
pre-period day with both a target and a scaled-control value, gap(d) =
target(d) − control(d)×scale; the noise band is the sample standard
deviation (``statistics.stdev``, stdlib, ``Decimal``-safe — no
``numpy``/``scipy``) of those daily gaps. On the fallback path, the control
series is control_pool.py's constant-1 series, so ``scale`` degenerates to
``mean(target_pre)`` itself and the band collapses to the target's own
pre-period standard deviation around its own mean — the correct degenerate
case for "no real control to compare against."

**This is declared plainly a heuristic z-analogue, not a credible
interval.** The tier thresholds (2×/1× the noise band) are a
production-analytics rule of thumb (the Google Merchant Center pattern named
in ADR-077), not a statistically derived confidence level from a fitted
model. ``tfcausalimpact`` (Bayesian structural time-series, real credible
intervals) is the named graduation path once this measurement surface earns
that investment. Nothing in this module's copy, naming, or docstrings should
be read as claiming more statistical rigour than "a rule-of-thumb multiple
of an empirically observed pre-period noise level."

**Purity.** Like the rest of this package, every function here is a pure,
deterministic function of its arguments — no wall-clock reads, no I/O.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from juli_backend.services.impact.control_pool import ControlPoolResult, FallbackReason
from juli_backend.services.impact.metric_map import (
    CONVERSION_RATE,
    CTR,
    GMV,
    GMV_PER_ORDER,
    IMPRESSIONS,
    ITEMS_SOLD,
    SKU_ORDERS,
    MetricSpec,
    RawDailyRecord,
)
from juli_backend.services.impact.reading import MetricReading, ReadingStatus
from juli_backend.services.impact.windows import date_range, mean_over_window, pre_window

DailySeries = Mapping[date, RawDailyRecord]

TierOutcome = Literal["cao", "trung_binh", "thap", "below_floor", "suppressed", "confounded"]


class MetricFamily(str, Enum):
    """The three metric families ADR-077 decision 4 assigns volume floors
    to. Deliberately coarser than :class:`~juli_backend.services.impact.
    metric_map.MetricSpec` — several metrics share one family and one
    floor."""

    REVENUE_ORDERS = "revenue_orders"
    IMPRESSIONS_CTR = "impressions_ctr"
    CONVERSION = "conversion"


#: Every metric this package knows how to read, mapped to its floor family.
#: Deliberately exhaustive over `metric_map.ALL_METRICS` (see the parametrized
#: contract test) — a metric with no family entry is a config bug, not a
#: silently-permissive default.
METRIC_FAMILY: dict[str, MetricFamily] = {
    GMV.key: MetricFamily.REVENUE_ORDERS,
    SKU_ORDERS.key: MetricFamily.REVENUE_ORDERS,
    ITEMS_SOLD.key: MetricFamily.REVENUE_ORDERS,
    GMV_PER_ORDER.key: MetricFamily.REVENUE_ORDERS,
    IMPRESSIONS.key: MetricFamily.IMPRESSIONS_CTR,
    CTR.key: MetricFamily.IMPRESSIONS_CTR,
    CONVERSION_RATE.key: MetricFamily.CONVERSION,
}

#: The floor config itself — ADR-077 decision 4's three numbers, and their
#: *only* declaration. Every use site reads through :func:`volume_floor_for`;
#: none re-declares ``1``/``50``/``20`` as a literal.
VOLUME_FLOORS: dict[MetricFamily, Decimal] = {
    MetricFamily.REVENUE_ORDERS: Decimal(1),  # >= 1 order/day
    MetricFamily.IMPRESSIONS_CTR: Decimal(50),  # >= 50 impressions/day
    MetricFamily.CONVERSION: Decimal(20),  # >= 20 visitors/day
}

#: The raw column read as each family's volume signal — see the module
#: docstring for why this is not always the reading metric's own column.
_VOLUME_INDICATOR: dict[MetricFamily, Callable[[RawDailyRecord], Decimal | None]] = {
    MetricFamily.REVENUE_ORDERS: lambda day: day.sku_orders,
    MetricFamily.IMPRESSIONS_CTR: lambda day: day.impressions,
    MetricFamily.CONVERSION: lambda day: day.visitors,
}

#: Tier boundary multipliers (ADR-077 decision 4) — the only declaration;
#: `assign_confidence` reads these rather than repeating `3`/`2`/`1` inline.
FLOOR_MULTIPLIER_CAO: Decimal = Decimal(3)
BAND_MULTIPLIER_CAO: Decimal = Decimal(2)
BAND_MULTIPLIER_TRUNG_BINH: Decimal = Decimal(1)


def metric_family_of(metric: MetricSpec) -> MetricFamily:
    """Resolve a metric's volume-floor family.

    Raises ``KeyError`` naming the unresolved metric — an unmapped metric is
    a configuration bug worth failing loudly on, matching
    ``metric_map.resolve_metric``'s own failure style.
    """
    try:
        return METRIC_FAMILY[metric.key]
    except KeyError:
        raise KeyError(f"no volume-floor family configured for metric {metric.key!r}") from None


def volume_indicator_for(metric: MetricSpec) -> Callable[[RawDailyRecord], Decimal | None]:
    """The count series a metric's volume floor is calibrated against.

    ADR-077 decision 4's floors are counts — orders, impressions, visitors —
    so anything screening candidates on that floor must read this series, not
    the metric itself. Exposed because `control_pool` needs it and cannot
    import this module (it would cycle: this module imports ControlPoolResult).
    """
    return _VOLUME_INDICATOR[metric_family_of(metric)]


def volume_floor_for(metric: MetricSpec) -> Decimal:
    """The single resolution path from a metric to its configured volume
    floor — never re-declare the numeric threshold at a call site."""
    return VOLUME_FLOORS[metric_family_of(metric)]


def pre_period_volume(daily: DailySeries, metric: MetricSpec, t: date) -> Decimal | None:
    """Mean daily volume-indicator value over the pre-period window
    ``[T-14, T-1]`` (day T excluded, mirroring every other window read in
    this package) — the quantity compared against :func:`volume_floor_for`.

    ``None`` (not zero) when no pre-period day has a value for the
    indicator column — "insufficient data" and "below floor" are kept as
    the same designed outcome here (both fail the ``volume >= floor``
    check in :func:`assign_confidence`), since a caller cannot trust an
    estimate either way.
    """
    indicator = _VOLUME_INDICATOR[metric_family_of(metric)]
    series = {day: indicator(record) for day, record in daily.items()}
    start, end = pre_window(t)
    return mean_over_window(series, start, end, exclude=t)


def _extract_series(daily: DailySeries, metric: MetricSpec) -> dict[date, Decimal | None]:
    return {day: metric.extractor(record) for day, record in daily.items()}


def compute_noise_band(
    target_daily: DailySeries,
    control_daily: DailySeries,
    metric: MetricSpec,
    t: date,
) -> Decimal | None:
    """The pre-period stddev of the daily treated-vs-expected gap — see the
    module docstring for the full derivation. ``None`` when fewer than two
    paired pre-period days survive (``statistics.stdev`` requires at least
    two data points) or the control series is silent (mean pre-period
    control value of zero, which cannot scale) in its own pre-period —
    both real, expected inputs, never an exception.
    """
    start, end = pre_window(t)

    target_series = _extract_series(target_daily, metric)
    control_series = _extract_series(control_daily, metric)

    target_pre_mean = mean_over_window(target_series, start, end, exclude=t)
    control_pre_mean = mean_over_window(control_series, start, end, exclude=t)
    if target_pre_mean is None or control_pre_mean is None or control_pre_mean == 0:
        return None
    scale = target_pre_mean / control_pre_mean

    gaps: list[Decimal] = []
    for day in date_range(start, end):
        if day == t:
            continue
        target_value = target_series.get(day)
        control_value = control_series.get(day)
        if target_value is not None and control_value is not None:
            gaps.append(target_value - control_value * scale)

    if len(gaps) < 2:
        return None
    try:
        return statistics.stdev(gaps)
    except statistics.StatisticsError:
        return None


def assign_confidence(
    *,
    metric: MetricSpec,
    status: ReadingStatus,
    incremental: Decimal | None,
    volume: Decimal | None,
    noise_band: Decimal | None,
    used_fallback: bool,
) -> TierOutcome:
    """Assign one of the six outcomes (ADR-077 decision 4), in precedence
    order: ``confounded`` > ``below_floor`` > ``suppressed`` > the tier
    boundaries. See the module docstring for why each precedence step
    exists and why fallback caps at ``thap`` unconditionally.
    """
    if status == "confounded":
        return "confounded"

    floor = volume_floor_for(metric)
    if volume is None or volume < floor:
        return "below_floor"

    if incremental is None or noise_band is None:
        return "suppressed"

    if used_fallback:
        return "thap"

    magnitude = abs(incremental)
    if volume >= floor * FLOOR_MULTIPLIER_CAO and magnitude > noise_band * BAND_MULTIPLIER_CAO:
        return "cao"
    if magnitude > noise_band * BAND_MULTIPLIER_TRUNG_BINH:
        return "trung_binh"
    return "thap"


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    """One metric's confidence assignment, plus the intermediate values a
    future caller (#1044) needs for both persistence
    (``impact_readings.confidence``) and audit (why this tier)."""

    metric: str
    tier: TierOutcome
    volume: Decimal | None
    noise_band: Decimal | None
    used_fallback: bool
    fallback_reason: FallbackReason | None


def compute_confidence(
    metric: MetricSpec,
    target_daily: DailySeries,
    control_pool_result: ControlPoolResult,
    reading: MetricReading,
) -> ConfidenceResult:
    """Compose :func:`pre_period_volume`, :func:`compute_noise_band`, and
    :func:`assign_confidence` from a #1042 ``ControlPoolResult`` and a #1041
    ``MetricReading`` — the full pipeline a future caller runs after
    ``select_control_pool`` and ``compute_metric_reading`` for one metric,
    with no separate ``t``/``kind`` arguments to keep in sync: both are read
    off ``control_pool_result``, which ``reading`` was necessarily computed
    against (the caller's own responsibility to keep consistent, same as
    every other cross-object invariant in this package).
    """
    t = control_pool_result.t
    volume = pre_period_volume(target_daily, metric, t)
    noise_band = compute_noise_band(target_daily, control_pool_result.control_daily, metric, t)
    tier = assign_confidence(
        metric=metric,
        status=reading.status,
        incremental=reading.incremental,
        volume=volume,
        noise_band=noise_band,
        used_fallback=control_pool_result.used_fallback,
    )
    return ConfidenceResult(
        metric=metric.key,
        tier=tier,
        volume=volume,
        noise_band=noise_band,
        used_fallback=control_pool_result.used_fallback,
        fallback_reason=control_pool_result.fallback_reason,
    )
