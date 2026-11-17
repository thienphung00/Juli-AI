"""F3: the shared period noise band, against a hand-computed series."""

from __future__ import annotations

import math

from juli_backend.services.forecast.noise import period_band


def test_period_band_matches_the_hand_computed_series():
    # days 2, 4, 6, 8: mean 5, sample variance (9+1+1+9)/3 = 20/3, sd = 2.5819889
    # a 7-day total: mean 35, sd 2.5819889 x sqrt(7) = 6.8313; 80 % z = 1.2815516
    band = period_band([2, 4, 6, 8], 7)
    half = 1.2815516 * math.sqrt(20 / 3) * math.sqrt(7)
    assert band.days == 4
    assert abs(band.mean - 35.0) < 1e-9
    assert abs((band.p90 - band.p10) / 2 - half) < 1e-3
    assert abs(band.band_pct - half / 35 * 100) < 1e-3


def test_a_longer_period_is_relatively_narrower():
    series = [2, 4, 6, 8, 3, 5, 7]
    assert period_band(series, 30).band_pct < period_band(series, 7).band_pct


def test_a_flat_series_gets_the_one_percent_minimum():
    band = period_band([5, 5, 5, 5], 14)
    assert abs(band.band_pct - 1.0) < 1e-9
    assert abs(band.p90 - 70 * 1.01) < 1e-9


def test_missing_days_are_skipped_and_too_little_history_has_no_band():
    assert period_band([2, None, 4, None, 6, 8], 7).days == 4
    assert period_band([3], 7).band_pct is None
    assert period_band([], 7).band_pct is None
    assert period_band([0, 0, 0], 7).band_pct is None


def _money(dgmv_p90: float) -> dict:
    block = {
        "p50": {"dgmv": dgmv_p90 / 2, "dorders": 1.0, "dprofit": None},
        "p90": {"dgmv": dgmv_p90, "dorders": 2.0, "dprofit": None},
    }
    return {"days": 7, "period": {"days": 7, "total": block}, "total": block}


def test_card_within_noise_nulls_the_shown_value_and_keeps_the_quantiles():
    from juli_backend.services.shopee_recommendations.prediction import apply_within_noise

    history = {"gmv": [0.0, 200.0] * 10, "orders": [1.0] * 20, "profit": [None] * 20}
    out = apply_within_noise(_money(50.0), "price", history)
    # gmv: sd 102.6 x sqrt(7) x 1.28 = 348 > 50 -> within noise; orders flat -> 1 % band of 7 = 0.07
    assert out["within_noise"] == ["dgmv"]
    assert out["shown"] == {"dgmv": None, "dorders": 1.0, "dprofit": None}
    assert out["period"]["total"]["p90"]["dgmv"] == 50.0
    assert apply_within_noise(_money(50.0), "listing_hide", history)["within_noise"] == []
