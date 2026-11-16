"""Forecast grill F2/F3/F5/F6/F8/F9 on the TikTok engine (2026-11-16).

Pure tests, plus two SQLite tests at the end (the own-rung loader and the pooled kind
filter); the Postgres function filter is migration 132.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.forecast.noise import NON_UPLIFT_KINDS, period_band
from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.forecast import (
    CardForecast,
    card_forecast,
    daily_history,
    effect_within_noise,
    is_stale,
    noise_band_for_card,
)
from juli_backend.services.optimize_product.prediction import (
    MIN_POOLED_RESULTS,
    CalibrationStats,
    Prediction,
    blended_factor,
    predict,
)
from juli_backend.services.optimize_product.tunables import (
    FORECAST_STALE_GRACE_DAYS,
    TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS,
)
from juli_backend.services.optimize_product.volatility import window_counts

AS_OF = date(2026, 11, 14)


def _pred(low: float, high: float, source: str = "prior", p50: float | None = None) -> Prediction:
    return Prediction(
        lever="title",
        gap_bucket="unknown",
        lift_low=low,
        lift_high=high,
        factor=1.0,
        source=source,
        lift_p50=p50,
    )


def _days(n: int, *, orders: int = 4, gmv: int = 400_000, start: date = AS_OF) -> list[ProductDay]:
    return [
        ProductDay(
            day=start - timedelta(days=i),
            impressions=Decimal(1000 + 37 * (i % 5)),
            clicks=Decimal(50 + (i % 3)),
            sku_orders=Decimal(orders + (i % 2)),
            gmv=Decimal(gmv + 10_000 * (i % 4)),
        )
        for i in range(n)
    ]


# --------------------------------------------------------------------------- F2 freshness


def test_tiktok_lag_two_data_is_not_stale():
    # Sandbox probe 16/11: latest_available_date 14/11 -- the routine lag.
    assert TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS == 2 and FORECAST_STALE_GRACE_DAYS == 2
    today = date(2026, 11, 16)
    assert is_stale(date(2026, 11, 14), today) is False
    # Lag + grace (4 days) is still fresh; one more day is stale.
    assert is_stale(date(2026, 11, 12), today) is False
    assert is_stale(date(2026, 11, 11), today) is True
    # No wall clock: never stale.
    assert is_stale(date(2020, 1, 1), None) is False


def test_stale_card_has_no_numbers_and_carries_data_through():
    f = card_forecast(
        _pred(0.04, 0.20),
        target_metric="ctr",
        data_through=date(2026, 11, 1),
        today=date(2026, 11, 16),
        gmv_per_day=1_000_000,
        aov=100_000,
        histories={},
    )
    body = f.to_json()
    assert f.stale is True
    assert body["stale"] == {"data_through": "2026-11-01"}
    assert body["gmv_per_month"] is None and body["orders_per_month"] is None
    assert body["target_lift"] is None and body["profit_per_month"] is None


def test_out_of_stock_days_are_left_out_of_the_base_not_zero():
    rows = _days(14, orders=4, gmv=400_000)
    full = window_counts(rows, AS_OF, 14)
    gone = [
        ProductDay(day=r.day, available=False) if r.day > AS_OF - timedelta(days=4) else r
        for r in rows
    ]
    zeroed = [ProductDay(day=r.day) if r.day > AS_OF - timedelta(days=4) else r for r in rows]
    excluded = window_counts(gone, AS_OF, 14)
    as_zero = window_counts(zeroed, AS_OF, 14)
    assert excluded.days == 10 and len(excluded.daily) == 10
    # Excluded: GMV/day stays near the selling level; a zero day would drag it down.
    assert excluded.value("gmv") == pytest.approx(sum(float(r.gmv) for r in rows[4:]) / 10)
    assert as_zero.value("gmv") < excluded.value("gmv") <= full.value("gmv") * 1.1
    # Unknown availability (None, the default) keeps the day.
    assert window_counts(rows, AS_OF, 14).days == 14


def test_days_after_data_through_are_never_read():
    rows = _days(14) + [ProductDay(day=AS_OF + timedelta(days=1), gmv=Decimal(10**9))]
    counts = window_counts(rows, AS_OF, 14)
    assert counts.gmv == pytest.approx(sum(float(r.gmv) for r in rows[:14]))


# --------------------------------------------------------------------------- F3 seam


def test_noise_band_seam_is_the_shared_period_band():
    params = list(inspect.signature(noise_band_for_card).parameters)
    assert params == ["totals_by_window", "window_days"]
    rows = _days(30)
    gmv = daily_history(rows, as_of=AS_OF, metric="gmv", window_days=14)
    assert len(gmv) == 14 and all(v is not None for v in gmv)
    assert noise_band_for_card(gmv, 14) == period_band(gmv, 14).band_pct
    orders = daily_history(rows, as_of=AS_OF, metric="orders", window_days=14)
    assert noise_band_for_card(orders, 14) == period_band(orders, 14).band_pct
    # Flat history: the 1 % minimum; no history: no band.
    assert noise_band_for_card([5.0] * 14, 14) == pytest.approx(1.0)
    assert noise_band_for_card([None, None], 14) is None


def test_daily_history_marks_missing_and_unavailable_days_none():
    rows = [
        ProductDay(day=AS_OF, clicks=Decimal(10), sku_orders=Decimal(2), gmv=Decimal(200)),
        ProductDay(day=AS_OF - timedelta(days=1), gmv=Decimal(500), available=False),
        ProductDay(day=AS_OF - timedelta(days=3), clicks=Decimal(0)),
    ]
    assert daily_history(rows, as_of=AS_OF, metric="gmv", window_days=4) == [
        0.0,
        None,
        None,
        200.0,
    ]
    # A ratio without its denominator is None, not 0.
    assert daily_history(rows, as_of=AS_OF, metric="ctor", window_days=4) == [
        None,
        None,
        None,
        0.2,
    ]


# --------------------------------------------------------------------------- F5 within noise


FLAT = [100.0] * 14  # band = the 1 % minimum
NOISY = [0.0, 200.0] * 7  # band ~ 36 % of the period total


def test_effect_within_noise_uses_the_shared_rule():
    assert effect_within_noise(0.005, FLAT, 14, "title") is True
    assert effect_within_noise(0.04, FLAT, 14, "title") is False
    assert effect_within_noise(0.04, NOISY, 14, "title") is True
    assert effect_within_noise(0.0, [], 14, "title") is False  # no band: not within noise
    # A non-uplift kind follows its own rule (shared NON_UPLIFT_KINDS).
    assert "listing_hide" in NON_UPLIFT_KINDS
    assert effect_within_noise(0.0, NOISY, 14, "listing_hide") is False


def test_within_noise_metric_is_null_but_the_card_keeps_its_other_numbers():
    f = card_forecast(
        _pred(0.0, 0.04, p50=0.02),
        target_metric="ctr",
        data_through=AS_OF,
        today=date(2026, 11, 16),
        gmv_per_day=1_000_000,
        aov=100_000,
        histories={"ctr": FLAT, "orders": NOISY, "gmv": FLAT},
        kind="title",
    )
    # P90 4 % >= the 1 % CTR / GMV bands: shown; orders' ~36 % band: "—".
    assert f.target_lift == pytest.approx(0.02)
    assert f.gmv_per_month == pytest.approx(600_000)
    assert f.orders_per_month is None
    assert f.stale is False


# --------------------------------------------------------------------------- F6 ladder


def test_ladder_own_then_shop_then_pooled_then_prior():
    pooled = CalibrationStats(coefficient=1.0, results=10)
    shop = CalibrationStats(coefficient=0.25, results=5)
    own = CalibrationStats(coefficient=0.75, results=2)
    assert blended_factor(None, None) == (1.0, "prior")
    assert blended_factor(None, pooled)[1] == "pooled"
    assert blended_factor(shop, pooled)[1] == "shop"
    factor, source = blended_factor(shop, pooled, own)
    assert source == "own"
    # Own shrinks toward the shop rung below it: 2 / (2 + 5) of the way to 1.5.
    shop_factor = blended_factor(shop, pooled)[0]
    assert factor == pytest.approx(shop_factor + 2 / 7 * (1.5 - shop_factor))


def test_pooled_needs_five_results_and_shop_needs_five():
    thin = CalibrationStats(coefficient=1.0, results=MIN_POOLED_RESULTS - 1)
    assert blended_factor(None, thin) == (1.0, "prior")
    few_shop = CalibrationStats(coefficient=1.0, results=4)
    assert blended_factor(few_shop, None) == (1.0, "prior")


def test_prediction_records_the_rung_and_only_prior_is_floored():
    assert predict("title", 5).source == "prior"
    own = predict("title", 5, own=CalibrationStats(coefficient=0.5, results=1))
    assert own.source == "own" and own.lift_p50 is None
    assert own.to_json()["source"] == "own"


# --------------------------------------------------------------------------- F8 / F9


def test_orders_and_gmv_come_from_one_scenario_and_add_up():
    f = card_forecast(
        _pred(0.02, 0.18, p50=0.10),
        target_metric="ctor",
        data_through=AS_OF,
        today=AS_OF,
        gmv_per_day=2_000_000,
        aov=250_000,
        histories={"ctor": FLAT, "orders": FLAT, "gmv": FLAT},
    )
    assert f.gmv_per_month == pytest.approx(2_000_000 * 0.10 * 30)
    assert f.orders_per_month is not None and f.gmv_per_month is not None
    assert f.orders_per_month * 250_000 == pytest.approx(f.gmv_per_month)


def test_aov_lever_moves_gmv_not_orders():
    f = card_forecast(
        _pred(0.03, 0.10),
        target_metric="aov",
        data_through=AS_OF,
        today=AS_OF,
        gmv_per_day=1_000_000,
        aov=200_000,
        histories={"aov": FLAT, "orders": FLAT, "gmv": FLAT},
    )
    assert f.gmv_per_month == pytest.approx(1_000_000 * 0.065 * 30)
    # Δorders 0 is within any band: "—".
    assert f.orders_per_month is None


def test_tiktok_profit_is_null_and_the_payload_is_additive():
    f = CardForecast(
        data_through=AS_OF,
        stale=False,
        source="pooled",
        target_metric="ctr",
        target_lift=0.05,
        orders_per_month=3.333,
        gmv_per_month=123_456.7,
    )
    body = f.to_json()
    assert body["profit_per_month"] is None
    assert body["stale"] is None and body["source"] == "pooled"
    assert body["scenario"] == "gmv_p50"
    assert body["orders_per_month"] == 3.33 and body["gmv_per_month"] == 123_457


# --------------------------------------------------------------------------- with the DB (SQLite)


async def _pool(session, shop_id) -> None:
    from juli_backend.services.consent import grant_consent

    await grant_consent(
        session,
        shop_id,
        scope="pooled_training",
        method="contract_paper",
        terms_version="synthetic-terms-01",
        evidence_ref="synthetic/contract.pdf",
        granted_by="Synthetic Director",
        granted_at=datetime(2026, 11, 1),
    )


@pytest.mark.asyncio
async def test_pooled_rung_excludes_sample_and_sandbox_shops(session):
    from juli_backend.models.lever_flows import LeverCalibration
    from juli_backend.services.lever_flows.measurement import fleet_calibration_stats
    from tests.support.builders import make_tenant

    real = [(await make_tenant(session))[1] for _ in range(5)]
    sandbox = (await make_tenant(session, kind="sandbox"))[1]
    sample = (await make_tenant(session, kind="sample"))[1]
    for shop in (*real, sandbox, sample):
        await _pool(session, shop.id)
    for shop in real:
        session.add(_calibration(LeverCalibration, shop.id, "0.5", 4))
    for shop in (sandbox, sample):
        session.add(_calibration(LeverCalibration, shop.id, "1.9", 50))  # would dominate
    await session.flush()
    fleet = await fleet_calibration_stats(session)
    assert fleet["cover_image"] == (Decimal("0.5"), 20)


@pytest.mark.asyncio
async def test_own_rung_reads_this_products_measured_results(session):
    from juli_backend.models.lever_flows import RunMeasurementFinal
    from juli_backend.services.action_cards.optimize_product_cards import own_calibration
    from tests.support.builders import make_product, make_tenant, make_workflow_run

    _, shop = await make_tenant(session)
    product = await make_product(session, shop, tiktok_product_id="tt-1")
    other = await make_product(session, shop, tiktok_product_id="tt-2")
    for i, (pct, label, prod) in enumerate(
        (
            (120, "dat", product),
            (60, "dat", product),
            (None, "chua_ket_luan", product),  # no verdict: not a result
            (300, "dat", other),  # clamped to 2
        )
    ):
        run = await make_workflow_run(session, shop, product=prod, subject_ref=f"run-{i}")
        session.add(
            RunMeasurementFinal(
                shop_id=shop.id,
                workflow_run_id=run.id,
                lever="title",
                label=label,
                pct_of_expected=pct,
            )
        )
    await session.flush()
    own = await own_calibration(session, shop.id)
    assert own[("tt-1", "title")] == CalibrationStats(pytest.approx(0.9), 2)
    assert own[("tt-2", "title")] == CalibrationStats(2.0, 1)
    assert ("tt-1", "cover_image") not in own


def _calibration(model, shop_id, coefficient: str, readings: int, lever: str = "cover_image"):
    return model(
        shop_id=shop_id,
        lever=lever,
        coefficient=Decimal(coefficient),
        readings=readings,
        updated_at=datetime(2026, 11, 1),
    )
