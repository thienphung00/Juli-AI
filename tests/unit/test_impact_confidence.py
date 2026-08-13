"""Confidence tiers, per-metric volume floors, and suppression (ADR-077
decision 4, #1043).

Acceptance criteria covered here:
- Floors live in config, keyed per metric family, and are read (never
  duplicated inline) at every use site (``volume_floor_for``).
- Below-floor produces its own designed outcome (``"below_floor"``),
  distinct from ``"suppressed"`` and ``"confounded"`` — asserted separately.
- All three tiers reachable, including the exact boundary conditions
  (``= floor``, ``= 3x floor``, ``= 1x band``, ``= 2x band``).
- The noise band is the pre-period stddev of the daily treated-vs-expected
  gap, asserted against a hand-computed fixture (not merely re-derived via
  the same stdlib call the implementation uses).
- A fallback-path reading can never be awarded "cao" — asserted directly,
  both at the pure ``assign_confidence`` boundary and through the composed
  ``compute_confidence`` pipeline fed a *real* ``select_control_pool``
  fallback result (#1042), not a hand-set boolean.

Every date in this file is derived from the single fixed reference point
``T = date(2026, 1, 15)`` — no ``datetime.now()``/``date.today()`` anywhere,
so nothing here can age out of a window overnight (see #1032).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.impact.confidence import (
    VOLUME_FLOORS,
    ConfidenceResult,
    MetricFamily,
    assign_confidence,
    compute_confidence,
    compute_noise_band,
    metric_family_of,
    pre_period_volume,
    volume_floor_for,
)
from juli_backend.services.impact.control_pool import ControlCandidate, select_control_pool
from juli_backend.services.impact.metric_map import (
    CONVERSION_RATE,
    CTR,
    GMV,
    GMV_PER_ORDER,
    IMPRESSIONS,
    ITEMS_SOLD,
    SKU_ORDERS,
    RawDailyRecord,
)
from juli_backend.services.impact.reading import compute_metric_reading

T = date(2026, 1, 15)
PRE_START, PRE_END = date(2026, 1, 1), date(2026, 1, 14)  # T-14 .. T-1
LONG_ACTIVE = T - timedelta(days=30)


# ---------------------------------------------------------------------------
# Floors config — keyed per metric family, read not duplicated
# ---------------------------------------------------------------------------


class TestVolumeFloorsConfig:
    def test_revenue_orders_family_floor_is_one_order_per_day(self):
        assert VOLUME_FLOORS[MetricFamily.REVENUE_ORDERS] == Decimal(1)

    def test_impressions_ctr_family_floor_is_fifty_per_day(self):
        assert VOLUME_FLOORS[MetricFamily.IMPRESSIONS_CTR] == Decimal(50)

    def test_conversion_family_floor_is_twenty_per_day(self):
        assert VOLUME_FLOORS[MetricFamily.CONVERSION] == Decimal(20)

    @pytest.mark.parametrize(
        "metric,expected_family",
        [
            (GMV, MetricFamily.REVENUE_ORDERS),
            (SKU_ORDERS, MetricFamily.REVENUE_ORDERS),
            (ITEMS_SOLD, MetricFamily.REVENUE_ORDERS),
            (GMV_PER_ORDER, MetricFamily.REVENUE_ORDERS),
            (IMPRESSIONS, MetricFamily.IMPRESSIONS_CTR),
            (CTR, MetricFamily.IMPRESSIONS_CTR),
            (CONVERSION_RATE, MetricFamily.CONVERSION),
        ],
    )
    def test_every_metric_is_mapped_to_its_family(self, metric, expected_family):
        assert metric_family_of(metric) is expected_family

    @pytest.mark.parametrize(
        "metric,expected_floor",
        [
            (GMV, Decimal(1)),
            (SKU_ORDERS, Decimal(1)),
            (ITEMS_SOLD, Decimal(1)),
            (GMV_PER_ORDER, Decimal(1)),
            (IMPRESSIONS, Decimal(50)),
            (CTR, Decimal(50)),
            (CONVERSION_RATE, Decimal(20)),
        ],
    )
    def test_volume_floor_for_resolves_through_config_not_a_literal(self, metric, expected_floor):
        assert volume_floor_for(metric) == expected_floor


# ---------------------------------------------------------------------------
# Pre-period volume — the correct underlying indicator per family
# ---------------------------------------------------------------------------


class TestPrePeriodVolume:
    def test_revenue_orders_family_uses_sku_orders_not_the_metrics_own_currency_value(self):
        # GMV is a currency metric; the "1 order/day" floor is a count, so the
        # volume signal behind a GMV reading must be the order count, not GMV
        # itself.
        daily = {
            PRE_START: RawDailyRecord(gmv=Decimal(500), sku_orders=Decimal(2)),
            PRE_START + timedelta(days=1): RawDailyRecord(gmv=Decimal(500), sku_orders=Decimal(4)),
        }
        assert pre_period_volume(daily, GMV, T) == Decimal(3)

    def test_impressions_ctr_family_uses_impressions(self):
        daily = {
            PRE_START: RawDailyRecord(ctr=Decimal("0.05"), impressions=Decimal(100)),
            PRE_START + timedelta(days=1): RawDailyRecord(
                ctr=Decimal("0.07"), impressions=Decimal(200)
            ),
        }
        assert pre_period_volume(daily, CTR, T) == Decimal(150)

    def test_conversion_family_uses_impressions_as_the_documented_visitors_proxy(self):
        daily = {
            PRE_START: RawDailyRecord(conversion_rate=Decimal("0.1"), impressions=Decimal(30)),
            PRE_START + timedelta(days=1): RawDailyRecord(
                conversion_rate=Decimal("0.2"), impressions=Decimal(10)
            ),
        }
        assert pre_period_volume(daily, CONVERSION_RATE, T) == Decimal(20)

    def test_missing_days_are_skipped_not_zero_filled(self):
        daily = {PRE_START: RawDailyRecord(sku_orders=Decimal(10))}
        assert pre_period_volume(daily, GMV, T) == Decimal(10)

    def test_no_data_at_all_is_none(self):
        assert pre_period_volume({}, GMV, T) is None

    def test_day_t_itself_is_excluded_even_if_present(self):
        daily = {
            PRE_START: RawDailyRecord(sku_orders=Decimal(10)),
            T: RawDailyRecord(sku_orders=Decimal(999)),
        }
        assert pre_period_volume(daily, GMV, T) == Decimal(10)


# ---------------------------------------------------------------------------
# Noise band — hand-computed fixture
# ---------------------------------------------------------------------------


class TestNoiseBandHandComputed:
    """Fixture derivation (by hand, not via the module under test):

    3 paired pre-period days. Control is constant 10 on all three, so
    control_pre_mean = 10. Target values are 17, 20, 23 -> target_pre_mean =
    (17+20+23)/3 = 20. scale = target_pre_mean / control_pre_mean = 20/10 = 2.
    expected(d) = control[d] * scale = 10*2 = 20 for every day (constant,
    because control is constant) -- which is exactly target_pre_mean, as it
    must be by construction.

    gap(d) = target[d] - expected(d): 17-20=-3, 20-20=0, 23-20=3.
    mean(gap) = 0. sum of squared deviations = 9+0+9 = 18.
    sample variance = 18 / (3-1) = 9. stdev = sqrt(9) = 3 exactly -- a clean
    integer, so this fixture is exactly (not approximately) verifiable.
    """

    D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 8), date(2026, 1, 11)

    def _target_control(self):
        target = {
            self.D1: RawDailyRecord(gmv=Decimal(17)),
            self.D2: RawDailyRecord(gmv=Decimal(20)),
            self.D3: RawDailyRecord(gmv=Decimal(23)),
        }
        control = {
            self.D1: RawDailyRecord(gmv=Decimal(10)),
            self.D2: RawDailyRecord(gmv=Decimal(10)),
            self.D3: RawDailyRecord(gmv=Decimal(10)),
        }
        return target, control

    def test_hand_computed_noise_band_is_exactly_three(self):
        target, control = self._target_control()
        assert compute_noise_band(target, control, GMV, T) == Decimal(3)

    def test_fallback_constant_control_reduces_to_targets_own_pre_period_stdev(self):
        # A fallback control series is a constant "1" for every day
        # (control_pool._plain_pre_post_control_daily). Feeding the same
        # target fixture through a constant-1 control must give the same
        # noise band of 3, because scale then equals target_pre_mean exactly
        # and expected(d) collapses to the target's own pre-period mean.
        target, _ = self._target_control()
        fallback_control = {
            self.D1: RawDailyRecord(gmv=Decimal(1)),
            self.D2: RawDailyRecord(gmv=Decimal(1)),
            self.D3: RawDailyRecord(gmv=Decimal(1)),
        }
        assert compute_noise_band(target, fallback_control, GMV, T) == Decimal(3)

    def test_fewer_than_two_paired_days_is_none(self):
        target = {self.D1: RawDailyRecord(gmv=Decimal(17))}
        control = {self.D1: RawDailyRecord(gmv=Decimal(10))}
        assert compute_noise_band(target, control, GMV, T) is None

    def test_zero_control_pre_mean_cannot_scale_and_is_none(self):
        target = {
            self.D1: RawDailyRecord(gmv=Decimal(17)),
            self.D2: RawDailyRecord(gmv=Decimal(20)),
        }
        control = {
            self.D1: RawDailyRecord(gmv=Decimal(0)),
            self.D2: RawDailyRecord(gmv=Decimal(0)),
        }
        assert compute_noise_band(target, control, GMV, T) is None


# ---------------------------------------------------------------------------
# Tier assignment — exact boundary conditions
# ---------------------------------------------------------------------------

FLOOR = VOLUME_FLOORS[MetricFamily.REVENUE_ORDERS]  # Decimal(1) via SKU_ORDERS
BAND = Decimal(10)


def _assign(volume, incremental, noise_band, used_fallback=False, status="ok"):
    return assign_confidence(
        metric=SKU_ORDERS,
        status=status,
        incremental=incremental,
        volume=volume,
        noise_band=noise_band,
        used_fallback=used_fallback,
    )


class TestTierBoundaries:
    def test_volume_just_below_floor_is_below_floor_regardless_of_signal(self):
        assert _assign(FLOOR - Decimal("0.001"), Decimal(9999), BAND) == "below_floor"

    def test_volume_exactly_at_floor_is_not_below_floor(self):
        # At floor exactly, with a weak signal (<=1x band), lands at "thap"
        # -- but crucially it is NOT "below_floor".
        result = _assign(FLOOR, BAND, BAND)
        assert result != "below_floor"

    def test_magnitude_exactly_at_one_times_band_is_not_trung_binh(self):
        # Trung binh requires STRICTLY > 1x band; exactly at the boundary
        # falls to "thap".
        assert _assign(FLOOR, BAND, BAND) == "thap"

    def test_magnitude_just_above_one_times_band_is_trung_binh(self):
        assert _assign(FLOOR, BAND + Decimal("0.01"), BAND) == "trung_binh"

    def test_volume_exactly_at_three_times_floor_and_two_times_band_boundary(self):
        # Exactly at 2x band -> Cao's ">2x band" fails, so it is NOT cao,
        # but IS trung_binh (since 2x band > 1x band).
        volume = FLOOR * 3
        result = _assign(volume, BAND * 2, BAND)
        assert result == "trung_binh"
        assert result != "cao"

    def test_magnitude_just_above_two_times_band_at_three_times_floor_is_cao(self):
        volume = FLOOR * 3
        assert _assign(volume, BAND * 2 + Decimal("0.01"), BAND) == "cao"

    def test_volume_just_below_three_times_floor_caps_at_trung_binh_even_with_huge_signal(
        self,
    ):
        volume = FLOOR * 3 - Decimal("0.001")
        result = _assign(volume, BAND * 100, BAND)
        assert result == "trung_binh"
        assert result != "cao"

    def test_signal_within_band_on_full_path_is_thap(self):
        volume = FLOOR * 3
        assert _assign(volume, BAND - Decimal("0.01"), BAND) == "thap"


class TestFallbackNeverAwardedCao:
    def test_fallback_with_qualifying_volume_and_signal_is_still_thap(self):
        # Every condition for "cao" is met except the control path is a
        # fallback -- ADR-077: "Thap = fallback path, or signal within the
        # band" -- fallback caps at Thap unconditionally.
        volume = FLOOR * 100
        magnitude = BAND * 100
        result = _assign(volume, magnitude, BAND, used_fallback=True)
        assert result == "thap"
        assert result != "cao"
        assert result != "trung_binh"

    def test_full_path_with_identical_numbers_reaches_cao(self):
        # Control: the exact same volume/signal/band on the full path DOES
        # reach cao -- proves the fallback cap above is doing real work, not
        # just an unreachable branch.
        volume = FLOOR * 100
        magnitude = BAND * 100
        assert _assign(volume, magnitude, BAND, used_fallback=False) == "cao"

    def test_composed_pipeline_real_fallback_result_never_yields_cao(self):
        """End-to-end: feed a *real* `select_control_pool` fallback result
        (triggered honestly via <3 candidates, ADR-077 decision 3) plus a
        target series with an enormous, obviously-significant uplift into
        `compute_confidence` -- if tier assignment ever ignored
        `used_fallback`, this would read "cao". It must not.
        """
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]

        target_daily = {
            d: RawDailyRecord(gmv=Decimal(100), sku_orders=Decimal(5)) for d in pre_days
        }
        target_daily.update(
            {d: RawDailyRecord(gmv=Decimal(100000), sku_orders=Decimal(5)) for d in post_days}
        )

        # Only 2 candidates offered -> below MIN_CANDIDATES=3 -> forced
        # fallback via "insufficient_candidates", a real, honestly-triggered
        # control_pool.py code path.
        candidates = [
            ControlCandidate(
                product_id="sib-1",
                daily={d: RawDailyRecord(gmv=Decimal(90)) for d in pre_days},
                touched=False,
                first_active_date=LONG_ACTIVE,
            ),
            ControlCandidate(
                product_id="sib-2",
                daily={d: RawDailyRecord(gmv=Decimal(95)) for d in pre_days},
                touched=False,
                first_active_date=LONG_ACTIVE,
            ),
        ]
        control_result = select_control_pool(
            GMV, target_daily, candidates, T, "final", volume_floor=Decimal(1)
        )
        assert control_result.used_fallback is True

        reading = compute_metric_reading(
            GMV, target_daily, control_result.control_daily, T, "final"
        )
        assert reading.incremental is not None
        assert reading.incremental > 0  # a real, large uplift is present

        confidence = compute_confidence(GMV, target_daily, control_result, reading)
        assert confidence.used_fallback is True
        assert confidence.tier == "thap"
        assert confidence.tier != "cao"
        assert confidence.tier != "trung_binh"


class TestConfoundedAlwaysWins:
    def test_confounded_status_overrides_every_other_signal(self):
        result = _assign(FLOOR * 100, BAND * 100, BAND, used_fallback=False, status="confounded")
        assert result == "confounded"


class TestThreeDistinctOutcomes:
    """Below-floor, suppressed, and confounded must be independently
    reachable and distinguishable -- not collapsed into one another."""

    def test_below_floor_is_its_own_outcome(self):
        result = assign_confidence(
            metric=SKU_ORDERS,
            status="ok",
            incremental=Decimal(100),
            volume=Decimal(0),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert result == "below_floor"

    def test_suppressed_is_its_own_outcome_distinct_from_below_floor(self):
        # Volume is fine (above floor) but incremental could not be computed
        # at all (e.g. the post-window had no data) -- a different failure
        # mode from "not enough traffic".
        result = assign_confidence(
            metric=SKU_ORDERS,
            status="ok",
            incremental=None,
            volume=Decimal(5),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert result == "suppressed"

    def test_confounded_is_its_own_outcome_distinct_from_the_other_two(self):
        result = assign_confidence(
            metric=SKU_ORDERS,
            status="confounded",
            incremental=None,
            volume=Decimal(5),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert result == "confounded"

    def test_all_three_are_pairwise_distinct(self):
        below_floor = assign_confidence(
            metric=SKU_ORDERS,
            status="ok",
            incremental=Decimal(1),
            volume=Decimal(0),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        suppressed = assign_confidence(
            metric=SKU_ORDERS,
            status="ok",
            incremental=None,
            volume=Decimal(5),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        confounded = assign_confidence(
            metric=SKU_ORDERS,
            status="confounded",
            incremental=None,
            volume=Decimal(5),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert len({below_floor, suppressed, confounded}) == 3


class TestNegativeIncrementalReachesTiersToo:
    def test_negative_incremental_reaches_cao_via_absolute_magnitude(self):
        volume = FLOOR * 100
        assert _assign(volume, Decimal(-1000), BAND) == "cao"

    def test_negative_incremental_reaches_trung_binh(self):
        assert _assign(FLOOR, BAND + Decimal(1), BAND) == "trung_binh"
        assert _assign(FLOOR, -(BAND + Decimal(1)), BAND) == "trung_binh"


class TestConfidenceResultShape:
    def test_compute_confidence_carries_fallback_reason_through(self):
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]
        target_daily = {d: RawDailyRecord(gmv=Decimal(100)) for d in pre_days}
        target_daily.update({d: RawDailyRecord(gmv=Decimal(110)) for d in post_days})

        control_result = select_control_pool(
            GMV, target_daily, candidates=[], t=T, kind="final", volume_floor=Decimal(1)
        )
        reading = compute_metric_reading(
            GMV, target_daily, control_result.control_daily, T, "final"
        )
        result = compute_confidence(GMV, target_daily, control_result, reading)
        assert isinstance(result, ConfidenceResult)
        assert result.fallback_reason == "insufficient_candidates"
