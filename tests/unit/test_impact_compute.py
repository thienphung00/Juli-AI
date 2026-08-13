"""The ratio-form DiD formula steps — ADR-077 decision 2 (#1041).

Acceptance criteria covered here:
- Each formula step is independently unit-tested against hand-computed
  values, not just the end-to-end number.
- Day T is excluded from `pre` and `post` (windows.py owns the mechanism;
  this file asserts compute.py's steps inherit it).
- `pre = 0` and `expected <= 0` both suppress the `%` form without raising —
  asserted separately, as distinct inputs reaching the same designed state.
- Compute is pure and deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.impact.compute import (
    compute_expected,
    compute_growth,
    compute_impact_pct,
    compute_incremental,
    compute_post,
    compute_pre,
)

T = date(2026, 1, 15)


def _daily(start: date, values: list[Decimal]) -> dict[date, Decimal | None]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


class TestComputePre:
    def test_hand_computed_mean_over_fourteen_days(self):
        # Values 10, 20, ..., 140 across T-14 .. T-1. Sum = 1050, mean = 75.
        pre_start = date(2026, 1, 1)
        daily = _daily(pre_start, [Decimal((i + 1) * 10) for i in range(14)])
        assert compute_pre(daily, T) == Decimal(75)

    def test_extreme_value_at_t_does_not_move_pre(self):
        pre_start = date(2026, 1, 1)
        daily = _daily(pre_start, [Decimal(100) for _ in range(14)])
        daily[T] = Decimal(999_999)  # T itself carries an extreme value
        assert compute_pre(daily, T) == Decimal(100)

    def test_missing_pre_data_returns_none_not_exception(self):
        assert compute_pre({}, T) is None


class TestComputePost:
    def test_preliminary_hand_computed_mean_over_seven_days(self):
        post_start = date(2026, 1, 16)
        # Values 100..160 step 10. Sum = 700+... let's hand-verify: 100,110,120,130,140,150,160
        values = [Decimal(100 + 10 * i) for i in range(7)]
        daily = _daily(post_start, values)
        assert sum(values) == Decimal(910)
        assert compute_post(daily, T, "preliminary") == Decimal(910) / Decimal(7)

    def test_final_hand_computed_mean_over_fourteen_days(self):
        post_start = date(2026, 1, 16)
        values = [Decimal(200) for _ in range(14)]
        daily = _daily(post_start, values)
        assert compute_post(daily, T, "final") == Decimal(200)

    def test_extreme_value_at_t_does_not_move_post(self):
        post_start = date(2026, 1, 16)
        daily = _daily(post_start, [Decimal(50) for _ in range(14)])
        daily[T] = Decimal(999_999)
        assert compute_post(daily, T, "final") == Decimal(50)

    def test_missing_post_data_returns_none_not_exception(self):
        assert compute_post({}, T, "preliminary") is None


class TestComputeGrowth:
    def test_hand_computed_ratio(self):
        assert compute_growth(Decimal(50), Decimal(65)) == Decimal("1.3")

    def test_control_pre_zero_is_none_not_zero_division_error(self):
        assert compute_growth(Decimal(0), Decimal(65)) is None

    def test_control_pre_none_is_none(self):
        assert compute_growth(None, Decimal(65)) is None

    def test_control_post_none_is_none(self):
        assert compute_growth(Decimal(50), None) is None

    def test_control_post_zero_gives_zero_growth_not_none(self):
        # Zero control-post is a legitimate (if extreme) growth of 0, not a
        # missing-data case — only control_pre == 0 is undefined (÷0).
        assert compute_growth(Decimal(50), Decimal(0)) == Decimal(0)


class TestComputeExpected:
    def test_hand_computed_product(self):
        assert compute_expected(Decimal(75), Decimal("1.3")) == Decimal("97.5")

    def test_pre_none_is_none(self):
        assert compute_expected(None, Decimal("1.3")) is None

    def test_growth_none_is_none(self):
        assert compute_expected(Decimal(75), None) is None


class TestComputeIncremental:
    def test_hand_computed_difference(self):
        assert compute_incremental(Decimal(120), Decimal("97.5")) == Decimal("22.5")

    def test_negative_incremental_is_allowed(self):
        assert compute_incremental(Decimal(80), Decimal(100)) == Decimal(-20)

    def test_post_none_is_none(self):
        assert compute_incremental(None, Decimal(100)) is None

    def test_expected_none_is_none(self):
        assert compute_incremental(Decimal(100), None) is None


class TestComputeImpactPct:
    def test_hand_computed_normal_case(self):
        pct, reason = compute_impact_pct(
            pre=Decimal(50), incremental=Decimal(25), expected=Decimal(100)
        )
        assert pct == Decimal("0.25")
        assert reason is None

    def test_negative_impact_computed_the_same_way_as_positive(self):
        pct, reason = compute_impact_pct(
            pre=Decimal(50), incremental=Decimal(-25), expected=Decimal(100)
        )
        assert pct == Decimal("-0.25")
        assert reason is None

    def test_pre_zero_suppresses_percent_without_raising(self):
        # pre = 0 forces expected = pre * growth = 0 too, but the reason must
        # be reported as "pre_zero" specifically (the more specific, upstream
        # cause), not "expected_non_positive".
        pct, reason = compute_impact_pct(
            pre=Decimal(0), incremental=Decimal(0), expected=Decimal(0)
        )
        assert pct is None
        assert reason == "pre_zero"

    def test_expected_non_positive_with_pre_strictly_positive_suppresses_percent(self):
        # A distinct input from the pre=0 case: pre is nonzero, but growth
        # (and therefore expected) is zero or negative — e.g. the control
        # cohort collapsed to zero in the post window.
        pct, reason = compute_impact_pct(
            pre=Decimal(50), incremental=Decimal(30), expected=Decimal(0)
        )
        assert pct is None
        assert reason == "expected_non_positive"

    def test_expected_strictly_negative_also_suppresses_percent(self):
        pct, reason = compute_impact_pct(
            pre=Decimal(50), incremental=Decimal(30), expected=Decimal(-10)
        )
        assert pct is None
        assert reason == "expected_non_positive"

    def test_insufficient_data_when_any_input_missing(self):
        assert compute_impact_pct(None, Decimal(1), Decimal(1)) == (None, "insufficient_data")
        assert compute_impact_pct(Decimal(1), None, Decimal(1)) == (None, "insufficient_data")
        assert compute_impact_pct(Decimal(1), Decimal(1), None) == (None, "insufficient_data")

    def test_no_exception_raised_for_any_suppression_path(self):
        # All five suppression-relevant calls above must not raise; this
        # test exists as an explicit "did not raise" guard independent of
        # the return-value assertions.
        compute_impact_pct(Decimal(0), Decimal(0), Decimal(0))
        compute_impact_pct(Decimal(50), Decimal(30), Decimal(0))
        compute_impact_pct(None, None, None)


class TestDeterminism:
    def test_same_inputs_produce_same_outputs_repeatedly(self):
        pre_start = date(2026, 1, 1)
        daily = _daily(pre_start, [Decimal((i + 1) * 10) for i in range(14)])
        results = {compute_pre(dict(daily), T) for _ in range(5)}
        assert len(results) == 1
