"""Confidence tiers, per-metric volume floors, and suppression (ADR-077
decision 4, #1043).

Acceptance criteria covered here:
- Floors live in config, keyed per metric family, and are read (never
  duplicated inline) at every use site (``volume_floor_for``).
- Below-floor produces its own designed outcome (``"below_floor"``),
  distinct from ``"suppressed"`` and ``"confounded"`` — asserted separately.
- All three tiers reachable, including the exact boundary conditions
  (``= floor``, ``= 3x floor``, ``= 1x band``, ``= 2x band``), **across all
  three metric families** (revenue_orders, impressions_ctr, conversion) —
  not only the GMV/orders family. A GMV-only suite is exactly the shape of
  test bed that let the #1062 defect (a count-calibrated floor compared
  against a rate metric's own value) survive ten reviewed PRs; every family
  is exercised here specifically because CTR and conversion_rate are rates
  while GMV/SKU orders are not.
- The noise band is the pre-period stddev of the daily treated-vs-expected
  gap, asserted against a hand-computed fixture (not merely re-derived via
  the same stdlib call the implementation uses).
- A fallback-path reading can never be awarded "cao" — asserted directly,
  both at the pure ``assign_confidence`` boundary (across all three
  families) and through the composed ``compute_confidence`` pipeline fed a
  *real* ``select_control_pool`` fallback result (#1042), for a count metric
  (GMV) and a rate metric (CTR), not a hand-set boolean.
- The rate-against-count-floor defect (#1062's shape, at this module's own
  boundary) is pinned by mutation: see the executor report for the
  red-output transcript of temporarily reintroducing
  "compare the metric's own value to the floor" here.

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
    volume_indicator_for,
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
    MetricSpec,
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

    def test_unmapped_metric_raises_rather_than_defaulting(self):
        bogus = MetricSpec(
            key="bogus_metric", label="Bogus", extractor=lambda d: d.gmv, is_rate=False
        )
        with pytest.raises(KeyError):
            metric_family_of(bogus)


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

    def test_impressions_ctr_family_uses_impressions_not_ctrs_own_fractional_value(self):
        # CTR is a rate (~0.01-0.30); the ">=50 impressions/day" floor must be
        # read from impressions, never from CTR's own value.
        daily = {
            PRE_START: RawDailyRecord(ctr=Decimal("0.05"), impressions=Decimal(100)),
            PRE_START + timedelta(days=1): RawDailyRecord(
                ctr=Decimal("0.07"), impressions=Decimal(200)
            ),
        }
        assert pre_period_volume(daily, CTR, T) == Decimal(150)

    def test_conversion_family_uses_visitors_not_conversion_rates_own_fractional_value(self):
        # AnalyticsPerformanceInterval.visitors is a real, distinct column
        # from impressions (models.py) -- the conversion family's floor must
        # read it directly, exactly matching ADR-077 decision 4's literal
        # "visitors/day" wording. conversion_rate is a rate (~0.01-0.30).
        daily = {
            PRE_START: RawDailyRecord(conversion_rate=Decimal("0.1"), visitors=Decimal(30)),
            PRE_START + timedelta(days=1): RawDailyRecord(
                conversion_rate=Decimal("0.2"), visitors=Decimal(10)
            ),
        }
        assert pre_period_volume(daily, CONVERSION_RATE, T) == Decimal(20)

    def test_conversion_family_ignores_impressions_entirely(self):
        # Regression guard for the impressions-as-visitors-proxy substitution
        # a prior revision made in error: impressions present and large,
        # visitors absent -> the conversion volume must be None (no data),
        # never fall back to reading impressions instead.
        daily = {
            PRE_START: RawDailyRecord(conversion_rate=Decimal("0.1"), impressions=Decimal(5000)),
        }
        assert pre_period_volume(daily, CONVERSION_RATE, T) is None

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

    def test_volume_indicator_for_exposes_the_right_column_per_family(self):
        # control_pool.py needs this to pass volume_of for rate metrics;
        # confirm the exposed callables actually read the documented column.
        record = RawDailyRecord(
            gmv=Decimal(1),
            sku_orders=Decimal(2),
            impressions=Decimal(3),
            ctr=Decimal(4),
            conversion_rate=Decimal(5),
            visitors=Decimal(6),
        )
        assert volume_indicator_for(GMV)(record) == Decimal(2)  # sku_orders
        assert volume_indicator_for(CTR)(record) == Decimal(3)  # impressions
        assert volume_indicator_for(CONVERSION_RATE)(record) == Decimal(6)  # visitors


class TestConversionFloorUsesVisitorsNotImpressions:
    """Regression guard for a real defect a prior revision of this module
    had: reading the conversion family's volume floor against `impressions`
    (believing no `visitors` column existed) instead of the real, distinct
    `AnalyticsPerformanceInterval.visitors` column.

    Impressions and visitors differ by roughly the click-through ratio, so
    impressions are typically one to two orders of magnitude larger than
    visitors -- a >=20 floor applied to impressions is a far weaker gate
    than ADR-077 decision 4 specifies (">=20 visitors/day"). This fixture
    sets impressions far above the threshold (5000/day) while visitors sit
    below it (5/day, floor is 20) -- if the volume indicator were ever
    impressions instead of visitors again, this reading would wrongly clear
    the floor and get published as a real tier instead of the designed
    "Chua du du lieu de uoc tinh" (below_floor) state.
    """

    HIGH_IMPRESSIONS = Decimal(5000)
    LOW_VISITORS = Decimal(5)  # below the conversion floor of 20

    def _daily(self) -> dict:
        days = [PRE_START + timedelta(days=i) for i in range(14)]
        return {
            d: RawDailyRecord(
                conversion_rate=Decimal("0.1"),
                impressions=self.HIGH_IMPRESSIONS,
                visitors=self.LOW_VISITORS,
            )
            for d in days
        }

    def test_pre_period_volume_reads_the_low_visitor_count_not_high_impressions(self):
        daily = self._daily()
        assert pre_period_volume(daily, CONVERSION_RATE, T) == self.LOW_VISITORS
        # Sanity: impressions really is far above the floor in this fixture
        # -- proves the two columns diverge in this scenario, so the test
        # is actually exercising the substitution, not a case where both
        # columns happen to agree.
        assert self.HIGH_IMPRESSIONS > volume_floor_for(CONVERSION_RATE) * 100
        assert self.LOW_VISITORS < volume_floor_for(CONVERSION_RATE)

    def test_reading_is_below_floor_despite_huge_impressions(self):
        daily = self._daily()
        volume = pre_period_volume(daily, CONVERSION_RATE, T)
        result = assign_confidence(
            metric=CONVERSION_RATE,
            status="ok",
            incremental=Decimal("0.05"),  # a real, large-looking signal
            volume=volume,
            noise_band=Decimal("0.001"),  # tiny band -- would easily be "cao"
            used_fallback=False,
        )
        assert result == "below_floor"


# ---------------------------------------------------------------------------
# Noise band — hand-computed fixture (unit-agnostic math, GMV is a
# representative choice; the rate-vs-count distinction does not apply to the
# noise-band arithmetic itself, only to the *floor* comparison above and the
# tier-boundary composition below, both of which are exercised per family).
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

    def test_hand_computed_noise_band_also_holds_for_a_rate_metric(self):
        # Same arithmetic, but the series is CTR (a rate, ~0.017-0.023
        # range) -- proves compute_noise_band is genuinely unit-agnostic and
        # not silently assuming a count/currency scale.
        target = {
            self.D1: RawDailyRecord(ctr=Decimal("0.017")),
            self.D2: RawDailyRecord(ctr=Decimal("0.020")),
            self.D3: RawDailyRecord(ctr=Decimal("0.023")),
        }
        control = {
            self.D1: RawDailyRecord(ctr=Decimal("0.010")),
            self.D2: RawDailyRecord(ctr=Decimal("0.010")),
            self.D3: RawDailyRecord(ctr=Decimal("0.010")),
        }
        assert compute_noise_band(target, control, CTR, T) == Decimal("0.003")

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
# Tier assignment — exact boundary conditions, across all three families
# ---------------------------------------------------------------------------


def _assign(metric, volume, incremental, noise_band, used_fallback=False, status="ok"):
    return assign_confidence(
        metric=metric,
        status=status,
        incremental=incremental,
        volume=volume,
        noise_band=noise_band,
        used_fallback=used_fallback,
    )


#: One representative metric + a family-appropriate noise-band magnitude per
#: family. BAND is deliberately a plausible pre-period noise level for that
#: family's own unit (a rate metric's band is a small fraction, not "10")
#: -- boundary math is identical, but every fixture stays dimensionally
#: honest for its family instead of reusing an count-scaled BAND=10 on a
#: rate metric where it would never occur in real data.
_FAMILY_CASES = [
    pytest.param(SKU_ORDERS, Decimal(10), id="revenue_orders"),
    pytest.param(CTR, Decimal("0.01"), id="impressions_ctr"),
    pytest.param(CONVERSION_RATE, Decimal("0.02"), id="conversion"),
]


@pytest.mark.parametrize("metric,band", _FAMILY_CASES)
class TestTierBoundariesAcrossFamilies:
    def test_volume_just_below_floor_is_below_floor_regardless_of_signal(self, metric, band):
        floor = volume_floor_for(metric)
        assert _assign(metric, floor - Decimal("0.001"), band * 9999, band) == "below_floor"

    def test_volume_exactly_at_floor_with_weak_signal_is_thap_not_below_floor(self, metric, band):
        floor = volume_floor_for(metric)
        result = _assign(metric, floor, band, band)
        assert result == "thap"
        assert result != "below_floor"

    def test_magnitude_exactly_at_one_times_band_is_not_trung_binh(self, metric, band):
        floor = volume_floor_for(metric)
        assert _assign(metric, floor, band, band) == "thap"

    def test_magnitude_just_above_one_times_band_is_trung_binh(self, metric, band):
        floor = volume_floor_for(metric)
        assert _assign(metric, floor, band + band / 100, band) == "trung_binh"

    def test_volume_exactly_at_three_times_floor_and_two_times_band_is_trung_binh_not_cao(
        self, metric, band
    ):
        floor = volume_floor_for(metric)
        volume = floor * 3
        result = _assign(metric, volume, band * 2, band)
        assert result == "trung_binh"
        assert result != "cao"

    def test_magnitude_just_above_two_times_band_at_three_times_floor_is_cao(self, metric, band):
        floor = volume_floor_for(metric)
        volume = floor * 3
        assert _assign(metric, volume, band * 2 + band / 100, band) == "cao"

    def test_volume_just_below_three_times_floor_caps_at_trung_binh_even_with_huge_signal(
        self, metric, band
    ):
        floor = volume_floor_for(metric)
        volume = floor * 3 - Decimal("0.001")
        result = _assign(metric, volume, band * 100, band)
        assert result == "trung_binh"
        assert result != "cao"

    def test_signal_within_band_on_full_path_is_thap(self, metric, band):
        floor = volume_floor_for(metric)
        volume = floor * 3
        assert _assign(metric, volume, band - band / 100, band) == "thap"

    def test_negative_incremental_reaches_cao_via_absolute_magnitude(self, metric, band):
        floor = volume_floor_for(metric)
        volume = floor * 100
        assert _assign(metric, volume, -(band * 1000), band) == "cao"

    def test_negative_incremental_reaches_trung_binh_symmetrically_with_positive(
        self, metric, band
    ):
        floor = volume_floor_for(metric)
        positive = _assign(metric, floor, band + band / 100, band)
        negative = _assign(metric, floor, -(band + band / 100), band)
        assert positive == negative == "trung_binh"


class TestFallbackNeverAwardedCaoAcrossFamilies:
    @pytest.mark.parametrize("metric,band", _FAMILY_CASES)
    def test_fallback_with_qualifying_volume_and_signal_is_still_thap(self, metric, band):
        # Every condition for "cao" is met except the control path is a
        # fallback -- ADR-077: "Thap = fallback path, or signal within the
        # band" -- fallback caps at Thap unconditionally, for every family.
        floor = volume_floor_for(metric)
        volume = floor * 100
        magnitude = band * 1000
        result = _assign(metric, volume, magnitude, band, used_fallback=True)
        assert result == "thap"
        assert result != "cao"
        assert result != "trung_binh"

    @pytest.mark.parametrize("metric,band", _FAMILY_CASES)
    def test_full_path_with_identical_numbers_reaches_cao(self, metric, band):
        # Control: the exact same volume/signal/band on the full path DOES
        # reach cao -- proves the fallback cap above is doing real work, not
        # just an unreachable branch, for every family.
        floor = volume_floor_for(metric)
        volume = floor * 100
        magnitude = band * 1000
        assert _assign(metric, volume, magnitude, band, used_fallback=False) == "cao"

    def test_composed_pipeline_real_fallback_result_never_yields_cao_for_gmv(self):
        """End-to-end, revenue_orders family (count metric, floor via its own
        extractor): feed a *real* `select_control_pool` fallback result
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
        # Pin the branch this fixture actually takes (only 2 candidates,
        # below MIN_CANDIDATES=3) -- not just "used_fallback is True" but
        # *why*, so this test cannot silently start passing via the other
        # fallback trigger (low_mean_correlation) if MIN_CANDIDATES ever
        # changes underneath it.
        assert control_result.used_fallback is True
        assert control_result.fallback_reason == "insufficient_candidates"

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

    def test_composed_pipeline_real_fallback_result_never_yields_cao_for_ctr(self):
        """Same end-to-end proof, but for impressions_ctr -- a *rate* family
        whose volume floor must be screened via `volume_of=impressions`
        (control_pool.py's #1062 contract), not CTR's own value. This is the
        family the original defect actually broke: if control_pool
        screening or confidence tiering ever regressed to comparing CTR's
        own ~0.05 value against the impressions floor, every candidate would
        be disqualified for a different (wrong) reason and this test's
        fallback would be for the wrong cause -- so this test also asserts
        the fallback_reason is the real trigger this fixture intends
        (insufficient candidates), not an accidental floor failure.
        """
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]

        target_daily = {
            d: RawDailyRecord(ctr=Decimal("0.05"), impressions=Decimal(200)) for d in pre_days
        }
        target_daily.update(
            {d: RawDailyRecord(ctr=Decimal("0.50"), impressions=Decimal(200)) for d in post_days}
        )

        candidates = [
            ControlCandidate(
                product_id="sib-1",
                daily={
                    d: RawDailyRecord(ctr=Decimal("0.04"), impressions=Decimal(180))
                    for d in pre_days
                },
                touched=False,
                first_active_date=LONG_ACTIVE,
            ),
            ControlCandidate(
                product_id="sib-2",
                daily={
                    d: RawDailyRecord(ctr=Decimal("0.045"), impressions=Decimal(190))
                    for d in pre_days
                },
                touched=False,
                first_active_date=LONG_ACTIVE,
            ),
        ]
        control_result = select_control_pool(
            CTR,
            target_daily,
            candidates,
            T,
            "final",
            volume_floor=Decimal(50),
            volume_of=volume_indicator_for(CTR),
        )
        assert control_result.used_fallback is True
        assert control_result.fallback_reason == "insufficient_candidates"

        reading = compute_metric_reading(
            CTR, target_daily, control_result.control_daily, T, "final"
        )
        assert reading.incremental is not None
        assert reading.incremental > 0

        confidence = compute_confidence(CTR, target_daily, control_result, reading)
        assert confidence.used_fallback is True
        assert confidence.tier == "thap"
        assert confidence.tier != "cao"
        assert confidence.tier != "trung_binh"


