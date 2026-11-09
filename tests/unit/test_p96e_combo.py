"""P96e: the combo bug the owner hit on ORY (2026-11-06).

Two products, "Giá cố định" typed 10đ: the card showed Δ lợi nhuận −7.404.531.027đ on a ΔGMV of
+527.324đ -- the combo's margin RATIO (contribution ÷ a 10đ price) was multiplied by the scope's
GMV. Also: the typed price showed as "—" in Ops (the ``buyer_*`` mask), and a co-purchase partner
named "unknown" (order lines without an item id).
"""

from __future__ import annotations

import pytest

from juli_backend.services.shopee_builder import copurchase
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.test_shopee_builder import one

ITEMS = ["1001", "1002"]
TIER = [{"qty": 2, "value": 10}]


@pytest.fixture
async def shop(session):
    """Synthetic reco shop. Owned here so this file does not import a ``shop`` name.

    Importing the fixture and requesting it by the same name needed F401 and F811
    suppressions, and those new suppressions failed the deploy ratchet.
    """
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


async def test_a_combo_price_under_1000d_is_refused_as_a_likely_percent(session, shop):
    # P97: the same guard in Shopee's "giá đặc biệt": 10đ for two products is a % typed wrongly
    v = await one(
        session,
        shop,
        kind="combo",
        item_ids=ITEMS,
        discount_type="special_price",
        tiers=[{"qty": 2, "value": 10}],
    )
    assert v["ok"] is False and v["refusal"]["code"] == "combo_price_too_low"
    assert "% giảm" in v["refusal"]["message"]


async def test_a_combo_cannot_give_more_than_90_percent_off(session, shop):
    # two products at about 79.000đ each: a 5.000đ price is a 97 % cut, 150.000đ off is 95 %
    fixed = await one(
        session,
        shop,
        kind="combo",
        item_ids=ITEMS,
        discount_type="special_price",
        tiers=[{"qty": 2, "value": 5_000}],
    )
    amount = await one(
        session,
        shop,
        kind="combo",
        item_ids=ITEMS,
        discount_type="amount",
        tiers=[{"qty": 2, "value": 150_000}],
    )
    for v in (fixed, amount):
        assert v["ok"] is False and v["refusal"]["code"] == "combo_discount_over_max"
        assert "90%" in v["refusal"]["message"]


async def test_a_deep_combo_cannot_lose_more_than_its_combos_lose(session, shop):
    v = await one(
        session,
        shop,
        kind="combo",
        item_ids=ITEMS,
        discount_type="pct",
        tiers=[{"qty": 2, "value": 85}],
    )
    assert v["ok"]
    margin = v["details"]["tiers"][0]["margin_pct"]
    assert margin is not None and margin < 0  # sold below cost
    profit = v["delta"]["profit"]
    assert profit["low"] <= profit["p50"] <= profit["high"] and profit["p50"] < 0


async def test_bands_per_order_run_low_to_high(session, shop):
    v = await one(
        session,
        shop,
        kind="combo",
        item_ids=ITEMS,
        discount_type="pct",
        tiers=[{"qty": 2, "value": 85}],
    )
    band = v["delta"]["per_order"]["profit"]
    assert band["low"] <= band["p50"] <= band["high"]


def test_co_purchase_never_suggests_a_line_without_an_item_id_and_labels_unnamed_ones():
    sets = [{"A", "unknown", "B"}, {"A", "unknown", "B"}, {"A", ""}, {"A", ""}]
    out = copurchase.suggestions(sets, "A", names={})
    ids = [r["item_id"] for r in out["suggestions"]]
    assert ids == ["B"]
    assert out["suggestions"][0]["name"] == "Sản phẩm đã ẩn/không còn bán (id B)"


def test_a_set_sold_far_below_cost_cannot_lose_more_than_its_extra_gmv():
    from juli_backend.services.shopee_builder import outcome

    band = outcome.set_profit_band(
        {"low": 10_000.0, "p50": 20_000.0, "high": 30_000.0},
        [{"pack_count": 3, "margin_pct": -1_404_170.0}],
    )
    assert band["low"] is not None and band["low"] >= -30_000.0
