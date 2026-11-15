"""P101: TikTok forecast floor (generic uplift >= 5 % P50) and the GMV range's source.

Pure tests; no database.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from juli_backend.services.optimize_product.prediction import (
    CalibrationStats,
    gmv_range_from_lift,
    gmv_range_per_month,
    predict,
)
from juli_backend.services.optimize_product.tunables import (
    GENERIC_UPLIFT_FLOOR,
    UPLIFT_FLOOR_EXEMPT_LEVERS,
    DiagTunables,
)
from juli_backend.services.optimize_product.volatility import kpi_target


def test_prior_p50_floored_at_five_percent_and_p90_not_below():
    # title / small gap: prior (0.00, 0.05), midpoint 0.025 -> P50 lifted to 5 %.
    p = predict("title", 5)
    assert p.source == "prior"
    assert p.lift_mid == pytest.approx(GENERIC_UPLIFT_FLOOR)
    assert p.lift_high >= p.lift_mid
    assert p.lift_low <= p.lift_mid
    # P10 is the conservative tail and is not floored.
    assert p.lift_low == 0.0
    # cover_image / small gap (0.00, 0.06): P90 stays at 0.06.
    c = predict("cover_image", 5)
    assert c.lift_mid == pytest.approx(0.05) and c.lift_high == pytest.approx(0.06)


def test_prior_above_floor_is_untouched():
    p = predict("buy_more_save_more", None)
    assert (p.lift_low, p.lift_high) == (0.03, 0.10)
    assert p.lift_mid == pytest.approx(0.065)


def test_description_is_exempt_like_shopee():
    assert "description" in UPLIFT_FLOOR_EXEMPT_LEVERS
    p = predict("description", 5)  # prior (0.00, 0.05)
    assert p.lift_mid == pytest.approx(0.025)
    assert p.lift_high == pytest.approx(0.05)


def test_no_floor_when_fleet_or_shop_calibrated():
    fleet = CalibrationStats(coefficient=0.25, results=50)  # factor 0.5 -> halves the lift
    p = predict("title", None, fleet=fleet)
    assert p.source == "fleet"
    assert p.lift_mid < GENERIC_UPLIFT_FLOOR
    shop = CalibrationStats(coefficient=0.25, results=10)
    s = predict("cover_image", 80, shop=shop)
    assert s.source == "shop"
    assert s.lift_mid == pytest.approx((s.lift_low + s.lift_high) / 2)


def test_gmv_range_follows_lift_band_not_kpi_band():
    low, high = gmv_range_from_lift(1_000_000, 0.03, 0.10)
    assert low == pytest.approx(900_000)
    assert high == pytest.approx(3_000_000)
    assert gmv_range_from_lift(0.0, 0.03, 0.10) == (0.0, 0.0)
    # Title card: lift_low 0 gives GMV min 0, never a positive min from the KPI band.
    t = predict("title", 5)
    lo, hi = gmv_range_from_lift(500_000, t.lift_low, t.lift_high)
    assert lo == 0.0 and hi > 0


def test_mngn_range_collapse_root_cause_and_fix():
    """MNGN = mua nhiều giảm nhiều (buy_more_save_more, AOV). A below-shop-level card
    clamps the KPI with kpi_max_band_mult = kpi_min_band_mult, so target_min == target_max
    and the old KPI-band GMV range collapsed to one number."""
    base = DiagTunables()
    collapsed = replace(base, kpi_max_band_mult=base.kpi_min_band_mult)
    kpi = kpi_target(
        metric="aov",
        current=100_000.0,
        band_pct=1.0,
        reference=130_000.0,
        window_days=14,
        tunables=collapsed,
        volatile=False,
    )
    assert kpi.target_min == kpi.target_max
    old = gmv_range_per_month(300_000.0, kpi.current, kpi.target_min, kpi.target_max)
    assert old[0] == old[1]
    p = predict("buy_more_save_more", None)
    new_low, new_high = gmv_range_from_lift(300_000.0, p.lift_low, p.lift_high)
    assert new_low < new_high


def test_tiny_forecast_under_new_code_path():
    """A +83k/month MNGN card (gmv/day 300k, AOV band 1 %): KPI band gives ~90k; the lift
    band gives 270k-900k. The floor itself does not move MNGN (prior P50 6.5 % >= 5 %)."""
    kpi = kpi_target(
        metric="aov",
        current=100_000.0,
        band_pct=1.0,
        reference=130_000.0,
        window_days=14,
        tunables=replace(DiagTunables(), kpi_max_band_mult=1.0),
        volatile=False,
    )
    old_low, old_high = gmv_range_per_month(300_000.0, 100_000.0, kpi.target_min, kpi.target_max)
    assert 80_000 < old_low == old_high < 100_000
    p = predict("buy_more_save_more", None)
    low, high = gmv_range_from_lift(300_000.0, p.lift_low, p.lift_high)
    assert low > 2.9 * old_low and high > low
    assert p.lift_mid >= GENERIC_UPLIFT_FLOOR
