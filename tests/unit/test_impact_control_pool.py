"""Control-pool selection — K-nearest-correlated siblings (ADR-077 decision 3,
#1042).

Acceptance criteria covered here:
- Candidate discovery: same-shop products with complete pre-window rows;
  incomplete series excluded, not zero-filled.
- All three disqualifiers (touched, below-floor, active < 14 days) enforced
  and independently tested.
- Pearson correlation over the pre-period target series; top-K=5 selected,
  equal-weighted.
- Fewer than 3 candidates -> plain pre/post fallback (its own case).
- Mean correlation < 0.2 -> the same fallback (a distinct trigger, its own
  case).
- `control_set_json` payload (IDs, correlations, windows) present on every
  reading, including fallback ones.
- Deterministic tiebreak under equal correlation.
- Degenerate inputs (zero-variance target or candidate) never raise.
- Interface contract: `ControlPoolResult.control_daily` plugs directly into
  #1041's `reading.compute_metric_reading` with no adapter.
- The HIGH-severity defect fixed by #1062 on the reference wave branch: the
  volume floor is calibrated in COUNTS (orders/impressions/visitors), so
  screening must compare a candidate's volume INDICATOR against it, never
  the metric's own value -- a rate metric (ctr, conversion_rate) can never
  clear a count floor on its own values, which silently disabled K-nearest
  selection for half of ADR-077 decision 1's metric map in the prior
  implementation. See `TestVolumeIndicatorNotMetricAgainstTheFloor` below.

**Every acceptance-criteria class in this file is parametrized over all
three ADR-077 decision 4 metric families** (`revenue_orders`,
`impressions_ctr`, `conversion`) via `FAMILIES` below -- a GMV-only suite is
exactly what let the screening defect ship undetected through ten green PRs
and a full wave (ADR-079). Where a case genuinely cannot apply to one family
(e.g. "omitting volume_of raises" only applies to rate metrics), that is
stated in a comment at the point the family is excluded from
parametrization, not silently skipped.

Every date in this file is derived from the single fixed reference point
`T = date(2026, 1, 15)` -- no `datetime.now()`/`date.today()` anywhere, so
nothing here can age out of a window overnight (see #1032).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.impact.control_pool import (
    MIN_ACTIVE_DAYS,
    MIN_CANDIDATES,
    TOP_K,
    ControlCandidate,
    select_control_pool,
)
from juli_backend.services.impact.metric_map import (
    CONVERSION_RATE,
    CTR,
    GMV,
    GMV_PER_ORDER,
    MetricSpec,
    RawDailyRecord,
)
from juli_backend.services.impact.reading import compute_metric_reading

T = date(2026, 1, 15)
PRE_START, PRE_END = date(2026, 1, 1), date(2026, 1, 14)  # T-14 .. T-1
POST_START_FINAL, POST_END_FINAL = date(2026, 1, 16), date(2026, 1, 29)  # T+1 .. T+14
LONG_ACTIVE = T - timedelta(days=30)  # comfortably >= 14 days active


# ---------------------------------------------------------------------------
# Per-family fixtures. `metric_field`/`volume_field` name the RawDailyRecord
# columns the metric and its ADR-077 decision-4 volume indicator each read;
# `volume_floor` is the real calibrated floor value; `metric_base`/
# `volume_base`/`low_volume` are realistic per-day magnitudes so fixtures
# read as real data, not arbitrary numbers.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FamilyCase:
    name: str
    metric: MetricSpec
    metric_field: str
    volume_field: str
    volume_floor: Decimal
    metric_base: Decimal
    volume_base: Decimal
    low_volume: Decimal


REVENUE_ORDERS = FamilyCase(
    name="revenue_orders",
    metric=GMV,
    metric_field="gmv",
    volume_field="sku_orders",  # the order count GMV/items_sold/gmv_per_order derive from
    volume_floor=Decimal(1),  # >= 1 order/day, ADR-077 decision 4
    metric_base=Decimal("120.00"),
    volume_base=Decimal("12"),
    low_volume=Decimal("0.4"),
)
IMPRESSIONS_CTR = FamilyCase(
    name="impressions_ctr",
    metric=CTR,
    metric_field="ctr",
    volume_field="impressions",
    volume_floor=Decimal(50),  # >= 50 impressions/day
    metric_base=Decimal("0.05"),
    volume_base=Decimal("900"),
    low_volume=Decimal("9"),
)
CONVERSION = FamilyCase(
    name="conversion",
    metric=CONVERSION_RATE,
    metric_field="conversion_rate",
    volume_field="visitors",  # the real AnalyticsPerformanceInterval column, not impressions
    volume_floor=Decimal(20),  # >= 20 visitors/day
    metric_base=Decimal("0.03"),
    volume_base=Decimal("400"),
    low_volume=Decimal("9"),
)

FAMILIES: tuple[FamilyCase, ...] = (REVENUE_ORDERS, IMPRESSIONS_CTR, CONVERSION)
FAMILY_IDS = [case.name for case in FAMILIES]

# The two rate families -- the shape the original defect actually broke
# (a rate metric's own values, ~0.01-0.30, can never clear a count-calibrated
# floor of 50 or 20). `revenue_orders`'s metric (GMV) is a count, so it is
# excluded from rate-only cases below with a comment at each exclusion site,
# never silently dropped.
RATE_FAMILIES: tuple[FamilyCase, ...] = (IMPRESSIONS_CTR, CONVERSION)
RATE_FAMILY_IDS = [case.name for case in RATE_FAMILIES]


def _record(case: FamilyCase, metric_value: Decimal, volume_value: Decimal) -> RawDailyRecord:
    return RawDailyRecord(**{case.metric_field: metric_value, case.volume_field: volume_value})


def _volume_of(case: FamilyCase):
    field = case.volume_field
    return lambda day: getattr(day, field)


def _metric_of(case: FamilyCase, record: RawDailyRecord) -> Decimal | None:
    return getattr(record, case.metric_field)


def _select(case: FamilyCase, target, candidates, *, t=T, kind="final", floor=None, volume_of=...):
    """Thin wrapper around `select_control_pool` that defaults to the
    family's own metric/floor/volume indicator, so every test below reads as
    "select for this family" rather than repeating five positional args."""
    resolved_volume_of = _volume_of(case) if volume_of is ... else volume_of
    return select_control_pool(
        case.metric,
        target,
        candidates,
        t,
        kind,
        case.volume_floor if floor is None else floor,
        volume_of=resolved_volume_of,
    )


def _target_increasing(case: FamilyCase) -> dict[date, RawDailyRecord]:
    """14 days, metric value strictly increasing (1x..14x metric_base -- real
    day-to-day variance, non-degenerate for Pearson correlation), volume
    indicator comfortably above the family floor throughout."""
    return {
        PRE_START + timedelta(days=i): _record(
            case, case.metric_base * Decimal(i + 1), case.volume_base
        )
        for i in range(14)
    }


def _flat_series(
    case: FamilyCase, start: date, end: date, metric_value: Decimal, volume_value: Decimal
) -> dict[date, RawDailyRecord]:
    days = (end - start).days
    return {
        start + timedelta(days=i): _record(case, metric_value, volume_value)
        for i in range(days + 1)
    }


def _split_series(
    case: FamilyCase,
    start: date,
    end: date,
    first_half: Decimal,
    second_half: Decimal,
    volume_value: Decimal,
) -> dict[date, RawDailyRecord]:
    """Real day-to-day variance (not constant): first half at `first_half`,
    second half at `second_half`, so Pearson correlation against it is
    non-degenerate."""
    days = (end - start).days + 1
    half = days // 2
    out: dict[date, RawDailyRecord] = {}
    for i in range(days):
        value = first_half if i < half else second_half
        out[start + timedelta(days=i)] = _record(case, value, volume_value)
    return out


def _identical_candidate(case: FamilyCase, product_id: str, target_pre: dict) -> ControlCandidate:
    """A candidate whose pre-window series is bit-for-bit identical to the
    target's -- Pearson correlation with itself is exactly 1.0."""
    return ControlCandidate(
        product_id=product_id, daily=dict(target_pre), touched=False, first_active_date=LONG_ACTIVE
    )


# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestPreWindowCompleteness:
    def test_candidate_missing_one_pre_window_day_is_excluded_not_zero_filled(self, case):
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        incomplete_daily = dict(target)
        del incomplete_daily[date(2026, 1, 7)]  # one gap inside the pre-window
        incomplete = ControlCandidate(
            product_id="incomplete",
            daily=incomplete_daily,
            touched=False,
            first_active_date=LONG_ACTIVE,
        )

        result = _select(case, target, [*clean, incomplete])

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "incomplete" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestCandidateDisqualifiers:
    def test_touched_candidate_is_excluded(self, case):
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        touched = ControlCandidate(
            product_id="touched-one",
            daily=dict(target),
            touched=True,
            first_active_date=LONG_ACTIVE,
        )

        result = _select(case, target, [*clean, touched])

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "touched-one" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}

    def test_candidate_below_the_family_volume_floor_is_excluded(self, case):
        """The floor is compared against the volume INDICATOR (sku_orders /
        impressions / visitors), never the metric's own value -- this is the
        exact comparison #1062 fixed. The low-volume candidate's metric
        series is bit-for-bit identical to the target's (would otherwise be
        a perfect correlation match), proving exclusion is driven by the
        volume indicator alone, not correlation quality."""
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        low_volume_daily = {
            day: _record(case, _metric_of(case, record), case.low_volume)
            for day, record in target.items()
        }
        low_volume = ControlCandidate(
            product_id="low-volume",
            daily=low_volume_daily,
            touched=False,
            first_active_date=LONG_ACTIVE,
        )

        result = _select(case, target, [*clean, low_volume])

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "low-volume" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}

    def test_candidate_active_less_than_fourteen_days_is_excluded(self, case):
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        too_new = ControlCandidate(
            product_id="too-new",
            daily=dict(target),
            touched=False,
            first_active_date=T - timedelta(days=5),
        )

        result = _select(case, target, [*clean, too_new])

        control_ids = {c.product_id for c in result.selected}
        assert "too-new" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}

    def test_candidate_active_exactly_fourteen_days_qualifies(self, case):
        """Boundary: "< 14 days" disqualifies; exactly 14 does not."""
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(2)]
        exactly_boundary = ControlCandidate(
            product_id="boundary",
            daily=dict(target),
            touched=False,
            first_active_date=T - timedelta(days=MIN_ACTIVE_DAYS),
        )

        result = _select(case, target, [*clean, exactly_boundary])

        control_ids = {c.product_id for c in result.selected}
        assert "boundary" in control_ids


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestTopKSelectionAndEqualWeighting:
    def test_six_candidates_top_five_selected_weakest_excluded(self, case):
        target = _target_increasing(case)

        def _scaled(product_id: str, factor: Decimal) -> ControlCandidate:
            daily = {
                day: _record(case, _metric_of(case, record) * factor, case.volume_base)
                for day, record in target.items()
            }
            return ControlCandidate(product_id, daily, touched=False, first_active_date=LONG_ACTIVE)

        def _reversed_candidate(product_id: str) -> ControlCandidate:
            days = sorted(target)
            values = [_metric_of(case, target[d]) for d in days]
            daily = {
                d: _record(case, v, case.volume_base)
                for d, v in zip(days, reversed(values), strict=True)
            }
            return ControlCandidate(product_id, daily, touched=False, first_active_date=LONG_ACTIVE)

        def _swapped(product_id: str, i: int, j: int) -> ControlCandidate:
            days = sorted(target)
            values = [_metric_of(case, target[d]) for d in days]
            values[i], values[j] = values[j], values[i]
            daily = {
                d: _record(case, v, case.volume_base) for d, v in zip(days, values, strict=True)
            }
            return ControlCandidate(product_id, daily, touched=False, first_active_date=LONG_ACTIVE)

        c1 = _identical_candidate(case, "c1-identical", target)  # corr == 1.0
        c2 = _scaled("c2-scaled", Decimal(2))  # corr == 1.0 (scale invariant)
        c3 = _swapped("c3-lightly-shuffled", 3, 4)  # corr close to but < 1.0
        c4 = ControlCandidate(  # constant -> degenerate -> corr == 0.0
            "c4-constant",
            _flat_series(case, PRE_START, PRE_END, case.metric_base * 7, case.volume_base),
            touched=False,
            first_active_date=LONG_ACTIVE,
        )
        c5 = _swapped("c5-heavily-shuffled", 0, 13)  # weaker positive corr
        c6 = _reversed_candidate("c6-reversed")  # corr == -1.0, always excluded

        result = _select(case, target, [c1, c2, c3, c4, c5, c6])

        assert result.used_fallback is False
        assert len(result.selected) == TOP_K == 5
        control_ids = {c.product_id for c in result.selected}
        assert "c6-reversed" not in control_ids
        assert control_ids == {
            "c1-identical",
            "c2-scaled",
            "c3-lightly-shuffled",
            "c4-constant",
            "c5-heavily-shuffled",
        }

        by_id = {c.product_id: c.correlation for c in result.selected}
        assert by_id["c1-identical"] == pytest.approx(1.0)
        assert by_id["c2-scaled"] == pytest.approx(1.0)
        assert by_id["c4-constant"] == 0.0

        # Equal-weighted: the control series is the plain arithmetic mean of
        # the five selected candidates' own daily metric values, not a
        # category- or correlation-weighted blend.
        first_day = PRE_START
        selected_daily = [c.daily for c in (c1, c2, c3, c4, c5)]
        expected_first_day = sum(
            (_metric_of(case, d[first_day]) for d in selected_daily), start=Decimal(0)
        ) / Decimal(5)
        assert _metric_of(case, result.control_daily[first_day]) == expected_first_day

    def test_three_or_four_eligible_selects_all_of_them(self, case):
        """ "top K=5 (min 3)" -- with exactly 3 eligible, all 3 are used, no
        fallback."""
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        result = _select(case, target, clean)
        assert result.used_fallback is False
        assert len(result.selected) == 3


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestDeterministicTiebreak:
    def test_tied_correlation_orders_by_product_id_regardless_of_input_order(self, case):
        target = _target_increasing(case)
        tied_a = _identical_candidate(case, "alpha", target)
        tied_z = _identical_candidate(case, "zeta", target)
        third = _identical_candidate(case, "middle", target)

        result_order_1 = _select(case, target, [tied_z, tied_a, third])
        result_order_2 = _select(case, target, [third, tied_a, tied_z])

        ids_1 = [c.product_id for c in result_order_1.selected]
        ids_2 = [c.product_id for c in result_order_2.selected]
        assert ids_1 == ids_2
        assert ids_1 == ["alpha", "middle", "zeta"]  # all tied at 1.0 -> ascending product_id


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestFallbackInsufficientCandidates:
    def test_two_candidates_falls_back_even_though_both_perfectly_correlated(self, case):
        target = _target_increasing(case)
        candidates = [_identical_candidate(case, f"only-{i}", target) for i in range(2)]

        result = _select(case, target, candidates)

        assert len(candidates) < MIN_CANDIDATES
        assert result.used_fallback is True
        assert result.fallback_reason == "insufficient_candidates"
        assert result.selected == ()
        assert result.mean_correlation is None
        # Fallback control series is the constant-1 plain pre/post series.
        sample_day = next(iter(result.control_daily))
        assert _metric_of(case, result.control_daily[sample_day]) == Decimal(1)


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestFallbackLowMeanCorrelation:
    def test_three_anti_correlated_candidates_falls_back_on_quality_bar(self, case):
        target = _target_increasing(case)
        days = sorted(target)
        values = [_metric_of(case, target[d]) for d in days]
        reversed_daily = {
            d: _record(case, v, case.volume_base)
            for d, v in zip(days, reversed(values), strict=True)
        }
        candidates = [
            ControlCandidate(
                f"anti-{i}", dict(reversed_daily), touched=False, first_active_date=LONG_ACTIVE
            )
            for i in range(3)
        ]

        result = _select(case, target, candidates)

        assert len(candidates) >= MIN_CANDIDATES  # NOT the insufficient-candidates case
        assert result.used_fallback is True
        assert result.fallback_reason == "low_mean_correlation"
        assert result.mean_correlation == pytest.approx(-1.0)
        assert result.selected == ()


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestDegenerateInputsDoNotRaise:
    def test_constant_candidate_series_scores_zero_and_does_not_raise(self, case):
        target = _target_increasing(case)
        strong = [_identical_candidate(case, f"strong-{i}", target) for i in range(2)]
        flat = ControlCandidate(
            "flat-sibling",
            _flat_series(case, PRE_START, PRE_END, case.metric_base * 9, case.volume_base),
            touched=False,
            first_active_date=LONG_ACTIVE,
        )

        result = _select(case, target, [*strong, flat])

        by_id = {c.product_id: c.correlation for c in result.selected}
        assert by_id["flat-sibling"] == 0.0
        assert result.used_fallback is False  # mean (1+1+0)/3 = 0.667 >= 0.2

    def test_constant_target_series_scores_every_candidate_zero_and_falls_back(self, case):
        flat_target = _flat_series(case, PRE_START, PRE_END, case.metric_base * 5, case.volume_base)
        real_target = _target_increasing(case)
        candidates = [_identical_candidate(case, f"sib-{i}", real_target) for i in range(3)]

        result = _select(case, flat_target, candidates)

        assert result.used_fallback is True
        assert result.fallback_reason == "low_mean_correlation"
        assert result.mean_correlation == 0.0


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestControlSetJsonAudit:
    def test_full_path_result_serializes_ids_correlations_and_windows(self, case):
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        result = _select(case, target, clean)

        payload = result.as_control_set_json()
        assert sorted(payload["control_ids"]) == ["clean-0", "clean-1", "clean-2"]
        assert len(payload["correlations"]) == 3
        assert payload["windows"] == {
            "pre_start": "2026-01-01",
            "pre_end": "2026-01-14",
            "post_start": "2026-01-16",
            "post_end": "2026-01-29",
        }
        assert payload["used_fallback"] is False
        assert payload["fallback_reason"] is None
        json.dumps(payload)  # must be JSON-serializable as-is

    def test_fallback_result_still_serializes_a_full_payload(self, case):
        target = _target_increasing(case)
        candidates = [_identical_candidate(case, f"only-{i}", target) for i in range(2)]
        result = _select(case, target, candidates)

        payload = result.as_control_set_json()
        assert payload["control_ids"] == []
        assert payload["correlations"] == []
        assert payload["windows"]["pre_start"] == "2026-01-01"
        assert payload["used_fallback"] is True
        assert payload["fallback_reason"] == "insufficient_candidates"
        json.dumps(payload)


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestDeterminismAcrossCalls:
    def test_repeated_calls_produce_identical_results(self, case):
        target = _target_increasing(case)
        clean = [_identical_candidate(case, f"clean-{i}", target) for i in range(3)]
        first = _select(case, dict(target), list(clean))
        second = _select(case, dict(target), list(clean))
        assert first == second


@pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
class TestInterfaceContractWithReading:
    """Proves `ControlPoolResult.control_daily` plugs directly into #1041's
    `reading.compute_metric_reading` -- the exact shape
    `control_daily_by_metric[metric.key]` expects -- with no adapter.

    Scale-invariant fixture: every value is `S = metric_base / 100` times the
    reference GMV scenario's numbers (target pre 90/110 split -> mean 100,
    post flat 150; control pre 45/55 split -> mean 50, post flat 60), so
    growth (a ratio) and impact_pct (a ratio) come out identical across all
    three families regardless of the metric's native magnitude, while
    pre/post/expected/incremental scale with S -- proving the DiD formula
    itself is unit-agnostic to a rate as well as a count/currency metric.
    """

    def _scale(self, case: FamilyCase) -> Decimal:
        return case.metric_base / Decimal(100)

    def _target_daily(self, case: FamilyCase) -> dict[date, RawDailyRecord]:
        s = self._scale(case)
        pre = _split_series(
            case, PRE_START, PRE_END, Decimal(90) * s, Decimal(110) * s, case.volume_base
        )
        post = _flat_series(
            case, POST_START_FINAL, POST_END_FINAL, Decimal(150) * s, case.volume_base
        )
        return {**pre, **post}

    def test_full_path_control_series_feeds_the_known_hand_computed_reading(self, case):
        s = self._scale(case)
        target_daily = self._target_daily(case)

        def _sibling(product_id: str) -> ControlCandidate:
            pre = _split_series(
                case, PRE_START, PRE_END, Decimal(45) * s, Decimal(55) * s, case.volume_base
            )
            post = _flat_series(
                case, POST_START_FINAL, POST_END_FINAL, Decimal(60) * s, case.volume_base
            )
            return ControlCandidate(
                product_id, {**pre, **post}, touched=False, first_active_date=LONG_ACTIVE
            )

        candidates = [_sibling(f"sib-{i}") for i in range(3)]
        result = _select(case, target_daily, candidates)
        assert result.used_fallback is False
        assert all(c.correlation == pytest.approx(1.0) for c in result.selected)

        reading = compute_metric_reading(
            case.metric, target_daily, result.control_daily, T, "final"
        )

        # Same hand-computed scenario as test_impact_reading.py's
        # test_normal_reading_hand_computed, scaled by `s`: growth and
        # impact_pct are ratios, so they are identical across all families.
        assert reading.status == "ok"
        assert reading.pre == Decimal(100) * s
        assert reading.post == Decimal(150) * s
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal(120) * s
        assert reading.incremental == Decimal(30) * s
        assert reading.impact_pct == Decimal("30") / Decimal("120")

    def test_fallback_control_series_reduces_the_formula_to_plain_pre_post(self, case):
        target_daily = self._target_daily(case)
        fallback_target = _target_increasing(case)
        candidates = [
            _identical_candidate(case, f"only-{i}", fallback_target) for i in range(2)
        ]  # only 2 -> fallback

        result = _select(case, target_daily, candidates)
        assert result.used_fallback is True

        reading = compute_metric_reading(
            case.metric, target_daily, result.control_daily, T, "final"
        )

        s = self._scale(case)
        assert reading.status == "ok"
        assert reading.pre == Decimal(100) * s
        assert reading.post == Decimal(150) * s
        assert reading.growth == Decimal(1)  # constant control series -> ratio collapses to 1
        assert reading.expected == reading.pre  # plain pre/post: expected == pre
        assert reading.incremental == reading.post - reading.pre  # == 50 * s

    def test_fallback_control_series_yields_unit_growth_for_gmv_per_order_too(self, case):
        """The fallback series is a constant `1` across every raw column
        (impressions/ctr/conversion_rate/items_sold/gmv/sku_orders -- see
        `_plain_pre_post_control_daily`), so even a *derived* metric
        (gmv_per_order = gmv / sku_orders, reading two fields from the same
        record) collapses to a growth ratio of 1. Independent of which
        family's own metric was being read when the fallback was chosen --
        the fallback series shape does not vary by family."""
        target = _target_increasing(case)
        candidates = [_identical_candidate(case, f"only-{i}", target) for i in range(2)]
        result = _select(case, target, candidates)
        assert result.used_fallback is True

        sample_day = next(iter(result.control_daily))
        record = result.control_daily[sample_day]
        assert GMV_PER_ORDER.extractor(record) == Decimal(1)


