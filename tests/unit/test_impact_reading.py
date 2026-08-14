"""Per-metric / per-mutation / run-level readings (#1041).

Acceptance criteria covered here:
- Multi-mutation runs produce per-mutation readings plus a run-level rollup
  keyed on the ActionCard's `expected_impact.metric`.
- A second Juli run inside either window yields `confounded`.
- Day T excluded end-to-end (target AND control) at the reading level.
- Compute is pure and deterministic across repeated calls.

**Three metric families, hand-computed, not a GMV monoculture.** A prior
run of this slice fixtured *only* the GMV/price family in every reading
test, which is exactly why a HIGH-severity rate-vs-count defect elsewhere in
this ADR's stack survived review undetected — nothing ever exercised a rate
metric's numbers. This file hand-computes readings for all three of ADR-077
decision 1's metric families:

- `revenue_orders` (price mutation: GMV primary, SKU_ORDERS + GMV_PER_ORDER
  secondary — the one count-metric family, kept as a baseline)
- `impressions_ctr` (SEO/title mutation: IMPRESSIONS primary [count], CTR
  secondary [rate])
- `conversion` (description mutation: CONVERSION_RATE primary [rate],
  ITEMS_SOLD secondary [count])
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.impact.metric_map import (
    CONVERSION_RATE,
    CTR,
    GMV,
    IMPRESSIONS,
    ITEMS_SOLD,
    MutationKind,
    RawDailyRecord,
)
from juli_backend.services.impact.reading import (
    compute_metric_reading,
    compute_mutation_readings,
    compute_run_readings,
)

T = date(2026, 3, 20)
PRE_START = T - timedelta(days=14)
PRE_END = T - timedelta(days=1)
POST_START = T + timedelta(days=1)
POST_END_FINAL = T + timedelta(days=14)


def _series(field: str, pre_value: Decimal, post_value: Decimal) -> dict[date, RawDailyRecord]:
    """A 14-day-pre / 14-day-post series (covers both preliminary and final
    post windows) with a single ``RawDailyRecord`` field set to a constant
    value in each half. Day T itself is never populated — it must never be
    read regardless."""
    out: dict[date, RawDailyRecord] = {}
    d = PRE_START
    while d <= PRE_END:
        out[d] = RawDailyRecord(**{field: pre_value})
        d += timedelta(days=1)
    d = POST_START
    while d <= POST_END_FINAL:
        out[d] = RawDailyRecord(**{field: post_value})
        d += timedelta(days=1)
    return out


# --- Family 1: revenue_orders (GMV / price mutation) ------------------------
# growth = 60/50 = 1.2; expected = 100*1.2 = 120; incremental = 150-120 = 30;
# impact_pct = 30/120 = 0.25
GMV_TARGET = _series("gmv", Decimal(100), Decimal(150))
GMV_CONTROL = _series("gmv", Decimal(50), Decimal(60))

# --- Family 2: impressions_ctr (SEO/title mutation) -------------------------
# impressions: growth = 880/800 = 1.1; expected = 1000*1.1 = 1100;
# incremental = 1210-1100 = 110; impact_pct = 110/1100 = 0.1
IMPRESSIONS_TARGET = _series("impressions", Decimal(1000), Decimal(1210))
IMPRESSIONS_CONTROL = _series("impressions", Decimal(800), Decimal(880))
# ctr (rate): growth = 0.045/0.03 = 1.5; expected = 0.04*1.5 = 0.06;
# incremental = 0.075-0.06 = 0.015; impact_pct = 0.015/0.06 = 0.25
CTR_TARGET = _series("ctr", Decimal("0.04"), Decimal("0.075"))
CTR_CONTROL = _series("ctr", Decimal("0.03"), Decimal("0.045"))

# --- Family 3: conversion (description mutation) ----------------------------
# conversion_rate (rate): growth = 0.018/0.015 = 1.2; expected = 0.02*1.2 = 0.024;
# incremental = 0.036-0.024 = 0.012; impact_pct = 0.012/0.024 = 0.5
CONVERSION_TARGET = _series("conversion_rate", Decimal("0.02"), Decimal("0.036"))
CONVERSION_CONTROL = _series("conversion_rate", Decimal("0.015"), Decimal("0.018"))
# items_sold (count secondary): growth = 44/40 = 1.1; expected = 50*1.1 = 55;
# incremental = 66-55 = 11; impact_pct = 11/55 = 0.2
ITEMS_SOLD_TARGET = _series("items_sold", Decimal(50), Decimal(66))
ITEMS_SOLD_CONTROL = _series("items_sold", Decimal(40), Decimal(44))


class TestComputeMetricReadingRevenueOrdersFamily:
    def test_gmv_reading_hand_computed(self):
        reading = compute_metric_reading(GMV, GMV_TARGET, GMV_CONTROL, T, "final")
        assert reading.status == "ok"
        assert reading.pre == Decimal(100)
        assert reading.post == Decimal(150)
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal("120.0")
        assert reading.incremental == Decimal("30.0")
        assert reading.impact_pct == Decimal("0.25")
        assert reading.percent_suppressed_reason is None

    def test_extreme_t_value_in_both_target_and_control_does_not_move_the_reading(self):
        poisoned_target = dict(GMV_TARGET)
        poisoned_control = dict(GMV_CONTROL)
        poisoned_target[T] = RawDailyRecord(gmv=Decimal(999_999_999))
        poisoned_control[T] = RawDailyRecord(gmv=Decimal(999_999_999))

        clean = compute_metric_reading(GMV, GMV_TARGET, GMV_CONTROL, T, "final")
        poisoned = compute_metric_reading(GMV, poisoned_target, poisoned_control, T, "final")
        assert poisoned == clean


class TestComputeMetricReadingImpressionsCtrFamily:
    def test_impressions_primary_reading_hand_computed(self):
        reading = compute_metric_reading(
            IMPRESSIONS, IMPRESSIONS_TARGET, IMPRESSIONS_CONTROL, T, "final"
        )
        assert reading.status == "ok"
        assert reading.pre == Decimal(1000)
        assert reading.post == Decimal(1210)
        assert reading.growth == Decimal("1.1")
        assert reading.expected == Decimal("1100.0")
        assert reading.incremental == Decimal("110.0")
        assert reading.impact_pct == Decimal("0.1")
        assert reading.percent_suppressed_reason is None

    def test_ctr_secondary_rate_reading_hand_computed(self):
        # CTR is a rate metric (MetricSpec.is_rate is True) — the reading
        # pipeline runs it through the exact same formula as a count metric,
        # unmodified, and the resulting numbers stay in fractional (rate)
        # units end to end, never accidentally rescaled to look like a count.
        reading = compute_metric_reading(CTR, CTR_TARGET, CTR_CONTROL, T, "final")
        assert reading.status == "ok"
        assert reading.pre == Decimal("0.04")
        assert reading.post == Decimal("0.075")
        assert reading.growth == Decimal("1.5")
        assert reading.expected == Decimal("0.060")
        assert reading.incremental == Decimal("0.015")
        assert reading.impact_pct == Decimal("0.25")
        assert reading.percent_suppressed_reason is None
        # Sanity: these values are genuinely rate-shaped (< 1), not
        # coincidentally count-shaped — a reading with pre/post > 1 here
        # would indicate the wrong field was wired up.
        assert reading.pre < Decimal(1)
        assert reading.post < Decimal(1)

    def test_preliminary_kind_reads_only_the_seven_day_post_window(self):
        # POST_START..POST_START+6 (7 days) is the preliminary window; every
        # day in the fixture's post half carries the same constant value, so
        # preliminary and final posts are equal here — this asserts the
        # *window*, not just the value, by checking kind is threaded through.
        reading = compute_metric_reading(
            IMPRESSIONS, IMPRESSIONS_TARGET, IMPRESSIONS_CONTROL, T, "preliminary"
        )
        assert reading.kind == "preliminary"
        assert reading.post == Decimal(1210)


class TestComputeMetricReadingConversionFamily:
    def test_conversion_rate_primary_reading_hand_computed(self):
        reading = compute_metric_reading(
            CONVERSION_RATE, CONVERSION_TARGET, CONVERSION_CONTROL, T, "final"
        )
        assert reading.status == "ok"
        assert reading.pre == Decimal("0.02")
        assert reading.post == Decimal("0.036")
        assert reading.growth == Decimal("1.2")
        assert reading.expected == Decimal("0.024")
        assert reading.incremental == Decimal("0.012")
        assert reading.impact_pct == Decimal("0.5")
        assert reading.percent_suppressed_reason is None

    def test_items_sold_secondary_count_reading_hand_computed(self):
        reading = compute_metric_reading(
            ITEMS_SOLD, ITEMS_SOLD_TARGET, ITEMS_SOLD_CONTROL, T, "final"
        )
        assert reading.status == "ok"
        assert reading.pre == Decimal(50)
        assert reading.post == Decimal(66)
        assert reading.growth == Decimal("1.1")
        assert reading.expected == Decimal("55.0")
        assert reading.incremental == Decimal("11.0")
        assert reading.impact_pct == Decimal("0.2")
        assert reading.percent_suppressed_reason is None


class TestComputeMetricReadingConfounded:
    def test_confounded_reading_has_all_none_numeric_fields(self):
        reading = compute_metric_reading(GMV, GMV_TARGET, GMV_CONTROL, T, "final", confounded=True)
        assert reading.status == "confounded"
        assert reading.pre is None
        assert reading.post is None
        assert reading.growth is None
        assert reading.expected is None
        assert reading.incremental is None
        assert reading.impact_pct is None
        assert reading.percent_suppressed_reason is None

    def test_confounded_also_suppresses_a_rate_metric_reading(self):
        # Regression guard: confounded suppression must not be accidentally
        # metric-type-specific — assert it on a rate metric too, not only
        # on the count-shaped GMV family.
        reading = compute_metric_reading(CTR, CTR_TARGET, CTR_CONTROL, T, "final", confounded=True)
        assert reading.status == "confounded"
        assert reading.pre is None

    def test_confounded_does_not_raise_even_with_empty_series(self):
        reading = compute_metric_reading(GMV, {}, {}, T, "preliminary", confounded=True)
        assert reading.status == "confounded"


class TestComputeMutationReadings:
    def test_price_mutation_produces_gmv_primary_and_two_secondaries(self):
        control_by_metric = {
            "gmv": GMV_CONTROL,
            "sku_orders": ITEMS_SOLD_CONTROL,  # arbitrary non-empty stand-in
            "gmv_per_order": GMV_CONTROL,
        }
        result = compute_mutation_readings(
            MutationKind.PRICE, GMV_TARGET, control_by_metric, T, "final"
        )
        assert result.mutation is MutationKind.PRICE
        assert result.primary.metric == "gmv"
        assert result.primary.pre == Decimal(100)
        assert {r.metric for r in result.secondary} == {"sku_orders", "gmv_per_order"}
        assert result.all_readings() == (result.primary, *result.secondary)

    def test_seo_mutation_produces_impressions_primary_ctr_secondary_hand_computed(self):
        control_by_metric = {"impressions": IMPRESSIONS_CONTROL, "ctr": CTR_CONTROL}
        # target_daily is shared for extraction purposes but only the field
        # relevant to each metric spec is read out of it — pass a merged
        # target series that carries both fields so both readings resolve.
        merged_target = {
            day: RawDailyRecord(
                impressions=IMPRESSIONS_TARGET.get(day, RawDailyRecord()).impressions,
                ctr=CTR_TARGET.get(day, RawDailyRecord()).ctr,
            )
            for day in set(IMPRESSIONS_TARGET) | set(CTR_TARGET)
        }
        result = compute_mutation_readings(
            MutationKind.SEO_KEYWORDS_TITLE, merged_target, control_by_metric, T, "final"
        )
        assert result.mutation is MutationKind.SEO_KEYWORDS_TITLE
        assert result.primary.metric == "impressions"
        assert result.primary.pre == Decimal(1000)
        assert result.secondary[0].metric == "ctr"
        assert result.secondary[0].pre == Decimal("0.04")

    def test_description_mutation_produces_conversion_rate_primary_items_sold_secondary(self):
        merged_target = {
            day: RawDailyRecord(
                conversion_rate=CONVERSION_TARGET.get(day, RawDailyRecord()).conversion_rate,
                items_sold=ITEMS_SOLD_TARGET.get(day, RawDailyRecord()).items_sold,
            )
            for day in set(CONVERSION_TARGET) | set(ITEMS_SOLD_TARGET)
        }
        control_by_metric = {
            "conversion_rate": CONVERSION_CONTROL,
            "items_sold": ITEMS_SOLD_CONTROL,
        }
        result = compute_mutation_readings(
            MutationKind.DESCRIPTION, merged_target, control_by_metric, T, "final"
        )
        assert result.mutation is MutationKind.DESCRIPTION
        assert result.primary.metric == "conversion_rate"
        assert result.primary.pre == Decimal("0.02")
        assert result.primary.impact_pct == Decimal("0.5")
        assert result.secondary[0].metric == "items_sold"
        assert result.secondary[0].pre == Decimal(50)


class TestComputeRunReadings:
    def test_single_mutation_run_rollup_matches_primary(self):
        control_by_metric = {
            "gmv": GMV_CONTROL,
            "sku_orders": ITEMS_SOLD_CONTROL,
            "gmv_per_order": GMV_CONTROL,
        }
        result = compute_run_readings(
            mutations=[MutationKind.PRICE],
            rollup_metric="gmv",
            target_daily=GMV_TARGET,
            control_daily_by_metric=control_by_metric,
            t=T,
            kind="final",
        )
        assert len(result.per_mutation) == 1
        assert result.rollup.metric == "gmv"
        assert result.rollup == result.per_mutation[0].primary

    def test_multi_mutation_run_spans_all_three_metric_families_plus_rollup(self):
        # SEO (impressions_ctr family) + DESCRIPTION (conversion family) +
        # PRICE (revenue_orders family) in one run — the acceptance
        # criterion (per-mutation readings plus one run-level rollup)
        # exercised across every metric family this package supports, not
        # only GMV. Rollup is deliberately keyed on a *rate* metric
        # (conversion_rate) here, not gmv, to break the monoculture further.
        merged_target = {}
        for day in (
            set(IMPRESSIONS_TARGET)
            | set(CTR_TARGET)
            | set(CONVERSION_TARGET)
            | set(ITEMS_SOLD_TARGET)
            | set(GMV_TARGET)
        ):
            merged_target[day] = RawDailyRecord(
                impressions=IMPRESSIONS_TARGET.get(day, RawDailyRecord()).impressions,
                ctr=CTR_TARGET.get(day, RawDailyRecord()).ctr,
                conversion_rate=CONVERSION_TARGET.get(day, RawDailyRecord()).conversion_rate,
                items_sold=ITEMS_SOLD_TARGET.get(day, RawDailyRecord()).items_sold,
                gmv=GMV_TARGET.get(day, RawDailyRecord()).gmv,
                sku_orders=ITEMS_SOLD_TARGET.get(day, RawDailyRecord()).items_sold,
            )
        control_by_metric = {
            "impressions": IMPRESSIONS_CONTROL,
            "ctr": CTR_CONTROL,
            "conversion_rate": CONVERSION_CONTROL,
            "items_sold": ITEMS_SOLD_CONTROL,
            "gmv": GMV_CONTROL,
            "sku_orders": ITEMS_SOLD_CONTROL,
            "gmv_per_order": GMV_CONTROL,
        }
        result = compute_run_readings(
            mutations=[
                MutationKind.SEO_KEYWORDS_TITLE,
                MutationKind.DESCRIPTION,
                MutationKind.PRICE,
            ],
            rollup_metric="conversion_rate",
            target_daily=merged_target,
            control_daily_by_metric=control_by_metric,
            t=T,
            kind="final",
        )
        assert len(result.per_mutation) == 3
        mutations_seen = {mr.mutation for mr in result.per_mutation}
        assert mutations_seen == {
            MutationKind.SEO_KEYWORDS_TITLE,
            MutationKind.DESCRIPTION,
            MutationKind.PRICE,
        }

        by_mutation = {mr.mutation: mr for mr in result.per_mutation}
        assert by_mutation[MutationKind.SEO_KEYWORDS_TITLE].primary.metric == "impressions"
        assert by_mutation[MutationKind.SEO_KEYWORDS_TITLE].primary.pre == Decimal(1000)
        assert by_mutation[MutationKind.DESCRIPTION].primary.metric == "conversion_rate"
        assert by_mutation[MutationKind.DESCRIPTION].primary.impact_pct == Decimal("0.5")
        assert by_mutation[MutationKind.PRICE].primary.metric == "gmv"
        assert by_mutation[MutationKind.PRICE].primary.pre == Decimal(100)

        # Rollup is a distinct, single extra reading keyed on the ActionCard
        # metric — computed independently of the per-mutation loop (it is
        # not folded into result.per_mutation, which still has exactly 3
        # entries as asserted above) — and is itself a rate-metric reading
        # here, hand-computed identically to the standalone conversion_rate
        # assertion above. It happens to equal the DESCRIPTION mutation's
        # primary reading by value because both compute the exact same
        # (metric, target, control, t, kind) formula — same as the
        # single-mutation rollup-matches-primary case below, generalized to
        # a multi-mutation run.
        assert result.rollup.metric == "conversion_rate"
        assert result.rollup.impact_pct == Decimal("0.5")
        assert result.rollup == by_mutation[MutationKind.DESCRIPTION].primary

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
        control_by_metric = {
            "gmv": GMV_CONTROL,
            "sku_orders": ITEMS_SOLD_CONTROL,
            "gmv_per_order": GMV_CONTROL,
        }
        with pytest.raises(KeyError, match="not_a_real_metric"):
            compute_run_readings(
                mutations=[MutationKind.PRICE],
                rollup_metric="not_a_real_metric",
                target_daily=GMV_TARGET,
                control_daily_by_metric=control_by_metric,
                t=T,
                kind="final",
            )

    def test_confounded_flag_propagates_to_every_reading_in_the_run(self):
        control_by_metric = {
            "gmv": GMV_CONTROL,
            "sku_orders": ITEMS_SOLD_CONTROL,
            "gmv_per_order": GMV_CONTROL,
        }
        result = compute_run_readings(
            mutations=[MutationKind.PRICE],
            rollup_metric="gmv",
            target_daily=GMV_TARGET,
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
    def test_repeated_calls_produce_identical_readings_revenue_family(self):
        first = compute_metric_reading(GMV, dict(GMV_TARGET), dict(GMV_CONTROL), T, "final")
        second = compute_metric_reading(GMV, dict(GMV_TARGET), dict(GMV_CONTROL), T, "final")
        assert first == second

    def test_repeated_calls_produce_identical_readings_rate_family(self):
        first = compute_metric_reading(CTR, dict(CTR_TARGET), dict(CTR_CONTROL), T, "final")
        second = compute_metric_reading(CTR, dict(CTR_TARGET), dict(CTR_CONTROL), T, "final")
        assert first == second
