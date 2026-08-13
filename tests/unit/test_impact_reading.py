"""Per-metric / per-mutation / run-level readings (#1041).

Acceptance criteria covered here:
- Multi-mutation runs produce per-mutation readings plus a run-level rollup
  keyed on the ActionCard's `expected_impact.metric`.
- A second Juli run inside either window yields `confounded`.
- Day T excluded end-to-end (target AND control) at the reading level.
- Compute is pure and deterministic across repeated calls.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.impact.metric_map import GMV, MutationKind, RawDailyRecord
from juli_backend.services.impact.reading import (
    compute_metric_reading,
    compute_mutation_readings,
    compute_run_readings,
)

T = date(2026, 1, 15)


def _series(
    start: date,
    end: date,
    value_fn,
) -> dict[date, RawDailyRecord]:
    days = (end - start).days
    out: dict[date, RawDailyRecord] = {}
    d = start
    for _ in range(days + 1):
        out[d] = value_fn(d)
        d += timedelta(days=1)
    return out


def _constant_gmv_series(start: date, end: date, gmv: Decimal, orders: Decimal) -> dict:
    return _series(start, end, lambda _d: RawDailyRecord(gmv=gmv, sku_orders=orders))


def _full_target_and_control(
    *,
    target_pre_gmv: Decimal,
    target_post_gmv: Decimal,
    control_pre_gmv: Decimal,
    control_post_gmv: Decimal,
) -> tuple[dict, dict]:
    """Builds 34-day (T-14..T+14) target/control GMV series so both
    preliminary and final post windows are fully covered."""
    pre_start, pre_end = date(2026, 1, 1), date(2026, 1, 14)
    post_start, post_end = date(2026, 1, 16), date(2026, 1, 29)

    def build(pre_val: Decimal, post_val: Decimal) -> dict:
        merged = {}
        merged.update(_constant_gmv_series(pre_start, pre_end, pre_val, Decimal(1)))
        merged.update(_constant_gmv_series(post_start, post_end, post_val, Decimal(1)))
        return merged

    return build(target_pre_gmv, target_post_gmv), build(control_pre_gmv, control_post_gmv)


class TestComputeMetricReadingOk:
    def test_normal_reading_hand_computed(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        reading = compute_metric_reading(GMV, target, control, T, "final")
        assert reading.status == "ok"
        assert reading.pre == Decimal(100)
        assert reading.post == Decimal(150)
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal("120.0")
        assert reading.incremental == Decimal("30.0")
        assert reading.impact_pct == Decimal("30.0") / Decimal("120.0")
        assert reading.percent_suppressed_reason is None

    def test_extreme_t_value_in_both_target_and_control_does_not_move_the_reading(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        # T itself is excluded from every window; poison it in both series
        # with a value extreme enough to visibly move any mean it leaked
        # into, and confirm the reading is bit-for-bit identical.
        poisoned_target = dict(target)
        poisoned_control = dict(control)
        poisoned_target[T] = RawDailyRecord(gmv=Decimal(999_999_999), sku_orders=Decimal(1))
        poisoned_control[T] = RawDailyRecord(gmv=Decimal(999_999_999), sku_orders=Decimal(1))

        clean_reading = compute_metric_reading(GMV, target, control, T, "final")
        poisoned_reading = compute_metric_reading(
            GMV, poisoned_target, poisoned_control, T, "final"
        )

        assert poisoned_reading == clean_reading


class TestComputeMetricReadingConfounded:
    def test_confounded_reading_has_all_none_numeric_fields(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        reading = compute_metric_reading(GMV, target, control, T, "final", confounded=True)
        assert reading.status == "confounded"
        assert reading.pre is None
        assert reading.post is None
        assert reading.growth is None
        assert reading.expected is None
        assert reading.incremental is None
        assert reading.impact_pct is None
        assert reading.percent_suppressed_reason is None

    def test_confounded_does_not_raise_even_with_empty_series(self):
        reading = compute_metric_reading(GMV, {}, {}, T, "preliminary", confounded=True)
        assert reading.status == "confounded"


class TestComputeMutationReadings:
    def test_price_mutation_produces_gmv_primary_and_two_secondaries(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        control_by_metric = {"gmv": control, "sku_orders": control, "gmv_per_order": control}
        result = compute_mutation_readings(
            MutationKind.PRICE, target, control_by_metric, T, "final"
        )
        assert result.mutation is MutationKind.PRICE
        assert result.primary.metric == "gmv"
        assert {r.metric for r in result.secondary} == {"sku_orders", "gmv_per_order"}
        assert result.all_readings() == (result.primary, *result.secondary)


class TestComputeRunReadings:
    def test_single_mutation_run_rollup_matches_primary(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        control_by_metric = {"gmv": control, "sku_orders": control, "gmv_per_order": control}
        result = compute_run_readings(
            mutations=[MutationKind.PRICE],
            rollup_metric="gmv",
            target_daily=target,
            control_daily_by_metric=control_by_metric,
            t=T,
            kind="final",
        )
        assert len(result.per_mutation) == 1
        assert result.rollup.metric == "gmv"
        assert result.rollup == result.per_mutation[0].primary

    def test_multi_mutation_run_produces_per_mutation_readings_plus_one_rollup(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        control_by_metric = {
            key: control
            for key in (
                "impressions",
                "ctr",
                "conversion_rate",
                "items_sold",
                "gmv",
                "sku_orders",
                "gmv_per_order",
            )
        }
        result = compute_run_readings(
            mutations=[MutationKind.SEO_KEYWORDS_TITLE, MutationKind.PRICE],
            rollup_metric="gmv",
            target_daily=target,
            control_daily_by_metric=control_by_metric,
            t=T,
            kind="preliminary",
        )
        assert len(result.per_mutation) == 2
        mutations_seen = {mr.mutation for mr in result.per_mutation}
        assert mutations_seen == {MutationKind.SEO_KEYWORDS_TITLE, MutationKind.PRICE}
        # Rollup is a distinct, single extra reading keyed on the ActionCard
        # metric — not folded into the per-mutation list.
        assert result.rollup.metric == "gmv"
        assert result.rollup.kind == "preliminary"

    def test_empty_mutations_raises_value_error(self):
        with pytest.raises(ValueError, match="at least one mutation"):
            compute_run_readings(
                mutations=[],
                rollup_metric="gmv",
                target_daily={},
                control_daily_by_metric={},
                t=T,
                kind="final",
            )

    def test_unknown_rollup_metric_raises_key_error(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        control_by_metric = {"gmv": control, "sku_orders": control, "gmv_per_order": control}
        with pytest.raises(KeyError, match="not_a_real_metric"):
            compute_run_readings(
                mutations=[MutationKind.PRICE],
                rollup_metric="not_a_real_metric",
                target_daily=target,
                control_daily_by_metric=control_by_metric,
                t=T,
                kind="final",
            )

    def test_confounded_flag_propagates_to_every_reading_in_the_run(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        control_by_metric = {"gmv": control, "sku_orders": control, "gmv_per_order": control}
        result = compute_run_readings(
            mutations=[MutationKind.PRICE],
            rollup_metric="gmv",
            target_daily=target,
            control_daily_by_metric=control_by_metric,
            t=T,
            kind="final",
            confounded=True,
        )
        assert result.rollup.status == "confounded"
        for mutation_readings in result.per_mutation:
            for r in mutation_readings.all_readings():
                assert r.status == "confounded"
                assert r.pre is None


class TestDeterminismAcrossCalls:
    def test_repeated_calls_produce_identical_readings(self):
        target, control = _full_target_and_control(
            target_pre_gmv=Decimal(100),
            target_post_gmv=Decimal(150),
            control_pre_gmv=Decimal(50),
            control_post_gmv=Decimal(60),
        )
        first = compute_metric_reading(GMV, dict(target), dict(control), T, "final")
        second = compute_metric_reading(GMV, dict(target), dict(control), T, "final")
        assert first == second
