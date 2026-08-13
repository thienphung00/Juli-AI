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

Every date in this file is derived from the single fixed reference point
`T = date(2026, 1, 15)` — no `datetime.now()`/`date.today()` anywhere, so
nothing here can age out of a window overnight (see #1032).
"""

from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.impact.confidence import (
    volume_floor_for,
    volume_indicator_for,
)
from juli_backend.services.impact.control_pool import (
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
    RawDailyRecord,
)
from juli_backend.services.impact.reading import compute_metric_reading

T = date(2026, 1, 15)
PRE_START, PRE_END = date(2026, 1, 1), date(2026, 1, 14)  # T-14 .. T-1
POST_START_FINAL, POST_END_FINAL = date(2026, 1, 16), date(2026, 1, 29)  # T+1 .. T+14

VOLUME_FLOOR = Decimal(1)
LONG_ACTIVE = T - timedelta(days=30)  # comfortably >= 14 days active


def _flat_gmv_series(start: date, end: date, value: Decimal) -> dict[date, RawDailyRecord]:
    days = (end - start).days
    return {start + timedelta(days=i): RawDailyRecord(gmv=value) for i in range(days + 1)}


def _split_gmv_series(
    start: date, end: date, first_half: Decimal, second_half: Decimal
) -> dict[date, RawDailyRecord]:
    """14 days, first 7 at `first_half`, last 7 at `second_half` — real
    day-to-day variance (not constant), so Pearson correlation against it is
    non-degenerate."""
    days = (end - start).days + 1
    half = days // 2
    out: dict[date, RawDailyRecord] = {}
    for i in range(days):
        value = first_half if i < half else second_half
        out[start + timedelta(days=i)] = RawDailyRecord(gmv=value)
    return out


def _identical_to_target_candidate(product_id: str, target_pre: dict) -> ControlCandidate:
    """A candidate whose pre-window series is bit-for-bit identical to the
    target's -- Pearson correlation with itself is exactly 1.0."""
    return ControlCandidate(
        product_id=product_id,
        daily=dict(target_pre),
        touched=False,
        first_active_date=LONG_ACTIVE,
    )


TARGET_PRE_INCREASING = {
    PRE_START + timedelta(days=i): RawDailyRecord(gmv=Decimal(i + 1)) for i in range(14)
}  # 1, 2, ..., 14


class TestPreWindowCompleteness:
    def test_candidate_missing_one_pre_window_day_is_excluded_not_zero_filled(self):
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        incomplete_daily = dict(TARGET_PRE_INCREASING)
        del incomplete_daily[date(2026, 1, 7)]  # one gap inside the pre-window
        incomplete = ControlCandidate(
            product_id="incomplete",
            daily=incomplete_daily,
            touched=False,
            first_active_date=LONG_ACTIVE,
        )

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [*clean, incomplete], T, "final", VOLUME_FLOOR
        )

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "incomplete" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}


class TestCandidateDisqualifiers:
    def test_touched_candidate_is_excluded(self):
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        touched = ControlCandidate(
            product_id="touched-one",
            daily=dict(TARGET_PRE_INCREASING),
            touched=True,
            first_active_date=LONG_ACTIVE,
        )

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [*clean, touched], T, "final", VOLUME_FLOOR
        )

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "touched-one" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}

    def test_candidate_below_volume_floor_is_excluded(self):
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        # Mean pre-period gmv is 1 -- below a floor of 5, while the clean
        # candidates' mean (7.5, from values 1..14) clears it easily.
        low_volume = ControlCandidate(
            product_id="low-volume",
            daily=_flat_gmv_series(PRE_START, PRE_END, Decimal(1)),
            touched=False,
            first_active_date=LONG_ACTIVE,
        )

        result = select_control_pool(
            GMV,
            TARGET_PRE_INCREASING,
            [*clean, low_volume],
            T,
            "final",
            volume_floor=Decimal(5),
        )

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "low-volume" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}

    def test_candidate_active_less_than_fourteen_days_is_excluded(self):
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        too_new = ControlCandidate(
            product_id="too-new",
            daily=dict(TARGET_PRE_INCREASING),
            touched=False,
            first_active_date=T - timedelta(days=5),
        )

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [*clean, too_new], T, "final", VOLUME_FLOOR
        )

        assert result.used_fallback is False
        control_ids = {c.product_id for c in result.selected}
        assert "too-new" not in control_ids
        assert control_ids == {"clean-0", "clean-1", "clean-2"}

    def test_candidate_active_exactly_fourteen_days_qualifies(self):
        """Boundary: "< 14 days" disqualifies; exactly 14 does not."""
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(2)
        ]
        exactly_boundary = ControlCandidate(
            product_id="boundary",
            daily=dict(TARGET_PRE_INCREASING),
            touched=False,
            first_active_date=T - timedelta(days=14),
        )

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [*clean, exactly_boundary], T, "final", VOLUME_FLOOR
        )

        control_ids = {c.product_id for c in result.selected}
        assert "boundary" in control_ids