class TestPearsonExactValues:
    """Hand-derivable Pearson correlation boundary cases, independent of the
    selection logic above and of any metric family -- proves the formula
    itself, matching the style of compute.py's own hand-computed tests."""

    def test_identical_series_is_perfectly_correlated(self):
        xs = [float(i) for i in range(1, 15)]
        assert statistics.correlation(xs, xs) == 1.0

    def test_reversed_series_is_perfectly_anti_correlated(self):
        xs = [float(i) for i in range(1, 15)]
        ys = list(reversed(xs))
        assert statistics.correlation(xs, ys) == -1.0

    def test_positive_affine_transform_preserves_perfect_correlation(self):
        xs = [float(i) for i in range(1, 15)]
        ys = [2.0 * x + 5.0 for x in xs]
        assert statistics.correlation(xs, ys) == 1.0


class TestVolumeIndicatorNotMetricAgainstTheFloor:
    """Regression for the HIGH-severity defect fixed on the reference wave
    branch (#1062): `select_control_pool` used to compare a candidate's mean
    of the METRIC ITSELF against the volume floor. ADR-077 decision 4's
    floors are counts (">= 50 impressions/day", ">= 20 visitors/day"), and
    CTR / conversion_rate are fractions around 0.01-0.30 -- so no candidate
    could ever clear them. Every CTR and conversion reading fell back to
    plain pre/post, permanently capped at Thap, for the Image and
    Description mutation families: half of ADR-077 decision 1's metric map,
    silently disabled in production, and undetected because every existing
    test drove only the GMV/PRICE family, where the metric happens to be a
    count and the comparison is coincidentally harmless.

    This class is the mutation-pin proof: `test_rate_candidates_survive_the_
    family_floor_when_volume_of_is_used` is the test verified to go RED when
    `_pre_window_volume`'s `volume_of` branch is deleted (candidate volume
    measured from the metric's own extractor for every metric, rate or not)
    -- see the PR body / implementation artifact for the actual red output
    captured during that mutation check.
    """

    @pytest.mark.parametrize("case", RATE_FAMILIES, ids=RATE_FAMILY_IDS)
    def test_rate_candidates_survive_the_family_floor_when_volume_of_is_used(self, case):
        """5 candidates with the family's real volume indicator far above the
        floor (900 impressions/day, 400 visitors/day) but a metric value
        (~0.03-0.05) that could never itself clear a floor of 50 or 20 --
        must all survive and be selected, proving the floor reads the
        indicator, not the metric."""
        target = _target_increasing(case)
        candidates = [
            ControlCandidate(
                product_id=f"p{i}",
                daily={
                    day: _record(case, _metric_of(case, record), case.volume_base)
                    for day, record in target.items()
                },
                touched=False,
                first_active_date=LONG_ACTIVE,
            )
            for i in range(5)
        ]

        result = _select(case, target, candidates)

        assert result.used_fallback is False, (
            f"{case.name} candidates with {case.volume_base} {case.volume_field}/day must "
            f"clear the >={case.volume_floor} floor; comparing the metric's own "
            f"~{case.metric_base} values against {case.volume_floor} disqualifies everyone "
            "-- this is exactly the #1062 defect"
        )
        assert len(result.selected) == 5

    def test_revenue_orders_metric_is_a_count_so_this_defect_cannot_manifest_there(self):
        """`revenue_orders`'s target metric (GMV) is itself a count/currency
        value with `is_rate=False` -- comparing GMV's own values (dollars,
        typically well above 1) against the >=1-order floor happens to pass
        even under the broken comparison, which is exactly why the original
        defect shipped undetected: every pre-#1062 test exercised only this
        family. It is intentionally excluded from the rate-only mutation-pin
        test above and documented here instead of silently omitted --
        `test_candidate_below_the_family_volume_floor_is_excluded` (in
        `TestCandidateDisqualifiers`, parametrized over all three families)
        still proves the floor is measured against `sku_orders`, not `gmv`,
        for this family: a candidate with identical GMV but below-floor
        `sku_orders` is excluded there."""
        assert REVENUE_ORDERS.metric.is_rate is False
        assert IMPRESSIONS_CTR.metric.is_rate is True
        assert CONVERSION.metric.is_rate is True

    @pytest.mark.parametrize("case", RATE_FAMILIES, ids=RATE_FAMILY_IDS)
    def test_a_rate_metric_without_a_volume_indicator_raises_rather_than_silently_disqualifying(
        self, case
    ):
        """Fail loudly, never silently. Silent disqualification is what made
        the original defect invisible for an entire wave."""
        target = _target_increasing(case)
        candidates = [_identical_candidate(case, f"p{i}", target) for i in range(3)]

        with pytest.raises(ValueError, match="is a rate"):
            select_control_pool(
                case.metric, target, candidates, T, "final", case.volume_floor
            )  # volume_of omitted

    def test_a_count_metric_without_a_volume_indicator_defaults_to_its_own_value(self):
        """The inverse of the rate case: omitting `volume_of` for a count
        metric (GMV, `is_rate=False`) does NOT raise -- `_pre_window_volume`
        defaults to the metric's own extractor as the indicator. This is the
        documented, deliberate fallback contract for count/currency metrics
        (not a gap the fix needs to close), and it is exactly what let the
        original defect look "coincidentally fine" for the revenue/orders
        family while being silently broken for the two rate families."""
        case = REVENUE_ORDERS
        target = _target_increasing(case)
        candidates = [_identical_candidate(case, f"p{i}", target) for i in range(3)]

        result = select_control_pool(
            case.metric, target, candidates, T, "final", case.volume_floor
        )  # volume_of omitted -- must not raise

        assert result.used_fallback is False
        assert len(result.selected) == 3

    @pytest.mark.parametrize("case", FAMILIES, ids=FAMILY_IDS)
    def test_a_genuinely_low_volume_candidate_pool_is_still_disqualified(self, case):
        """The fix must not disable the floor -- only measure it in the
        right unit. All five candidates have a metric series identical to
        the target's (perfect correlation) but every one sits below the
        family's real volume floor, so the pool is genuinely insufficient
        and must fall back -- not silently pass because "the floor doesn't
        apply anymore"."""
        target = _target_increasing(case)
        low_volume_candidates = [
            ControlCandidate(
                product_id=f"low{i}",
                daily={
                    day: _record(case, _metric_of(case, record), case.low_volume)
                    for day, record in target.items()
                },
                touched=False,
                first_active_date=LONG_ACTIVE,
            )
            for i in range(5)
        ]

        result = _select(case, target, low_volume_candidates)

        assert result.used_fallback is True
        assert result.fallback_reason == "insufficient_candidates"
