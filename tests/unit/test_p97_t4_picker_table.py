"""P97 D85.12: the picker rows carry what the table filters need (ngành hàng, biên, CTOR,
có đề xuất, đang chạy QC / KOL). SQLite, synthetic reco shop."""

# ruff: noqa: F811
from __future__ import annotations

from tests.support.shopee_reco import AS_OF
from tests.unit.test_shopee_builder import builder, shop  # noqa: F401

COLUMNS = (
    "category",
    "category_path",
    "margin_pct",
    "ctor_30d",
    "ctor_prev_30d",
    "ctor_down",
    "has_proposal",
    "in_ads",
    "in_kol",
)


async def test_every_row_has_the_filter_columns(session, shop):
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    assert out["products"]
    for row in out["products"]:
        for col in COLUMNS:
            assert col in row, col
        assert isinstance(row["has_proposal"], bool)
        assert isinstance(row["in_ads"], bool)
        assert isinstance(row["in_kol"], bool)


async def test_a_product_with_orders_has_a_margin_and_one_without_stays_unknown(session, shop):
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    sold = [r for r in out["products"] if r["orders_30d"] > 0 and r["has_cost"]]
    assert sold and all(r["margin_pct"] is not None for r in sold)
    unsold = [r for r in out["products"] if r["orders_30d"] == 0]
    assert all(r["margin_pct"] is None and r["ctor_down"] is None for r in unsold)


async def test_the_proposals_column_follows_the_cards_waiting_for_a_decision(session, shop):
    from juli_backend.models.shop_proposals import ShopProposal
    from tests.unit.test_shopee_builder import select

    rows = (await session.scalars(select(ShopProposal))).all()
    waiting = {p.item_id for p in rows if p.status in ("sent", "changes_requested") and p.item_id}
    out = await builder.products(session, shop.shop_id, as_of=AS_OF)
    flagged = {r["item_id"] for r in out["products"] if r["has_proposal"]}
    assert flagged == waiting & {r["item_id"] for r in out["products"]}