class TestTopKSelectionAndEqualWeighting:
    def test_six_candidates_top_five_selected_weakest_excluded(self):
        target = TARGET_PRE_INCREASING  # 1..14

        def _scaled(product_id: str, factor: Decimal) -> ControlCandidate:
            daily = {day: RawDailyRecord(gmv=record.gmv * factor) for day, record in target.items()}
            return ControlCandidate(product_id, daily, touched=False, first_active_date=LONG_ACTIVE)

        def _reversed(product_id: str) -> ControlCandidate:
            days = sorted(target)
            values = [target[d].gmv for d in days]
            daily = {d: RawDailyRecord(gmv=v) for d, v in zip(days, reversed(values), strict=True)}
            return ControlCandidate(product_id, daily, touched=False, first_active_date=LONG_ACTIVE)

        def _swapped(product_id: str, i: int, j: int) -> ControlCandidate:
            days = sorted(target)
            values = [target[d].gmv for d in days]
            values[i], values[j] = values[j], values[i]
            daily = {d: RawDailyRecord(gmv=v) for d, v in zip(days, values, strict=True)}
            return ControlCandidate(product_id, daily, touched=False, first_active_date=LONG_ACTIVE)

        c1 = _identical_to_target_candidate("c1-identical", target)  # corr == 1.0
        c2 = _scaled("c2-scaled", Decimal(2))  # corr == 1.0 (scale invariant)
        c3 = _swapped("c3-lightly-shuffled", 3, 4)  # corr close to but < 1.0
        c4 = ControlCandidate(  # constant -> degenerate -> corr == 0.0
            "c4-constant",
            _flat_gmv_series(PRE_START, PRE_END, Decimal(7)),
            touched=False,
            first_active_date=LONG_ACTIVE,
        )
        c5 = _swapped("c5-heavily-shuffled", 0, 13)  # weaker positive corr
        c6 = _reversed("c6-reversed")  # corr == -1.0, the global minimum: always excluded

        result = select_control_pool(
            GMV, target, [c1, c2, c3, c4, c5, c6], T, "final", VOLUME_FLOOR
        )

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
        # the five selected candidates' own daily values, not a category- or
        # correlation-weighted blend.
        first_day = PRE_START
        selected_daily = [c.daily for c in (c1, c2, c3, c4, c5)]
        expected_first_day_gmv = sum(
            (d[first_day].gmv for d in selected_daily), start=Decimal(0)
        ) / Decimal(5)
        assert result.control_daily[first_day].gmv == expected_first_day_gmv

    def test_three_or_four_eligible_selects_all_of_them(self):
        """ "top K=5 (min 3)" -- with exactly 3 eligible, all 3 are used, no
        fallback."""
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        result = select_control_pool(GMV, TARGET_PRE_INCREASING, clean, T, "final", VOLUME_FLOOR)
        assert result.used_fallback is False
        assert len(result.selected) == 3


class TestDeterministicTiebreak:
    def test_tied_correlation_orders_by_product_id_regardless_of_input_order(self):
        tied_a = _identical_to_target_candidate("alpha", TARGET_PRE_INCREASING)
        tied_z = _identical_to_target_candidate("zeta", TARGET_PRE_INCREASING)
        third = _identical_to_target_candidate("middle", TARGET_PRE_INCREASING)

        result_order_1 = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [tied_z, tied_a, third], T, "final", VOLUME_FLOOR
        )
        result_order_2 = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [third, tied_a, tied_z], T, "final", VOLUME_FLOOR
        )

        ids_1 = [c.product_id for c in result_order_1.selected]
        ids_2 = [c.product_id for c in result_order_2.selected]
        assert ids_1 == ids_2
        assert ids_1 == ["alpha", "middle", "zeta"]  # all tied at 1.0 -> ascending product_id