def _linear(base: str | int, slope: str | int, start: date, day: date) -> Decimal:
    """``base + slope * (day - start).days`` -- the shared building block for
    every genuinely-correlated fixture below. Two series built from this
    function with different ``base``/``slope`` but the same sign of slope
    are perfectly (or near-perfectly) Pearson-correlated, because Pearson
    correlation is invariant under an affine transform of either variable --
    unlike a constant series (zero variance, ``statistics.correlation``
    raises, mapped to ``0.0`` by ``_safe_correlation`` in control_pool.py),
    which is what every prior composed-pipeline fixture in this file
    accidentally used for its "control" candidates, silently routing every
    one of them onto the fallback branch instead of the full control path
    they were meant to exercise."""
    offset = (day - start).days
    return Decimal(base) + Decimal(slope) * Decimal(offset)


class TestComposedPipelineGenuinelyReachesNonFallbackPath:
    """The composed-pipeline tests above (``TestFallbackNeverAwardedCao...``,
    and the original version of the conversion-family test in
    ``TestConfidenceResultShape``) all built their control-candidate
    fixtures from *constant* daily series. A constant series has zero
    variance, so ``statistics.correlation`` cannot define a Pearson
    coefficient and ``control_pool._safe_correlation`` maps that to ``0.0``
    -- which sits below ``MIN_MEAN_CORRELATION`` (0.2) and forces
    ``select_control_pool`` onto its fallback branch every time, regardless
    of what the fixture's author intended. None of those tests asserted
    ``used_fallback`` in the *non-fallback* direction, so this went
    unnoticed: every "end-to-end" composed test in this file was, in
    practice, exercising the fallback path only.

    These two tests are the fix: real, non-constant, genuinely-correlated
    candidate series (built from :func:`_linear`, so Pearson correlation is
    exactly computable and does not degenerate), for one count family
    (revenue_orders / GMV) and one rate family (conversion -- the family the
    original #1062 defect actually broke). Both assert ``used_fallback is
    False`` explicitly, plus the two conditions that make that assertion
    meaningful rather than accidental: a real mean correlation above the
    0.2 bar, and at least ``MIN_CANDIDATES`` (3) candidates actually
    selected.
    """

    def test_gmv_revenue_orders_family_reaches_real_non_fallback_control_path(self):
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]

        # Target: a genuine linear pre-period trend (not constant), plus a
        # large, deliberate post-window jump on top of that trend -- the
        # "treatment effect" this fixture is built to detect.
        target_daily = {
            d: RawDailyRecord(gmv=_linear(100, 5, PRE_START, d), sku_orders=Decimal(5))
            for d in pre_days
        }
        target_daily.update(
            {
                d: RawDailyRecord(
                    gmv=_linear(100, 5, PRE_START, d) + Decimal(5000), sku_orders=Decimal(5)
                )
                for d in post_days
            }
        )

        # Three candidates, each its own affine function of the same day
        # offset with a different base/slope but the same slope sign as the
        # target -- genuinely correlated (Pearson ~= 1.0), never constant,
        # and never touched by any jump (no treatment effect of their own).
        candidate_specs = [("sib-1", 90, 5), ("sib-2", 80, 6), ("sib-3", 70, 4)]
        candidates = [
            ControlCandidate(
                product_id=product_id,
                daily={
                    d: RawDailyRecord(gmv=_linear(base, slope, PRE_START, d))
                    for d in (*pre_days, *post_days)
                },
                touched=False,
                first_active_date=LONG_ACTIVE,
            )
            for product_id, base, slope in candidate_specs
        ]

        control_result = select_control_pool(
            GMV, target_daily, candidates, T, "final", volume_floor=Decimal(1)
        )

        # The assertion that is the whole point of this test: it must
        # actually be on the full control path, not silently drift onto
        # fallback the way every prior composed fixture in this file did.
        assert control_result.used_fallback is False
        assert control_result.fallback_reason is None
        assert control_result.mean_correlation is not None
        assert control_result.mean_correlation > 0.2
        assert len(control_result.selected) >= 3

        reading = compute_metric_reading(
            GMV, target_daily, control_result.control_daily, T, "final"
        )
        assert reading.incremental is not None
        assert reading.incremental > 0  # the deliberate post-window jump survives DiD adjustment

        confidence = compute_confidence(GMV, target_daily, control_result, reading)
        assert confidence.used_fallback is False
        # Pinned, not just "a real tier": volume=5 clears 3x the floor (1),
        # and the 5000-unit jump dwarfs the pre-period noise band (~3.7) by
        # orders of magnitude -- deterministic given this fixture, verified
        # by direct computation, not merely asserted to be in-range.
        assert confidence.tier == "cao"

    def test_conversion_family_reaches_real_non_fallback_control_path(self):
        """Same proof, for the *rate* family -- the family the original
        #1062 defect actually broke, and the family this file's own
        regression bug (reported by Review) most recently hid behind."""
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]

        def rec(cr: Decimal, visitors: Decimal) -> RawDailyRecord:
            return RawDailyRecord(conversion_rate=cr, visitors=visitors)

        target_daily = {
            d: rec(_linear("0.05", "0.002", PRE_START, d), Decimal(100)) for d in pre_days
        }
        target_daily.update(
            {
                d: rec(_linear("0.05", "0.002", PRE_START, d) + Decimal("0.15"), Decimal(100))
                for d in post_days
            }
        )

        candidate_specs = [
            ("sib-1", "0.045", "0.002"),
            ("sib-2", "0.040", "0.0025"),
            ("sib-3", "0.035", "0.0018"),
        ]
        candidates = [
            ControlCandidate(
                product_id=product_id,
                daily={
                    d: rec(_linear(base, slope, PRE_START, d), Decimal(100))
                    for d in (*pre_days, *post_days)
                },
                touched=False,
                first_active_date=LONG_ACTIVE,
            )
            for product_id, base, slope in candidate_specs
        ]

        control_result = select_control_pool(
            CONVERSION_RATE,
            target_daily,
            candidates,
            T,
            "final",
            volume_floor=Decimal(20),
            volume_of=volume_indicator_for(CONVERSION_RATE),
        )

        assert control_result.used_fallback is False
        assert control_result.fallback_reason is None
        assert control_result.mean_correlation is not None
        assert control_result.mean_correlation > 0.2
        assert len(control_result.selected) >= 3

        reading = compute_metric_reading(
            CONVERSION_RATE, target_daily, control_result.control_daily, T, "final"
        )
        assert reading.incremental is not None
        assert reading.incremental > 0

        confidence = compute_confidence(CONVERSION_RATE, target_daily, control_result, reading)
        assert confidence.used_fallback is False
        # Pinned, not just "a real tier": volume=100 visitors clears 3x the
        # floor (20), and the deliberate +0.15 post-window jump dwarfs the
        # pre-period noise band (~0.0019) by orders of magnitude --
        # deterministic given this fixture, verified by direct computation.
        assert confidence.tier == "cao"
        assert confidence.volume == Decimal(100)


