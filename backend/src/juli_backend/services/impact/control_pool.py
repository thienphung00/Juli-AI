"""Control-pool selection — K-nearest-correlated siblings (ADR-077 decision 3,
#1042).

**What this module does.** Given a target product's pre-period daily series
and a pool of same-shop sibling candidates, select the top **K=5** (minimum
**3**) candidates by Pearson correlation of the *target metric's* pre-period
series, equal-weighted into one synthetic control daily series shaped exactly
like the ``control_daily_by_metric`` values ``reading.py`` (#1041) already
consumes (``Mapping[date, RawDailyRecord]``) — correlation beats category as
the selection criterion because it measures shared shock exposure, which is
what the ratio-form DiD in ``compute.py`` needs from its control cohort.
Below the quality bar (mean correlation < 0.2), or with fewer than 3 eligible
candidates, this module falls back to a synthetic **plain pre/post** control
series instead — a constant series that forces ``compute_growth``'s ratio to
exactly ``1``, so ``expected == pre`` and ``incremental == post - pre`` with
no control adjustment at all. The confidence-tier cap that fallback implies
(Thấp) is #1043's concern (ADR-077 decision 4) — this module only produces
the ``used_fallback``/``fallback_reason`` signal for #1043 to act on.

**Interface contract with #1041.** ``reading.compute_mutation_readings`` /
``compute_run_readings`` accept ``control_daily_by_metric: Mapping[str,
DailySeries]`` — one full ``RawDailyRecord`` daily series *per metric key*,
because (per that module's own docstring) the correlated siblings that
qualify as a control for ``gmv`` need not be the same siblings that qualify
for ``ctr``. That is exactly what ``select_control_pool`` below produces: it
is called once per metric (the metric being read), and
``ControlPoolResult.control_daily`` is the value a caller assembling
``control_daily_by_metric`` stores at ``[metric.key]``. No adapter or shape
change was needed — see the PR body for the full reasoning trail.

**I/O boundary.** Like ``reading.py``'s ``confounded: bool``, the three
eligibility inputs that require a database read are caller-supplied on
``ControlCandidate`` rather than queried here:

- ``touched`` — whether any Juli run touched this candidate product inside
  the pre *or* post window (a single bool; either window disqualifies, so
  the caller ORs them before constructing the candidate).
- ``first_active_date`` — the candidate's first day of recorded activity,
  used to enforce "active < 14 days" relative to ``t``.
- the volume-floor *value* itself — ADR-077 decision 4's per-metric floor
  config is #1043's territory; this module enforces whichever floor
  (``Decimal``) the caller passes in, against the mean of the candidate's own
  pre-period series for the metric being evaluated.

**Determinism under ties.** Two candidates with equal Pearson correlation are
ordered by ``product_id`` ascending as an explicit, total tiebreak, applied
*before* truncating to the top K. ``sorted``'s stability alone does not
guarantee reproducibility here because callers are not required to supply
candidates in any particular order — a set built from an unordered DB query,
for instance, could arrive in a different order on every call.

**Degenerate correlation.** ``statistics.correlation`` (stdlib, Python
>=3.10; this repo runs 3.12) raises ``StatisticsError`` when either input
series is constant (zero variance) or when fewer than two paired data points
survive. Both are real, expected inputs — a product with genuinely flat daily
impressions is not a bug — so both are caught here and mapped to a
correlation of ``0.0`` rather than raising: an undefined linear relationship
carries no positive selection signal, so it competes on equal footing with a
weakly anti-correlated candidate instead of crashing the whole selection.

**No scientific-stack dependency.** Only the stdlib ``statistics`` module is
used for Pearson correlation — no ``numpy``/``pandas``/``scipy``. The
equal-weighted control series itself is built with plain ``Decimal``
arithmetic, matching ``compute.py``.

**Purity.** No function here performs I/O or reads the wall clock — every
window is derived from the caller-supplied ``t``, mirroring the rest of this
package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import StatisticsError
from statistics import correlation as _pearson_correlation
from typing import Literal

from juli_backend.services.impact.metric_map import MetricSpec, RawDailyRecord
from juli_backend.services.impact.windows import WindowKind, Windows, compute_windows, date_range

DailySeries = Mapping[date, RawDailyRecord]

#: Top-K siblings selected (ADR-077 decision 3), and the minimum candidate
#: count below which selection is not attempted at all.
TOP_K = 5
MIN_CANDIDATES = 3

#: Quality bar on the mean Pearson correlation of the selected top-K set.
#: Below this, fall back to plain pre/post even when >=3 candidates exist.
MIN_MEAN_CORRELATION = 0.2

#: "active < 14 days" disqualifier (ADR-077 decision 3), relative to `t`.
MIN_ACTIVE_DAYS = 14

#: The two distinct triggers that both reach the fallback state — kept as
#: separate literal values (not collapsed into one bool) so each is
#: independently assertable, per the acceptance criteria.
FallbackReason = Literal["insufficient_candidates", "low_mean_correlation"]
_FALLBACK_INSUFFICIENT: FallbackReason = "insufficient_candidates"
_FALLBACK_LOW_CORRELATION: FallbackReason = "low_mean_correlation"


@dataclass(frozen=True, slots=True)
class ControlCandidate:
    """One same-shop sibling product under consideration as a control.

    ``daily`` should cover at least the full pre-window so completeness can
    be checked, and ideally the post-window too so the equal-weighted control
    series has post-period data when this candidate is selected.
    """

    product_id: str
    daily: DailySeries
    touched: bool
    first_active_date: date


@dataclass(frozen=True, slots=True)
class SelectedControl:
    """One chosen sibling, with the correlation that qualified it."""

    product_id: str
    correlation: float


@dataclass(frozen=True, slots=True)
class ControlPoolResult:
    """The outcome of one ``select_control_pool`` call for one metric.

    ``control_daily`` is always populated — with the equal-weighted control
    series on the full path, or the synthetic plain-pre/post series on
    fallback — so a caller can unconditionally plug it into
    ``control_daily_by_metric[metric.key]`` without branching on
    ``used_fallback``.
    """

    metric: str
    t: date
    kind: WindowKind
    windows: Windows
    used_fallback: bool
    fallback_reason: FallbackReason | None
    mean_correlation: float | None
    selected: tuple[SelectedControl, ...]
    control_daily: DailySeries

    def as_control_set_json(self) -> dict[str, object]:
        """The audit payload ADR-077 decision 3 requires on *every* reading
        (``impact_readings.control_set_json``), including fallback ones:
        chosen control IDs, their correlations, and the windows used. Stored
        as a plain JSON-serializable ``dict``; the caller (#1044) owns
        ``json.dumps`` and the actual column write — this module never
        touches ``models.py`` or performs I/O.
        """
        return {
            "control_ids": [c.product_id for c in self.selected],
            "correlations": [c.correlation for c in self.selected],
            "windows": {
                "pre_start": self.windows.pre_start.isoformat(),
                "pre_end": self.windows.pre_end.isoformat(),
                "post_start": self.windows.post_start.isoformat(),
                "post_end": self.windows.post_end.isoformat(),
            },
            "used_fallback": self.used_fallback,
            "fallback_reason": self.fallback_reason,
            "mean_correlation": self.mean_correlation,
        }


def _safe_correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation, or ``0.0`` for the two degenerate inputs
    ``statistics.correlation`` refuses: a constant series (zero variance) on
    either side, or fewer than two paired points. See the module docstring
    for why ``0.0`` (not an exception, not ``None``) is the designed output."""
    try:
        return _pearson_correlation(xs, ys)
    except StatisticsError:
        return 0.0


def _extract_complete_pre_series(
    daily: DailySeries, metric: MetricSpec, pre_dates: Sequence[date]
) -> dict[date, Decimal] | None:
    """The metric's daily values over every date in ``pre_dates``, or
    ``None`` if any date is missing a row or the extracted value is ``None``
    — an incomplete pre-window series is excluded outright, never zero-filled
    (ADR-077 decision 3 acceptance criterion)."""
    series: dict[date, Decimal] = {}
    for day in pre_dates:
        record = daily.get(day)
        value = metric.extractor(record) if record is not None else None
        if value is None:
            return None
        series[day] = value
    return series


def _average_record(records: Sequence[RawDailyRecord]) -> RawDailyRecord:
    """Equal-weighted mean of every raw column across ``records``, skipping
    ``None`` components rather than treating them as zero — the same
    "missing carries no information" rule ``windows.mean_over_window`` uses
    for the target series."""

    def avg(field: str) -> Decimal | None:
        values = [v for r in records if (v := getattr(r, field)) is not None]
        if not values:
            return None
        return sum(values, start=Decimal(0)) / Decimal(len(values))

    return RawDailyRecord(
        impressions=avg("impressions"),
        ctr=avg("ctr"),
        conversion_rate=avg("conversion_rate"),
        items_sold=avg("items_sold"),
        gmv=avg("gmv"),
        sku_orders=avg("sku_orders"),
    )


def _build_equal_weighted_control_daily(
    selected_daily: Sequence[DailySeries], start: date, end: date
) -> DailySeries:
    """One synthetic daily series over ``[start, end]``: each day is the
    equal-weighted mean, across the selected siblings, of every raw column
    present that day. A day with no data from any selected sibling is
    omitted (not zero-filled) — ``windows.mean_over_window`` already treats a
    missing day as "no information", so omitting is the correct, already-
    handled case rather than a new one to invent."""
    out: dict[date, RawDailyRecord] = {}
    for day in date_range(start, end):
        records = [daily[day] for daily in selected_daily if day in daily]
        if not records:
            continue
        out[day] = _average_record(records)
    return out


def _plain_pre_post_control_daily(start: date, end: date) -> DailySeries:
    """The fallback control series (ADR-077 decision 3): every raw column is
    a constant ``1`` across ``[start, end]``. Fed through ``compute.py``,
    ``compute_growth`` divides the constant post-window mean by the constant
    pre-window mean and gets exactly ``1`` (for any metric, including
    derived ones like ``gmv_per_order`` — both its inputs are constant ``1``
    too), so ``expected = pre * 1 = pre`` and ``incremental = post -
    expected = post - pre``: plain pre/post, computed by the exact same
    formula path as the full control-adjusted case, with no branching added
    to ``compute.py``."""
    constant = RawDailyRecord(
        impressions=Decimal(1),
        ctr=Decimal(1),
        conversion_rate=Decimal(1),
        items_sold=Decimal(1),
        gmv=Decimal(1),
        sku_orders=Decimal(1),
    )
    return {day: constant for day in date_range(start, end)}


def _fallback_result(
    metric: MetricSpec,
    t: date,
    kind: WindowKind,
    windows: Windows,
    fallback_reason: FallbackReason,
    mean_correlation: float | None,
) -> ControlPoolResult:
    return ControlPoolResult(
        metric=metric.key,
        t=t,
        kind=kind,
        windows=windows,
        used_fallback=True,
        fallback_reason=fallback_reason,
        mean_correlation=mean_correlation,
        selected=(),
        control_daily=_plain_pre_post_control_daily(windows.pre_start, windows.post_end),
    )


def _pre_window_volume(
    daily: DailySeries,
    metric: MetricSpec,
    pre_dates: Sequence[date],
    *,
    volume_of: Callable[[RawDailyRecord], Decimal | None] | None,
) -> Decimal | None:
    """Mean of the candidate's VOLUME INDICATOR over the pre-window.

    The volume floor is calibrated in counts — ADR-077 decision 4 reads
    ">= 1 order/day", ">= 50 impressions/day", ">= 20 visitors/day". Comparing
    it against the *metric being evaluated* is only meaningful when that metric
    is itself a count. For a rate it is a category error: CTR and
    conversion_rate are fractions (~0.01-0.30) that can never reach 50 or 20,
    so every candidate is disqualified and K-nearest-correlated selection
    silently dies for the Image and Description mutation families — half of
    decision 1's metric map — leaving those readings permanently capped at
    Thap no matter how good the real siblings are.

    Callers therefore pass ``volume_of`` (the family's indicator: sku_orders,
    impressions or visitors). When the metric is a count the metric's own
    extractor is the indicator, so ``volume_of`` may be omitted; when it is a
    rate, omitting it raises rather than silently disqualifying everything.
    """
    if volume_of is None:
        if metric.is_rate:
            raise ValueError(
                f"metric {metric.key!r} is a rate, so its own values cannot be compared "
                "against a count-calibrated volume floor; pass volume_of with the "
                "family's volume indicator (sku_orders / impressions / visitors)"
            )
        volume_of = metric.extractor

    values: list[Decimal] = []
    for day in pre_dates:
        record = daily.get(day)
        if record is None:
            return None
        value = volume_of(record)
        if value is None:
            return None
        values.append(value)
    if not values:
        return None
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def select_control_pool(
    metric: MetricSpec,
    target_daily: DailySeries,
    candidates: Sequence[ControlCandidate],
    t: date,
    kind: WindowKind,
    volume_floor: Decimal,
    volume_of: Callable[[RawDailyRecord], Decimal | None] | None = None,
) -> ControlPoolResult:
    """Select the control pool for one metric's reading at execution date
    ``t``.

    Pipeline: filter candidates by the three disqualifiers (touched,
    below-floor, active < 14 days) plus pre-window completeness; compute each
    survivor's Pearson correlation against the target's pre-period series for
    ``metric``; sort by correlation descending with ``product_id`` ascending
    as the deterministic tiebreak; take the top ``TOP_K``. Fewer than
    ``MIN_CANDIDATES`` eligible candidates, or a mean correlation among the
    selected top-K below ``MIN_MEAN_CORRELATION``, both fall back to the
    plain pre/post synthetic control series — two distinct triggers reaching
    the same designed state, reported via ``fallback_reason`` so they remain
    separately assertable.
    """
    windows = compute_windows(t, kind)
    pre_dates = date_range(windows.pre_start, windows.pre_end)

    target_pre = _extract_partial_pre_series(target_daily, metric, pre_dates)

    scored: list[tuple[ControlCandidate, float]] = []
    for candidate in candidates:
        if candidate.touched:
            continue
        if (t - candidate.first_active_date).days < MIN_ACTIVE_DAYS:
            continue

        candidate_pre = _extract_complete_pre_series(candidate.daily, metric, pre_dates)
        if candidate_pre is None:
            continue  # incomplete pre-window series — excluded, not zero-filled

        candidate_volume = _pre_window_volume(
            candidate.daily, metric, pre_dates, volume_of=volume_of
        )
        if candidate_volume is None or candidate_volume < volume_floor:
            continue

        paired_days = [day for day in pre_dates if day in target_pre]
        xs = [float(target_pre[day]) for day in paired_days]
        ys = [float(candidate_pre[day]) for day in paired_days]
        correlation = _safe_correlation(xs, ys)
        scored.append((candidate, correlation))

    # Deterministic order: correlation descending, product_id ascending on
    # ties — independent of the input candidates' iteration order.
    scored.sort(key=lambda pair: (-pair[1], pair[0].product_id))

    if len(scored) < MIN_CANDIDATES:
        return _fallback_result(
            metric, t, kind, windows, _FALLBACK_INSUFFICIENT, mean_correlation=None
        )

    top = scored[:TOP_K]
    mean_correlation = sum(correlation for _, correlation in top) / len(top)

    if mean_correlation < MIN_MEAN_CORRELATION:
        return _fallback_result(
            metric, t, kind, windows, _FALLBACK_LOW_CORRELATION, mean_correlation=mean_correlation
        )

    selected = tuple(
        SelectedControl(product_id=c.product_id, correlation=correlation) for c, correlation in top
    )
    control_daily = _build_equal_weighted_control_daily(
        [c.daily for c, _ in top], windows.pre_start, windows.post_end
    )
    return ControlPoolResult(
        metric=metric.key,
        t=t,
        kind=kind,
        windows=windows,
        used_fallback=False,
        fallback_reason=None,
        mean_correlation=mean_correlation,
        selected=selected,
        control_daily=control_daily,
    )


def _extract_partial_pre_series(
    daily: DailySeries, metric: MetricSpec, pre_dates: Sequence[date]
) -> dict[date, Decimal]:
    """The target's own pre-period series — unlike candidates, the target is
    never disqualified or excluded for gaps; missing/None days are simply
    dropped, and correlation is computed pairwise over whatever days survive
    on both sides (see ``select_control_pool``)."""
    series: dict[date, Decimal] = {}
    for day in pre_dates:
        record = daily.get(day)
        value = metric.extractor(record) if record is not None else None
        if value is not None:
            series[day] = value
    return series