class TestFallbackInsufficientCandidates:
    def test_two_candidates_falls_back_even_though_both_perfectly_correlated(self):
        candidates = [
            _identical_to_target_candidate(f"only-{i}", TARGET_PRE_INCREASING) for i in range(2)
        ]

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, candidates, T, "final", VOLUME_FLOOR
        )

        assert len(candidates) < MIN_CANDIDATES
        assert result.used_fallback is True
        assert result.fallback_reason == "insufficient_candidates"
        assert result.selected == ()
        assert result.mean_correlation is None
        # Fallback control series is the constant-1 plain pre/post series.
        sample_day = next(iter(result.control_daily))
        assert result.control_daily[sample_day].gmv == Decimal(1)


class TestFallbackLowMeanCorrelation:
    def test_three_anti_correlated_candidates_falls_back_on_quality_bar(self):
        days = sorted(TARGET_PRE_INCREASING)
        values = [TARGET_PRE_INCREASING[d].gmv for d in days]
        reversed_daily = {
            d: RawDailyRecord(gmv=v) for d, v in zip(days, reversed(values), strict=True)
        }
        candidates = [
            ControlCandidate(
                f"anti-{i}", dict(reversed_daily), touched=False, first_active_date=LONG_ACTIVE
            )
            for i in range(3)
        ]

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, candidates, T, "final", VOLUME_FLOOR
        )

        assert len(candidates) >= MIN_CANDIDATES  # this is NOT the insufficient-candidates case
        assert result.used_fallback is True
        assert result.fallback_reason == "low_mean_correlation"
        assert result.mean_correlation == pytest.approx(-1.0)
        assert result.selected == ()


