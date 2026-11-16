"""F10 Đo lường: run-day window, verdict, forecast check, calibration gate, ads CPA read-back."""

from __future__ import annotations

from datetime import date

from juli_backend.services.card_measure import reader
from juli_backend.services.shopee_recommendations import ads_readback as ar
from juli_backend.services.shopee_recommendations import impact, verdict
from juli_backend.services.shopee_recommendations.learning import Observation, calibrate

T = date(2026, 11, 1)
HIST = [100.0, 104.0, 96.0, 101.0, 99.0, 103.0, 97.0, 100.0, 102.0, 98.0] * 3  # band ~2 %


def _reading(pct, incr, conf="cao", pre=100.0):
    return impact.Reading(conf, None, pre, pre + incr, pre, incr, pct, 0.01, False)


def _block(gmv=(1000.0, 2000.0, 3000.0), profit=(100.0, 200.0, 300.0), days=14):
    delta = {
        "gmv": dict(zip(("p10", "p50", "p90"), gmv)),
        "profit": None if profit is None else dict(zip(("p10", "p50", "p90"), profit)),
    }
    return {"estimable": True, "own": {"days": days, "delta": delta}}


def _meas(reading, metric="gmv", fresh=True, band=2.0):
    """What ``card_measure.reader.measure`` returns for this reading."""
    return reader.Measurement(
        "shopee", metric, 14, reading, band, reader.verdict_of(reading, band), None, None, None,
        fresh, fresh and reading.confidence in reader.CALIBRATING_TIERS,
    )  # fmt: skip


def _m(reading, block, days=14, gmv_reading=None, metric="gmv", stale=False):
    gmv_m = None if gmv_reading is None else _meas(gmv_reading)
    return verdict.payload(_meas(reading, metric, not stale), gmv_m, block=block, days=days, t=T)


def test_window_is_the_run_days():
    w = verdict.run_window(T, 28)
    assert (w["days"], w["from"], w["to"]) == (28, "2026-11-02", "2026-11-29")
    assert w["label"] == "Chạy và đo 28 ngày"
    assert (
        verdict.run_days(
            {"version": 1, "versions": [{"version": 1, "result": _block(days=21)}]}, 14
        )
        == 21
    )
    assert verdict.run_days({}, 14) == 14


def test_verdict_inside_and_outside_the_band():
    flat = _m(_reading(0.005, 0.5), _block())
    assert flat["verdict"] == "khong_doi" and flat["within_band"] is True
    up = _m(_reading(0.20, 20.0), _block())
    assert up["verdict"] == "tang" and up["verdict_label"] == "Tăng"
    down = _m(_reading(-0.20, -20.0), _block())
    assert down["verdict"] == "giam"


def test_profit_basis_when_known_else_gmv():
    with_profit = _m(_reading(0.2, 20.0), _block())
    assert with_profit["basis"] == "profit"
    assert with_profit["actual"] == 20.0 * 14 * 0.1  # incremental GMV x profit per GMV
    no_profit = _m(_reading(0.2, 20.0), _block(profit=None))
    assert no_profit["basis"] == "gmv" and no_profit["actual"] == 280.0


def test_no_estimate_card_still_gets_a_verdict_on_its_metric():
    m = _m(_reading(0.30, 0.0), None, metric="ctr")
    assert m["estimated"] is False and m["basis"] == "metric"
    assert m["verdict"] == "tang" and m["expected"] is None and m["forecast_ok"] is None


def test_forecast_check_inside_frozen_p10_p90():
    ok = _m(_reading(0.2, 20.0), _block(profit=None))  # 280 vs 14-day P50 2000 (1000-3000)
    assert ok["expected"] == 2000.0 and ok["forecast_ok"] is False
    assert ok["difference"] == 280.0 - 2000.0
    hit = _m(_reading(0.2, 100.0), _block(profit=None))  # 1400 inside 1000-3000
    assert hit["forecast_ok"] is True


def test_lowest_tier_and_stale_runs_do_not_calibrate():
    assert _m(_reading(0.2, 20.0, "thap"), _block())["calibrates"] is False
    assert _m(_reading(0.2, 20.0, "thap"), _block())["calibration_skip"] == "lowest_tier"
    stale = _m(_reading(0.2, 20.0, "cao"), _block(), stale=True)
    assert stale["calibrates"] is False and stale["calibration_skip"] == "stale_run"
    assert _m(_reading(0.2, 20.0, "trung_binh"), _block())["calibrates"] is True

    def obs(tier, fresh):
        return Observation("price", "gmv", 0.0, 0.2, 0.1, 0.01, tier=tier, fresh=fresh)

    kinds = {("price", "gmv")}
    for tier, fresh, n in (("cao", True, 1), ("thap", True, 0), ("cao", False, 0), ("", True, 1)):
        state = calibrate([obs(tier, fresh)])
        assert kinds == set(state) and state[("price", "gmv")].n_results == n


def test_freshness_is_the_shared_f2_rule():
    end = date(2026, 11, 15)
    assert reader.is_fresh(end, end, end, 0) is True
    assert reader.is_fresh(date(2026, 11, 10), date(2026, 11, 20), end, 0) is False
    assert reader.is_fresh(None, end, end, 0) is False


def test_ads_cpa_read_back_against_prediction():
    rows = [
        ar.DayRow(date(2026, 11, 3), 100.0, 500.0, 2.0),
        ar.DayRow(date(2026, 11, 4), 200.0, 700.0, 2.0),
    ]
    actual = ar.read_actual(rows, date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 10))
    assert actual["cpa"] == 75.0 and actual["roas"] == 1200.0 / 300.0
    block = {
        "cost_total": 400.0,
        "option": {"ads": {
            "spend": {"after": 400.0}, "orders": {"after": 4.0}, "cpa": {"after": 100.0},
            "roas_shopee": {"after": 3.0}, "break_even_cpa": 90.0,
        }},
    }  # fmt: skip
    by = {r["key"]: r for r in verdict.ads_rows(block, actual)}
    assert (by["spend"]["expected"], by["spend"]["actual"]) == (400.0, 300.0)
    assert (by["cpa"]["expected"], by["cpa"]["actual"], by["cpa"]["difference"]) == (
        100.0,
        75.0,
        -25.0,
    )
    assert by["cpa_break_even"]["expected"] == 90.0 and by["cpa_break_even"]["verdict"] == "tang"
    empty = {
        r["key"]: r
        for r in verdict.ads_rows(
            block, ar.read_actual([], date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 10))
        )
    }
    assert empty["cpa"]["actual"] is None and empty["spend"]["actual"] is None


def test_running_campaign_edit_is_measured_on_spend_gmv_orders_cpa():
    rows = verdict.campaign_rows(
        {
            "option": {
                "ads": {
                    "spend": {"after": 700.0},
                    "orders": {"after": 7.0},
                    "cpa": {"after": 100.0},
                }
            }
        },
        {"spend": 50.0, "gmv": 200.0, "orders": 1.0},
        {"spend": 100.0, "gmv": 500.0, "orders": 2.0},
        7,
    )
    by = {r["key"]: r for r in rows}
    assert set(by) == {"spend", "gmv", "orders", "cpa"}
    assert (by["spend"]["before"], by["spend"]["actual"]) == (350.0, 700.0)
    assert (by["cpa"]["before"], by["cpa"]["actual"]) == (50.0, 50.0)
