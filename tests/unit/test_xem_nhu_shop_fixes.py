"""Regression tests for the "Xem như shop" sweep of 2026-11-05 (V1-V6, V10). Synthetic data."""

from __future__ import annotations

from datetime import timedelta

import pytest

from juli_backend.services.ops.masking import mask_pii
from juli_backend.services.shop_keywords.decompose import Title, decompose
from juli_backend.services.shopee_analytics import loaders, queries
from juli_backend.services.shopee_analytics.catalog import ItemInfo, Variation
from juli_backend.services.shopee_analytics.product import header_sku
from tests.support.shopee_analytics import (
    CUR_END,
    PREV_END,
    PREV_START,
    Seeded,
    _daily,
    seed_shopee_shop,
)


@pytest.fixture
async def seeded(session) -> Seeded:
    return await seed_shopee_shop(session)


async def test_v1_the_order_amount_key_is_not_a_masked_buyer_key(session, seeded):
    body = await queries.orders(session, seeded.shop_id, period="7d", as_of=CUR_END)
    row = body["orders"][0]
    assert "buyer_paid" not in row and isinstance(row["paid_amount"], (int, float))
    assert mask_pii(row)["paid_amount"] == row["paid_amount"]


async def test_v2_a_thin_previous_period_withholds_every_delta(session, seeded):
    # one stray old line keeps the export bounds bracketing the previous window
    keep = next(ln for ln in seeded.lines if ln.ordered_at.date() == PREV_START)
    for ln in [x for x in seeded.lines if x.ordered_at.date() <= PREV_END and x is not keep]:
        await session.delete(ln)
    await session.flush()
    body = await queries.overview(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert body["five_numbers"]["comparison"]["available"] is False
    assert body["kpi_strip"]["margin_pct"]["previous"] is None
    assert any(w["code"] == "previous_period_thin" for w in body["warnings"])
    assert "kỳ trước chưa đủ dữ liệu" in body["warnings"][-1]["message"].lower()


async def test_v3_the_window_ends_on_the_last_day_every_live_dataset_posted(session):
    """D85.2 (replaces V3's "newest Connector day"): the shared anchor is the last COMPLETE day.
    A dataset a day or two behind holds the window back and is named; one more than three days
    behind is a stale upload and no longer counts. (The raw datasets' rule: no stored rows.)"""
    seeded = await seed_shopee_shop(session, materialized=False)
    assert await loaders.default_as_of(session, seeded.shop_id) == CUR_END
    later = CUR_END + timedelta(days=2)
    session.add(_daily(seeded.shop_id, later, "total", "all", orders=1, gmv=1))
    await session.flush()
    anchor = await loaders.load_anchor(session, seeded.shop_id)
    assert anchor is not None and anchor.day == CUR_END and anchor.newest == later
    assert anchor.limited_by == "shop_overview"
    assert "shop_overview" in anchor.label() and "07/10/2026" in anchor.label()
    much_later = CUR_END + timedelta(days=6)
    session.add(_daily(seeded.shop_id, much_later, "total", "all", orders=1, gmv=1))
    await session.flush()
    anchor = await loaders.load_anchor(session, seeded.shop_id)
    assert anchor is not None and anchor.day == much_later
    assert anchor.stale == ("shop_overview",)


def test_v5_a_sku_of_another_listing_is_not_the_header_sku():
    gloves = ItemInfo(
        item_id="1",
        seller_sku="1000",
        variations=(Variation("a", "x3", "G500002"), Variation("b", "x5", "G500003")),
    )
    assert header_sku(gloves, {"1000"}) is None
    assert header_sku(gloves, set()) == "1000"
    single = ItemInfo(item_id="2", seller_sku="1000", variations=(Variation("c", "L", "G9"),))
    assert header_sku(single, {"1000"}) == "G9"
    own = ItemInfo(item_id="3", seller_sku="G1", variations=(Variation("d", "M", "G1"),))
    assert header_sku(own, {"G1"}) == "G1"


async def test_v4_each_cost_row_names_its_variation_and_plain_sku(session, seeded):
    page = await queries.product_page(session, seeded.shop_id, "1001", period="7d", as_of=CUR_END)
    for row in page["cost_and_floor"]["skus"]:
        assert row["base_sku"] and row["sku"].startswith(row["base_sku"])


def test_v10_a_bare_number_never_glues_onto_a_keyword():
    titles = [
        Title("1", "Găng tay cao su 1 găng tay rửa chén"),
        Title("2", "Găng tay nitrile 1 găng tay rửa chén"),
    ]
    keywords = {c.keyword for c in decompose(titles)}
    assert keywords and not any(k.split()[0].isdigit() for k in keywords), keywords
