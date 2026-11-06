"""P96e: the combo bug the owner hit on ORY (2026-11-06).

Two products, "Giá cố định" typed 10đ: the card showed Δ lợi nhuận −7.404.531.027đ on a ΔGMV of
+527.324đ -- the combo's margin RATIO (contribution ÷ a 10đ price) was multiplied by the scope's
GMV. Also: the typed price showed as "—" in Ops (the ``buyer_*`` mask), and a co-purchase partner
named "unknown" (order lines without an item id).
"""

from __future__ import annotations

from juli_backend.services.ops.masking import mask_pii
from juli_backend.services.shopee_builder import copurchase
from tests.unit.test_shopee_builder import one, shop  # noqa: F401  (fixture)

ITEMS = [{"item_id": "1001"}, {"item_id": "1002"}]


async def test_a_combo_price_under_1000d_is_refused_as_a_likely_percent(session, shop):  # noqa: F811
    v = await one(session, shop, kind="combo", items=ITEMS, pricing="fixed_price", value=10)
    assert v["ok"] is False and v["refusal"]["code"] == "combo_price_too_low"
    assert "% giảm" in v["refusal"]["message"]


async def test_a_combo_cannot_give_more_than_90_percent_off(session, shop):  # noqa: F811
    # list value 144.000đ today: 5.000đ is a 96 % cut, 140.000đ off is 97 %
    fixed = await one(session, shop, kind="combo", items=ITEMS, pricing="fixed_price", value=5_000)
    amount = await one(session, shop, kind="combo", items=ITEMS, pricing="amount", value=140_000)
    for v in (fixed, amount):
        assert v["ok"] is False and v["refusal"]["code"] == "combo_discount_over_max"
        assert "90%" in v["refusal"]["message"]


async def test_a_deep_combo_cannot_lose_more_than_its_combos_lose(session, shop):  # noqa: F811
    v = await one(session, shop, kind="combo", items=ITEMS, pricing="pct", value=85)
    assert v["ok"]
    d = v["details"]
    per_combo = d["contribution"]  # negative: sold below cost
    assert per_combo < 0
    # extra combos are the predicted ΔGMV in combos at today's value; each loses ``per_combo``
    worst_combos = v["delta"]["gmv"]["high"] / d["value_now"]
    floor = worst_combos * per_combo - v["cost"]["amount"]
    assert v["delta"]["profit"]["low"] >= floor - 1


async def test_bands_per_order_run_low_to_high(session, shop):  # noqa: F811
    v = await one(session, shop, kind="combo", items=ITEMS, pricing="pct", value=85)
    band = v["delta"]["per_order"]["profit"]
    assert band["low"] <= band["p50"] <= band["high"]


async def test_the_combo_price_survives_the_ops_buyer_mask(session, shop):  # noqa: F811
    v = await one(session, shop, kind="combo", items=ITEMS, pricing="fixed_price", value=120_000)
    masked = mask_pii(v)
    assert masked["details"]["combo_price"] == 120_000


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