class TestConfoundedAlwaysWins:
    @pytest.mark.parametrize("metric,band", _FAMILY_CASES)
    def test_confounded_status_overrides_every_other_signal(self, metric, band):
        floor = volume_floor_for(metric)
        result = _assign(
            metric, floor * 100, band * 100, band, used_fallback=False, status="confounded"
        )
        assert result == "confounded"


class TestThreeDistinctOutcomes:
    """Below-floor, suppressed, and confounded must be independently
    reachable and distinguishable -- not collapsed into one another. Checked
    for both a count metric (SKU_ORDERS) and a rate metric (CONVERSION_RATE)
    since the below-floor gate is exactly where the family/rate distinction
    matters."""

    @pytest.mark.parametrize("metric", [SKU_ORDERS, CONVERSION_RATE])
    def test_below_floor_is_its_own_outcome(self, metric):
        result = assign_confidence(
            metric=metric,
            status="ok",
            incremental=Decimal(100),
            volume=Decimal(0),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert result == "below_floor"

    @pytest.mark.parametrize("metric", [SKU_ORDERS, CONVERSION_RATE])
    def test_suppressed_is_its_own_outcome_distinct_from_below_floor(self, metric):
        # Volume is fine (above floor) but incremental could not be computed
        # at all (e.g. the post-window had no data) -- a different failure
        # mode from "not enough traffic".
        floor = volume_floor_for(metric)
        result = assign_confidence(
            metric=metric,
            status="ok",
            incremental=None,
            volume=floor * 5,
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert result == "suppressed"

    @pytest.mark.parametrize("metric", [SKU_ORDERS, CONVERSION_RATE])
    def test_confounded_is_its_own_outcome_distinct_from_the_other_two(self, metric):
        floor = volume_floor_for(metric)
        result = assign_confidence(
            metric=metric,
            status="confounded",
            incremental=None,
            volume=floor * 5,
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert result == "confounded"

    @pytest.mark.parametrize("metric", [SKU_ORDERS, CONVERSION_RATE])
    def test_all_three_are_pairwise_distinct(self, metric):
        floor = volume_floor_for(metric)
        below_floor = assign_confidence(
            metric=metric,
            status="ok",
            incremental=Decimal(1),
            volume=Decimal(0),
            noise_band=Decimal(1),
            used_fallback=False,
        )
        suppressed = assign_confidence(
            metric=metric,
            status="ok",
            incremental=None,
            volume=floor * 5,
            noise_band=Decimal(1),
            used_fallback=False,
        )
        confounded = assign_confidence(
            metric=metric,
            status="confounded",
            incremental=None,
            volume=floor * 5,
            noise_band=Decimal(1),
            used_fallback=False,
        )
        assert len({below_floor, suppressed, confounded}) == 3


class TestConfidenceResultShape:
    def test_compute_confidence_carries_fallback_reason_through(self):
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]
        target_daily = {d: RawDailyRecord(gmv=Decimal(100)) for d in pre_days}
        target_daily.update({d: RawDailyRecord(gmv=Decimal(110)) for d in post_days})

        control_result = select_control_pool(
            GMV, target_daily, candidates=[], t=T, kind="final", volume_floor=Decimal(1)
        )
        # Pin the branch: zero candidates is unambiguously the fallback
        # path, and specifically the insufficient-candidates trigger, not
        # the low-mean-correlation one -- assert both explicitly rather than
        # inferring "fallback" only from the reason string below.
        assert control_result.used_fallback is True
        reading = compute_metric_reading(
            GMV, target_daily, control_result.control_daily, T, "final"
        )
        result = compute_confidence(GMV, target_daily, control_result, reading)
        assert isinstance(result, ConfidenceResult)
        assert result.used_fallback is True
        assert result.fallback_reason == "insufficient_candidates"

    def test_compute_confidence_for_conversion_family_with_constant_candidates_correctly_falls_back(
        self,
    ):
        """This fixture's candidates are literally constant (every day the
        same conversion_rate value) -- zero variance, so
        ``statistics.correlation`` cannot define a Pearson coefficient and
        ``control_pool._safe_correlation`` maps that to ``0.0``, below
        ``MIN_MEAN_CORRELATION`` (0.2). That correctly forces the fallback
        branch via ``low_mean_correlation``, distinct from the
        ``insufficient_candidates`` trigger above (5 candidates are offered
        here, well above ``MIN_CANDIDATES``) -- this is a *different*,
        legitimate way to reach fallback, asserted explicitly rather than
        left implicit.

        This test previously claimed (in its name and a since-removed
        comment) to exercise the conversion family's *non-fallback* path --
        it did not: it silently took this fallback branch instead, because
        nothing here asserted ``used_fallback`` in either direction. Caught
        by Review on #1043. The genuine non-fallback conversion-family proof
        now lives in
        ``TestComposedPipelineGenuinelyReachesNonFallbackPath::test_conversion_family_reaches_real_non_fallback_control_path``,
        which uses non-constant, actually-correlated candidate series and
        asserts ``used_fallback is False``. This test is kept, renamed and
        corrected, as the fallback-side counterpart for the same family.
        """
        pre_days = [PRE_START + timedelta(days=i) for i in range(14)]
        post_days = [T + timedelta(days=i) for i in range(1, 15)]

        def rec(cr, visitors):
            return RawDailyRecord(conversion_rate=cr, visitors=visitors)

        target_daily = {d: rec(Decimal("0.10"), Decimal(100)) for d in pre_days}
        target_daily.update({d: rec(Decimal("0.30"), Decimal(100)) for d in post_days})

        candidates = [
            ControlCandidate(
                product_id=f"sib-{i}",
                daily={d: rec(Decimal("0.10"), Decimal(100)) for d in pre_days},
                touched=False,
                first_active_date=LONG_ACTIVE,
            )
            for i in range(5)
        ]
        control_result = select_control_pool(
            CONVERSION_RATE,
            target_daily,
            candidates,
            T,
            "final",
            volume_floor=Decimal(20),
            volume_of=volume_indicator_for(CONVERSION_RATE),
        )
        # The assertion this test was missing: pin the branch it actually
        # takes, and why (degenerate zero-variance correlation), rather than
        # letting it pass silently on whichever branch the fixture happens
        # to land on.
        assert control_result.used_fallback is True
        assert control_result.fallback_reason == "low_mean_correlation"
        assert control_result.mean_correlation == 0.0

        reading = compute_metric_reading(
            CONVERSION_RATE, target_daily, control_result.control_daily, T, "final"
        )
        result = compute_confidence(CONVERSION_RATE, target_daily, control_result, reading)
        assert result.used_fallback is True
        assert result.tier == "thap"  # fallback caps unconditionally, per ADR-077 decision 4
        assert result.volume == Decimal(100)
