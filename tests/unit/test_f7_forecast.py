"""F7.1 / F7.2 / F7.4: ``forecast.metrics`` (hiện tại / dự kiến / Δ / band, per metric, over the
card's own days), the card's 7-day base, and ``data_through`` in the freshness check.
Made-up figures only."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder.engine.contract import MarginBasis
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_recommendations import (
    forecast,
    freshness,
    result_store,
    stale,
    store,
)
from juli_backend.services.shopee_recommendations import service as reco
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_funnel_engine import simple_base, voucher_option
from tests.unit.test_p98_plan_results import result
from tests.unit.test_p100_one_number import VOUCHER, _choose
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW

KINDS = (
    "voucher",
    "product_discount",
    "program",
    "flash_sale",
    "combo",
    "deal_soc",
    "gift",
    "affiliate_invite",
    "ads",
    "title",
    "cover_image",
)


@pytest.mark.parametrize("kind", KINDS)
def test_du_kien_is_hien_tai_plus_delta_for_every_kind(kind):
    r = dataclasses.replace(
        result(1_000_000, 10, 300_000, lo=100_000, hi=500_000, days=7), kind=kind
    )
    m = forecast.forecast_of(r, reason=None, data_through=date(2026, 10, 7))["metrics"]
    assert set(m) == {"profit", "gmv", "orders", "aov", "margin_pct"}
    for name in ("profit", "gmv", "orders", "aov"):
        b = m[name]
        assert b["days"] == 7
        assert b["du_kien"] == pytest.approx(b["hien_tai"] + b["delta"])
        assert b["low"] <= b["du_kien"] <= b["high"]
    assert m["profit"]["hien_tai"] == 2_000_000
    assert m["profit"]["delta"] == 300_000
    assert m["profit"]["du_kien"] == 2_300_000
    assert (m["profit"]["low"], m["profit"]["high"]) == (2_100_000, 2_500_000)
    assert m["profit"]["delta_pct"] == pytest.approx(15.0)
    assert m["orders"]["du_kien"] == 110
    assert m["aov"]["hien_tai"] == pytest.approx(100_000)
    assert m["aov"]["du_kien"] == pytest.approx(11_000_000 / 110)


def test_margin_pct_is_profit_over_net_revenue_in_points():
    r = dataclasses.replace(
        result(1_000_000, 10, 300_000, days=7),
        margin_basis=MarginBasis(profit=D(2_000_000), net_revenue=D(8_000_000), gmv=D(10_000_000)),
    )
    mg = forecast.metrics_of_result(r)["margin_pct"]
    assert mg["hien_tai"] == pytest.approx(25.0)
    # R after = 11M x 0.8 = 8.8M; profit after = 2M + 0.3M
    assert mg["du_kien"] == pytest.approx(2_300_000 / 8_800_000 * 100, abs=0.06)
    assert mg["delta"] == pytest.approx(mg["du_kien"] - mg["hien_tai"])
    assert mg["delta_pct"] is None


def test_no_estimate_keeps_hien_tai_and_carries_a_reason_code():
    r = result(0, 0, None, days=7, estimable=False)
    f = forecast.forecast_of(r, reason=None, data_through=date(2026, 10, 7))
    assert f["estimable"] is False and f["reason_code"] and f["reason_text"]
    p = f["metrics"]["profit"]
    assert p["hien_tai"] == 2_000_000 and p["du_kien"] is None and p["delta"] is None
    none = forecast.forecast_of(None, reason="no_spec", data_through=None)
    assert none["reason_code"] == "no_spec" and none["metrics"]["gmv"]["hien_tai"] is None


def test_the_base_is_the_cards_own_days_not_the_30_day_total():
    base = simple_base()  # 30 days, profit 5.000.000
    r7 = run(base, voucher_option(days=7), seed=1, n=200)
    r14 = run(base, voucher_option(days=14), seed=1, n=200)
    m7 = forecast.metrics_of_result(r7)
    assert m7["profit"]["days"] == 7
    assert m7["profit"]["hien_tai"] == pytest.approx(5_000_000 / 30 * 7, rel=1e-6)
    assert m7["gmv"]["hien_tai"] == pytest.approx(25_000_000 / 30 * 7, rel=1e-6)
    m14 = forecast.metrics_of_result(r14)
    assert m14["profit"]["hien_tai"] == pytest.approx(5_000_000 / 30 * 14, rel=1e-6)


def test_the_stored_block_carries_forecast_and_data_through():
    r = result(1_000_000, 10, 300_000, days=7)
    block = result_store.block_of(
        r, reason=None, start=date(2026, 10, 8), targets=None, as_of=date(2026, 10, 7),
        now=NOW, hash_="h",
    )  # fmt: skip
    assert block["data_through"] == "2026-10-07"
    assert block["forecast"]["data_through"] == "2026-10-07"
    assert block["forecast"]["metrics"]["profit"]["du_kien"] == 2_300_000
    card = {"result": None}
    result_store._lay_forecast(card, block)
    assert card["forecast"] is block["forecast"] and card["data_through"] == "2026-10-07"
    miss = result_store.missing_block()
    assert miss["forecast"]["reason_code"] == result_store.NOT_COMPUTED


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


async def test_a_new_data_day_makes_the_card_and_its_result_stale(session, shop):
    seeded, env = shop
    card_id = await _choose(session, seeded, VOUCHER)
    card = await store.card_payload(session, seeded.shop_id, card_id)
    block = result_store.version_result(card, 1)
    assert block["forecast"]["data_through"] == AS_OF.isoformat()
    assert card["forecast"]["metrics"]["profit"]["days"] == block["own"]["days"]
    assert freshness.stale_reason(card, env) is None
    assert result_store.is_fresh(block, env, card)
    later = dataclasses.replace(env, as_of=AS_OF + timedelta(days=1))
    # a moved data day never makes the CARD stale (no re-version / re-send) ...
    assert freshness.stale_reason(card, later) is None
    assert freshness.card_stale_reason(card, later) is None
    # ... it only re-forecasts the stored result
    assert not result_store.is_fresh(block, later, card)
    prop = await session.get(ShopProposal, card_id)
    listed = reco._summary(prop, card)
    assert listed["forecast"] == block["forecast"]
    assert listed["data_through"] == AS_OF.isoformat()
    # the morning refresh re-forecasts the result; it does not re-issue or re-send the card
    got = await stale.mark_stale_by_freshness(session, seeded.shop_id, later, now=NOW)
    assert got["flagged"] == 0
    counts = await result_store.refresh_shop(session, seeded.shop_id, later, now=NOW)
    assert counts.updated >= 1
    card = await store.card_payload(session, seeded.shop_id, card_id)
    assert card["forecast"]["data_through"] == later.as_of.isoformat()
