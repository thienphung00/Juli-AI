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
    # P100-C (B.10): the seeded shop has too few orders to measure who moves up to the tier, so
    # the card has no ΔGMV / Δ profit estimate -- the loss shows through what is certain: the
    # combos already bought lose money, every order at the tier loses money, and the result
    # carries the cost and a break-even
    d = v["delta"]
    assert d["profit"]["p50"] is None
    existing = v["cost"]["existing"]
    assert existing > 0
    # the P96e bug: the loss is the combos' own discount, never a ratio times the scope's GMV
    assert -existing <= d["certain_profit"] < 0
    band = d["per_order"]["profit"]
    assert band["low"] <= band["p50"] <= band["high"] < 0
    r = v["result"]
    assert r["estimable"] is False
    assert r["cost"]["total"] > 0 and r["cost"]["break_even_orders"] is not None


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