class TestDegenerateInputsDoNotRaise:
    def test_constant_candidate_series_scores_zero_and_does_not_raise(self):
        strong = [
            _identical_to_target_candidate(f"strong-{i}", TARGET_PRE_INCREASING) for i in range(2)
        ]
        flat = ControlCandidate(
            "flat-sibling",
            _flat_gmv_series(PRE_START, PRE_END, Decimal(9)),
            touched=False,
            first_active_date=LONG_ACTIVE,
        )

        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, [*strong, flat], T, "final", VOLUME_FLOOR
        )

        by_id = {c.product_id: c.correlation for c in result.selected}
        assert by_id["flat-sibling"] == 0.0
        assert result.used_fallback is False  # mean (1+1+0)/3 = 0.667 >= 0.2

    def test_constant_target_series_scores_every_candidate_zero_and_falls_back(self):
        flat_target = _flat_gmv_series(PRE_START, PRE_END, Decimal(5))
        candidates = [
            _identical_to_target_candidate(f"sib-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]

        result = select_control_pool(GMV, flat_target, candidates, T, "final", VOLUME_FLOOR)

        assert result.used_fallback is True
        assert result.fallback_reason == "low_mean_correlation"
        assert result.mean_correlation == 0.0


class TestControlSetJsonAudit:
    def test_full_path_result_serializes_ids_correlations_and_windows(self):
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        result = select_control_pool(GMV, TARGET_PRE_INCREASING, clean, T, "final", VOLUME_FLOOR)

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

    def test_fallback_result_still_serializes_a_full_payload(self):
        candidates = [
            _identical_to_target_candidate(f"only-{i}", TARGET_PRE_INCREASING) for i in range(2)
        ]
        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, candidates, T, "final", VOLUME_FLOOR
        )

        payload = result.as_control_set_json()
        assert payload["control_ids"] == []
        assert payload["correlations"] == []
        assert payload["windows"]["pre_start"] == "2026-01-01"
        assert payload["used_fallback"] is True
        assert payload["fallback_reason"] == "insufficient_candidates"
        json.dumps(payload)


class TestDeterminismAcrossCalls:
    def test_repeated_calls_produce_identical_results(self):
        clean = [
            _identical_to_target_candidate(f"clean-{i}", TARGET_PRE_INCREASING) for i in range(3)
        ]
        first = select_control_pool(
            GMV, dict(TARGET_PRE_INCREASING), list(clean), T, "final", VOLUME_FLOOR
        )
        second = select_control_pool(
            GMV, dict(TARGET_PRE_INCREASING), list(clean), T, "final", VOLUME_FLOOR
        )
        assert first == second


class TestInterfaceContractWithReading:
    """Proves `ControlPoolResult.control_daily` plugs directly into #1041's
    `reading.compute_metric_reading` -- the exact shape
    `control_daily_by_metric[metric.key]` expects -- with no adapter."""

    def _target_daily(self) -> dict[date, RawDailyRecord]:
        pre = _split_gmv_series(PRE_START, PRE_END, Decimal(90), Decimal(110))  # mean 100
        post = _flat_gmv_series(POST_START_FINAL, POST_END_FINAL, Decimal(150))
        return {**pre, **post}

    def test_full_path_control_series_feeds_the_known_hand_computed_reading(self):
        target_daily = self._target_daily()

        def _sibling(product_id: str) -> ControlCandidate:
            pre = _split_gmv_series(PRE_START, PRE_END, Decimal(45), Decimal(55))  # mean 50
            post = _flat_gmv_series(POST_START_FINAL, POST_END_FINAL, Decimal(60))
            return ControlCandidate(
                product_id, {**pre, **post}, touched=False, first_active_date=LONG_ACTIVE
            )

        candidates = [_sibling(f"sib-{i}") for i in range(3)]
        result = select_control_pool(GMV, target_daily, candidates, T, "final", VOLUME_FLOOR)
        assert result.used_fallback is False
        assert all(c.correlation == pytest.approx(1.0) for c in result.selected)

        reading = compute_metric_reading(GMV, target_daily, result.control_daily, T, "final")

        # Same hand-computed scenario as test_impact_reading.py's
        # test_normal_reading_hand_computed: pre=100, post=150, control
        # pre=50, control post=60 -> growth=1.2, expected=120.0,
        # incremental=30.0, impact_pct=0.25.
        assert reading.status == "ok"
        assert reading.pre == Decimal(100)
        assert reading.post == Decimal(150)
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal("120.0")
        assert reading.incremental == Decimal("30.0")
        assert reading.impact_pct == Decimal("30.0") / Decimal("120.0")

    def test_fallback_control_series_reduces_the_formula_to_plain_pre_post(self):
        target_daily = self._target_daily()
        candidates = [
            _identical_to_target_candidate(f"only-{i}", TARGET_PRE_INCREASING) for i in range(2)
        ]  # only 2 -> fallback

        result = select_control_pool(GMV, target_daily, candidates, T, "final", VOLUME_FLOOR)
        assert result.used_fallback is True

        reading = compute_metric_reading(GMV, target_daily, result.control_daily, T, "final")

        assert reading.status == "ok"
        assert reading.pre == Decimal(100)
        assert reading.post == Decimal(150)
        assert reading.growth == Decimal(1)  # constant control series -> ratio collapses to 1
        assert reading.expected == reading.pre  # plain pre/post: expected == pre
        assert reading.incremental == reading.post - reading.pre  # == 50

    def test_fallback_control_series_yields_unit_growth_for_a_derived_metric_too(self):
        """The fallback series is a constant `1` across every raw column, so
        even a *derived* metric (gmv_per_order = gmv / sku_orders) that reads
        two fields from the same record collapses to a growth ratio of 1,
        not just the metrics with a single backing column."""
        candidates = [
            _identical_to_target_candidate(f"only-{i}", TARGET_PRE_INCREASING) for i in range(2)
        ]
        result = select_control_pool(
            GMV, TARGET_PRE_INCREASING, candidates, T, "final", VOLUME_FLOOR
        )
        assert result.used_fallback is True

        sample_day = next(iter(result.control_daily))
        record = result.control_daily[sample_day]
        assert GMV_PER_ORDER.extractor(record) == Decimal(1)


class TestPearsonExactValues:
    """Hand-derivable Pearson correlation boundary cases, independent of the
    selection logic above -- proves the formula itself, matching the style of
    compute.py's own hand-computed tests."""

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


class TestVolumeFloorIsComparedAgainstTheVolumeIndicator:
    """Regression: the floor is calibrated in counts, the metric may be a rate.

    Found by the W2-B review pass. `select_control_pool` compared a candidate's
    mean of the METRIC ITSELF against the floor. ADR-077 decision 4's floors are
    counts (">= 50 impressions/day", ">= 20 visitors/day"), and CTR /
    conversion_rate are fractions around 0.01-0.30 — so no candidate could ever
    clear them. Every CTR and conversion reading fell back to plain pre/post,
    permanently capped at Thap, for the Image and Description mutation families:
    half of decision 1's metric map, silently disabled in production.

    Nothing caught it because every test in the block — including all six files
    of the #1045 phase gate — drove only the GMV/PRICE family, where the metric
    happens to be a count and the comparison is coincidentally harmless.
    """

    @staticmethod
    def _rate_case(metric, field: str, base: float):
        t = date(2026, 4, 1)

        def series(offset: float) -> dict[date, RawDailyRecord]:
            return {
                t - timedelta(days=d): RawDailyRecord(
                    **{field: Decimal(str(round(base + offset + 0.001 * d, 6)))},
                    impressions=Decimal("900"),
                    visitors=Decimal("400"),
                    sku_orders=Decimal("12"),
                )
                for d in range(1, 15)
            }

        candidates = [
            ControlCandidate(
                product_id=f"p{i}",
                daily=series(0.001 * i),
                touched=False,
                first_active_date=t - timedelta(days=200),
            )
            for i in range(5)
        ]
        return t, series(0.0), candidates

    def test_ctr_candidates_survive_the_impressions_floor(self):
        t, target, candidates = self._rate_case(CTR, "ctr", 0.05)
        result = select_control_pool(
            CTR,
            target,
            candidates,
            t,
            "final",
            volume_floor_for(CTR),
            volume_of=volume_indicator_for(CTR),
        )
        assert result.used_fallback is False, (
            "CTR candidates with 900 impressions/day must clear the >=50 floor; "
            "comparing CTR's own ~0.05 values against 50 disqualifies everyone"
        )
        assert len(result.selected) == 5

    def test_conversion_candidates_survive_the_visitors_floor(self):
        t, target, candidates = self._rate_case(CONVERSION_RATE, "conversion_rate", 0.03)
        result = select_control_pool(
            CONVERSION_RATE,
            target,
            candidates,
            t,
            "final",
            volume_floor_for(CONVERSION_RATE),
            volume_of=volume_indicator_for(CONVERSION_RATE),
        )
        assert result.used_fallback is False
        assert len(result.selected) == 5

    def test_a_rate_metric_without_a_volume_indicator_raises_rather_than_silently_disqualifying(
        self,
    ):
        """Fail loudly, never silently. Silent disqualification is what made the
        original defect invisible for an entire wave."""
        t, target, candidates = self._rate_case(CTR, "ctr", 0.05)
        with pytest.raises(ValueError, match="is a rate"):
            select_control_pool(CTR, target, candidates, t, "final", volume_floor_for(CTR))

    def test_a_genuinely_low_volume_candidate_is_still_disqualified(self):
        """The fix must not disable the floor — only measure it in the right unit."""
        t = date(2026, 4, 1)

        def series(impressions: str) -> dict[date, RawDailyRecord]:
            return {
                t - timedelta(days=d): RawDailyRecord(
                    ctr=Decimal("0.05"),
                    impressions=Decimal(impressions),
                    visitors=Decimal("400"),
                    sku_orders=Decimal("12"),
                )
                for d in range(1, 15)
            }

        candidates = [
            ControlCandidate(
                product_id=f"low{i}",
                daily=series("9"),
                touched=False,
                first_active_date=t - timedelta(days=200),
            )
            for i in range(5)
        ]
        result = select_control_pool(
            CTR,
            series("900"),
            candidates,
            t,
            "final",
            volume_floor_for(CTR),
            volume_of=volume_indicator_for(CTR),
        )
        assert result.used_fallback is True
        assert result.fallback_reason == "insufficient_candidates"
