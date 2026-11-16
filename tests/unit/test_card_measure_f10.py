"""F10 Đo lường: ADR-077's reader behind a platform series seam (``services.card_measure``).

- controls: K = 5 most pre-correlated untouched products, at least 3 with mean r ≥ 0.2, else
  plain before/after at the lowest tier (``thap``);
- verdict Tăng / Không đổi / Giảm, Không đổi inside the noise band;
- Đúng dự báo when Thực tế lies inside the internal P10–P90;
- only ``cao`` / ``trung_binh`` readings on fresh data calibrate;
- the TikTok series source: uncovered days dropped, touched products never controls;
- Shopee's reader is unchanged by the new ``pre_days`` argument.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from juli_backend.services.card_measure import reader
from juli_backend.services.card_measure.noise import MIN_BAND_PCT, period_band_pct
from juli_backend.services.card_measure.tiktok_series import (
    TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS,
    card_forecast,
    gmv_bundle,
)
from juli_backend.services.shopee_recommendations import impact

T = date(2026, 9, 20)
RUN = 14
END = T + timedelta(days=RUN)


def _pattern(offset: int) -> float:
    return 100.0 + 20.0 * ((offset * 7) % 5)


def _series(scale: float, *, lift: float = 1.0, run: int = RUN) -> dict[date, float]:
    out = {T - timedelta(days=i): scale * _pattern(i) for i in range(1, run + 1)}
    out.update({T + timedelta(days=i): scale * lift * _pattern(i) for i in range(1, run + 1)})
    return out


def _flat(value: float, run: int = RUN) -> dict[date, float]:
    return {T + timedelta(days=i): value for i in range(-run, run + 1) if i != 0}


def _measure(bundle: reader.SeriesBundle, *, today: date = END, forecast=None):
    return reader.measure(
        bundle,
        T,
        RUN,
        today=today,
        expected_lag_days=TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS,
        platform="tiktok",
        metric="gmv",
        forecast=forecast,
    )


def _controls(n: int) -> dict[str, dict[date, float]]:
    return {f"c{k}": _series(float(k + 1)) for k in range(n)}


# --- controls -----------------------------------------------------------------------------


def test_three_correlated_controls_correct_the_effect_at_a_high_tier():
    got = _measure(reader.SeriesBundle(_series(10.0, lift=1.2), _controls(3), newest_day=END))

    assert got.reading.fallback is False
    assert len(got.reading.controls) == 3
    assert got.reading.confidence == "cao"
    assert abs(got.reading.impact_pct - 0.2) < 1e-9
    assert got.verdict == reader.VERDICT_UP
    assert got.calibrates is True


def test_at_most_five_controls_are_used():
    got = _measure(reader.SeriesBundle(_series(10.0, lift=1.2), _controls(7), newest_day=END))

    assert len(got.reading.controls) == impact.K_CONTROLS


def test_two_controls_fall_back_to_before_after_at_the_lowest_tier():
    got = _measure(reader.SeriesBundle(_series(10.0, lift=1.2), _controls(2), newest_day=END))

    assert got.reading.fallback is True
    assert got.reading.confidence == "thap"
    assert got.reading.reason == "no_controls"
    assert got.calibrates is False


def test_uncorrelated_controls_fall_back_too():
    controls = {f"flat{k}": _flat(50.0 + k) for k in range(4)}  # r = 0 against the product

    got = _measure(reader.SeriesBundle(_series(10.0, lift=1.2), controls, newest_day=END))

    assert got.reading.fallback is True
    assert got.reading.confidence == "thap"


def test_the_before_window_is_as_long_as_the_run():
    seven = reader.measure(
        reader.SeriesBundle(_series(10.0, lift=1.2, run=7), {}, newest_day=END),
        T,
        7,
        today=END,
        expected_lag_days=2,
        platform="tiktok",
        metric="gmv",
    )

    assert (seven.reading.pre_days_used, seven.reading.post_days_used) == (7, 7)


# --- verdict ------------------------------------------------------------------------------


def _reading(impact_pct: float | None, confidence: str = "cao") -> impact.Reading:
    return impact.Reading(confidence, None, impact_pct=impact_pct)


def test_an_effect_inside_the_band_is_khong_doi():
    assert reader.verdict_of(_reading(0.004), 1.0) == reader.VERDICT_FLAT
    assert reader.verdict_of(_reading(-0.03), 3.0) == reader.VERDICT_FLAT


def test_an_effect_outside_the_band_is_tang_or_giam():
    assert reader.verdict_of(_reading(0.05), 1.0) == reader.VERDICT_UP
    assert reader.verdict_of(_reading(-0.05), 1.0) == reader.VERDICT_DOWN
    assert reader.VERDICT_VI[reader.VERDICT_DOWN] == "Giảm"


def test_a_suppressed_reading_has_no_verdict():
    assert reader.verdict_of(_reading(None, "suppressed"), 1.0) is None
    assert reader.verdict_of(_reading(0.5, "suppressed"), 1.0) is None


def test_a_flat_product_measures_khong_doi():
    got = _measure(reader.SeriesBundle(_series(10.0), _controls(3), newest_day=END))

    assert got.verdict == reader.VERDICT_FLAT


def test_the_noise_band_has_a_one_percent_floor():
    assert period_band_pct([100.0] * 14, 14) == MIN_BAND_PCT
    assert period_band_pct([], 14) == MIN_BAND_PCT
    assert period_band_pct([50.0, 150.0] * 7, 14) > MIN_BAND_PCT


# --- Dự kiến vs Thực tế -------------------------------------------------------------------


def test_dung_du_bao_when_thuc_te_is_inside_p10_p90():
    f = reader.Forecast(p50=100.0, p10=60.0, p90=150.0)

    assert reader.forecast_hit(100.0, f) is True
    assert reader.forecast_hit(60.0, f) is True
    assert reader.forecast_hit(59.0, f) is False
    assert reader.forecast_hit(151.0, f) is False
    assert reader.forecast_hit(100.0, reader.Forecast(p50=100.0)) is None
    assert reader.forecast_hit(None, f) is None


def test_the_measurement_carries_du_kien_and_thuc_te():
    treated = _series(10.0, lift=1.2)
    pre_mean = sum(treated[T - timedelta(days=i)] for i in range(1, RUN + 1)) / RUN
    actual = pre_mean * 0.2
    forecast = reader.Forecast(p50=actual * 1.1, p10=actual * 0.5, p90=actual * 1.5)

    got = _measure(reader.SeriesBundle(treated, _controls(3), newest_day=END), forecast=forecast)

    assert got.expected_per_day == forecast.p50
    assert abs(got.actual_per_day - actual) < 1e-6
    assert got.forecast_hit is True
    body = got.to_json()
    assert (body["verdict_vi"], body["forecast_hit"], body["calibrates"]) == ("Tăng", True, True)


# --- calibration gate ---------------------------------------------------------------------


def test_a_high_tier_reading_on_stale_data_never_calibrates():
    stale = END - timedelta(days=5)  # the window's last days are missing, the sync stopped
    bundle = reader.SeriesBundle(_series(10.0, lift=1.2), _controls(3), newest_day=stale)

    got = _measure(bundle, today=END + timedelta(days=10))

    assert got.reading.confidence == "cao"
    assert got.fresh is False
    assert got.calibrates is False


def test_freshness_is_the_window_covered_or_the_expected_lag_plus_two():
    assert reader.is_fresh(END, END + timedelta(days=60), END, 2) is True
    assert reader.is_fresh(END - timedelta(days=4), END, END, 2) is True
    assert reader.is_fresh(END - timedelta(days=5), END, END, 2) is False
    assert reader.is_fresh(None, END, END, 2) is False


def test_only_medium_and_high_tiers_calibrate():
    assert reader.CALIBRATING_TIERS == frozenset({"cao", "trung_binh"})


# --- TikTok series source -----------------------------------------------------------------


@dataclass(frozen=True)
class _Row:
    start_date: date
    tiktok_product_id: str
    gmv: float


def test_tiktok_bundle_drops_uncovered_days_and_touched_products():
    first, last = T - timedelta(days=3), T + timedelta(days=3)
    gap = T + timedelta(days=2)
    rows = [
        _Row(d, pid, 10.0)
        for d in (first + timedelta(days=i) for i in range(7))
        if d != gap
        for pid in ("p", "c1", "c2")
    ]
    rows.remove(_Row(T + timedelta(days=1), "c2", 10.0))  # covered day, no sale: 0
    touched = {"c1": {T + timedelta(days=1)}, "p": {T - timedelta(days=1)}}

    got = gmv_bundle(rows, ["p"], first, last, touched=touched)

    assert gap in got.excluded
    assert T - timedelta(days=1) in got.excluded
    assert set(got.controls) == {"c2"}
    assert got.controls["c2"][T + timedelta(days=1)] == 0.0
    assert gap not in got.treated
    assert got.newest_day == last


def test_card_forecast_reads_p50_and_the_monthly_p10_p90():
    payload = json.dumps(
        {
            "diagnosis": {"recoverable_gmv_per_day": 70000},
            "gmv_estimate": {"per_month_min": 900000, "per_month_max": 3000000},
        }
    )

    assert card_forecast(payload) == reader.Forecast(p50=70000.0, p10=30000.0, p90=100000.0)
    assert card_forecast(None) == reader.Forecast()
    assert card_forecast("not json") == reader.Forecast()


# --- Shopee unchanged ---------------------------------------------------------------------


def test_shopee_reader_default_before_window_is_unchanged():
    treated, controls = _series(10.0, lift=1.2), _controls(3)

    default = impact.read_effect(treated, controls, T, post_days=14)
    explicit = impact.read_effect(treated, controls, T, post_days=14, pre_days=impact.PRE_DAYS)

    assert default == explicit
    assert default.pre_days_used == impact.PRE_DAYS
