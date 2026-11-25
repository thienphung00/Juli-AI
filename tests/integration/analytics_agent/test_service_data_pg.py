"""The analytics agent's real adapters on real Postgres, from the synthetic Shopee shop.

Every named SELECT of `ServiceData` runs on the real schema and returns the shape the chains
expect; `open_cards` honours the 28-day cutoff for executed cards (G4); the analytics-service
reads (overview, metric-view, critical, channel split) and the recommendation engine adapter
answer in the shapes the engine reads; nothing is written. No client data: the synthetic shop of
`tests/support/shopee_analytics.py` plus rows seeded here.

Run: `fasttrack/bin/pg-test.sh tests/integration/analytics_agent/test_service_data_pg.py`
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.models.shopee_profit import ShopeeOrderIncome
from juli_backend.models.stock_alert import ShopeeStockHistory
from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine
from juli_backend.services.analytics_agent.chains import run_chain
from juli_backend.services.analytics_agent.data_service import ServiceData
from juli_backend.services.analytics_agent.labels import shopee_labels
from juli_backend.services.shopee_recommendations.kinds import WIRING
from tests.support.postgres import requires_postgres
from tests.support.shopee_analytics import CUR_END, ITEMS, seed_shopee_shop

pytestmark = [requires_postgres]

AS_OF = CUR_END
DAY_KEYS = {"day", "gmv", "orders", "units", "views", "clicks", "ads_spend", "ads_gmv", "complete"}


def _proposal(
    shop_id: uuid.UUID, kind: str, item: str | None, status: str, code: str, updated: datetime
) -> ShopProposal:
    return ShopProposal(
        shop_id=shop_id,
        platform="shopee",
        cycle="c1",
        kind=kind,
        subject_type="item" if item else "shop",
        item_id=item,
        subject_label="Synthetic",
        change_before={},
        change_after={"x": 1},
        reason="synthetic",
        status=status,
        code=code,
        created_at=updated,
        updated_at=updated,
    )


@pytest_asyncio.fixture
async def world():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    conn = await engine.connect()
    outer = await conn.begin()

    def new_session() -> AsyncSession:
        return AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

    seed = new_session()
    seeded = await seed_shopee_shop(seed)
    sid = seeded.shop_id
    # shop_proposals timestamps are `timestamp without time zone` (naive UTC, like the models)
    now = datetime.now(UTC).replace(tzinfo=None)
    seed.add_all(
        [
            # stock: item 1001 sold out on 5/10, item 1002 unlisted on 6/10
            ShopeeStockHistory(
                shop_id=sid,
                item_id="1001",
                variation_id="",
                read_at=datetime(2026, 10, 5, 10),
                available=0,
                sellable=0,
                listing_status="normal",
            ),
            ShopeeStockHistory(
                shop_id=sid,
                item_id="1002",
                variation_id="",
                read_at=datetime(2026, 10, 6, 10),
                available=5,
                sellable=5,
                listing_status="unlisted",
            ),
            # open cards: a draft, an executed one inside the 28 days, one outside, a rejected one
            _proposal(sid, "price", "1001", "draft", "JC-2610-0001", now),
            _proposal(sid, "voucher", "1002", "executed", "JC-2610-0002", now - timedelta(days=3)),
            _proposal(sid, "ads", None, "executed", "JC-2610-0003", now - timedelta(days=40)),
            _proposal(sid, "bundle", "1003", "rejected", "JC-2610-0004", now),
        ]
    )
    await seed.commit()
    await seed.close()

    @asynccontextmanager
    async def factory():
        s = new_session()
        try:
            yield s
        finally:
            await s.close()

    try:
        yield sid, factory
    finally:
        await outer.rollback()
        await conn.close()
        await engine.dispose()


async def test_shop_daily_shape_and_order(world: Any) -> None:
    sid, f = world
    rows = await ServiceData(f, sid).shop_daily(AS_OF)
    assert rows and all(DAY_KEYS <= set(r) for r in rows)
    assert [r["day"] for r in rows] == sorted(r["day"] for r in rows)
    assert all(r["day"] <= AS_OF for r in rows) and any(r["complete"] for r in rows)
    assert all(isinstance(r["day"], date) for r in rows)


async def test_item_daily_has_shop_rows_shape_and_zero_sales_days(world: Any) -> None:
    sid, f = world
    d = ServiceData(f, sid)
    shop, item = await d.shop_daily(AS_OF), await d.shop_daily(AS_OF, "1001")
    assert [r["day"] for r in item] == [r["day"] for r in shop] and all(
        DAY_KEYS <= set(r) for r in item
    )
    assert all(
        r["orders"] is not None and r["gmv"] is not None for r in item
    )  # no row = 0 sales, not NULL
    # decision #39: the product's own ad cost (the ads report by product), NULL = no basis
    spend = [r["ads_spend"] for r in item if r["ads_spend"] is not None]
    assert spend and all(v >= 0 for v in spend)
    assert any(r["ads_spend"] is None for r in item)  # a day with no basis is not 0


async def test_source_and_product_rows(world: Any) -> None:
    sid, f = world
    d = ServiceData(f, sid)
    a, b = AS_OF - timedelta(days=13), AS_OF
    src = await d.source_daily(a, b)
    assert src and all({"day", "source", "views", "clicks", "orders", "gmv"} <= set(r) for r in src)
    assert all(a <= r["day"] <= b for r in src)
    prods = await d.product_daily(a, b)
    assert prods and {r["item_id"] for r in prods} <= set(ITEMS)
    assert all({"day", "item_id", "gmv", "orders", "units"} <= set(r) for r in prods)
    assert not any(r["item_id"].startswith("sku:") or r["item_id"] == "__residual__" for r in prods)
    item_src = await d.source_daily(a, b, "1001")
    assert all({"day", "source", "views"} <= set(r) for r in item_src)


async def test_names_and_catalog_search_use_the_repository_read(world: Any) -> None:
    sid, f = world
    d = ServiceData(f, sid)
    names = await d.item_names(["1001", "9999"])
    assert names == {"1001": ITEMS["1001"][0], "9999": "9999"}
    assert await d.item_names([]) == {}
    assert [c["item_id"] for c in await d.catalog_search("gang tay")] == [
        "1001"
    ]  # accent-insensitive
    assert [c["item_id"] for c in await d.catalog_search("1002")] == ["1002"]  # exact item id
    assert [c["item_id"] for c in await d.catalog_search("T1")] == ["1003"]  # seller SKU
    assert await d.catalog_search("khong co san pham nay") == []
    assert await d.catalog_search("  ") == []


async def test_stock_events(world: Any) -> None:
    sid, f = world
    ev = await ServiceData(f, sid).stock_events(date(2026, 10, 1), date(2026, 10, 7))
    by = {(r["item_id"], r["day"]): r for r in ev}
    assert by[("1001", date(2026, 10, 5))]["min_available"] == 0
    assert "unlisted" in by[("1002", date(2026, 10, 6))]["statuses"]
    assert await ServiceData(f, sid).stock_events(date(2026, 9, 1), date(2026, 9, 2)) == []


async def test_open_cards_honour_the_28_day_cutoff_for_executed_cards(world: Any) -> None:
    sid, f = world
    cards = await ServiceData(f, sid).open_cards()
    codes = {c["code"] for c in cards}
    assert codes == {
        "JC-2610-0001",
        "JC-2610-0002",
    }  # draft + executed 3 days ago; not 40 days, not rejected
    one = next(c for c in cards if c["code"] == "JC-2610-0001")
    assert {
        "kind",
        "item_id",
        "status",
        "planned_start",
        "subject_label",
        "change_after",
        "code",
    } <= set(one)
    assert one["kind"] == "price" and one["item_id"] == "1001"


async def test_other_shops_cards_never_appear(world: Any) -> None:
    sid, f = world
    assert await ServiceData(f, uuid.uuid4()).open_cards() == []
    assert await ServiceData(f, uuid.uuid4()).shop_daily(AS_OF) == []


async def test_analytics_service_reads_have_the_shape_the_chains_expect(world: Any) -> None:
    sid, f = world
    d = ServiceData(f, sid)
    a, b = AS_OF - timedelta(days=6), AS_OF
    ov = await d.overview(a, b)
    assert "shop_profit" in ov and "shop_metrics" in ov
    mv = await d.metric_view("gmv", a, b, None)
    assert isinstance(mv.get("channels"), list) and isinstance(mv.get("products"), list)
    crit = await d.critical(a, b)
    assert isinstance(crit.get("items"), list)
    cost = await d.cost_lines(a, b)
    assert set(cost) == {"net_revenue", "cost_ads", "cost_affiliate", "cost_offers"}
    assert cost["net_revenue"] is not None
    item_cost = await d.cost_lines(a, b, "1001")
    assert set(item_cost) == set(cost) and item_cost["net_revenue"] is None


async def test_chains_run_on_the_real_adapter(world: Any) -> None:
    sid, f = world
    d = ServiceData(f, sid)
    for chain, metric in (
        ("gmv_change", "gmv"),
        ("orders_change", "orders"),
        ("cost_change", None),
    ):
        r = await run_chain(d, chain, metric, "last_7d_vs_prev_7d", AS_OF)
        assert r.stop_reason in {
            "explained",
            "within_noise",
            "unexplained",
            "data_missing",
            "data_stale",
        }
        assert r.json(shopee_labels())["chain"] == chain
    item = await run_chain(d, "gmv_change", "gmv", "last_7d_vs_prev_7d", AS_OF, item_id="1001")
    assert item.item_id == "1001" and item.item_name == ITEMS["1001"][0]


async def test_card_engine_adapter_answers_with_values_or_a_reason(world: Any) -> None:
    sid, f = world
    eng = ServiceCardEngine(f, sid)
    assert eng.allowed_kinds("ctor") == WIRING["ctor"]
    out = await eng.engine_card("product_discount", "1001", AS_OF)
    assert isinstance(out["ok"], bool)
    if out["ok"]:
        assert out["card"]["versions"] and all("label" in v for v in out["card"]["versions"])
    else:
        assert isinstance(out["reason"], str) and out["reason"]
    unknown = await eng.engine_card("not_a_kind", None, AS_OF)
    assert unknown["ok"] is False


async def test_nothing_is_written(world: Any) -> None:
    sid, f = world
    d = ServiceData(f, sid)

    async def counts() -> tuple[int, int]:
        async with f() as s:
            p = await s.scalar(select(func.count()).select_from(ShopProposal))
            m = await s.scalar(select(func.count()).select_from(ShopeeShopMetricsDaily))
            return int(p or 0), int(m or 0)

    before = await counts()
    await d.shop_daily(AS_OF)
    await d.open_cards()
    await d.overview(AS_OF - timedelta(days=6), AS_OF)
    await d.cost_lines(AS_OF - timedelta(days=6), AS_OF)
    await ServiceCardEngine(f, sid).engine_card("product_discount", "1001", AS_OF)
    assert await counts() == before


async def test_entity_readers_run_on_the_real_schema_and_return_their_shapes(world: Any) -> None:
    """Track J: every new named SELECT / service read executes on the real tables."""
    sid, f = world
    d = ServiceData(f, sid)
    a, b = AS_OF - timedelta(days=6), AS_OF
    for kind in ("voucher", "affiliate"):
        tot = await d.entity_totals(kind, a, b)
        assert {"orders", "gmv", "cost"} <= set(tot)
        assert {"orders", "gmv", "cost"} <= set(await d.entity_totals(kind, a, b, "1001"))
    assert isinstance(await d.voucher_rows(a, b), list)
    assert isinstance(await d.budget_days(a, b), list)
    for c in await d.campaign_rows(a, b):
        assert {"key", "name", "spend", "gmv", "roas", "break_even", "profit_after_ads"} <= set(c)
    p = await d.product_profit("1001", a, b)
    assert p is None or {"profit", "margin_pct", "coverage_pct", "gmv"} <= set(p)


async def test_voucher_income_counts_only_income_rows_in_the_window(world: Any) -> None:
    """`order_settlements` (the stored per-order income) filtered on `ordered_on`: voucher orders
    are rows with seller_voucher_borne > 0, the cost is the sum, `income_to` the last order day
    with an income row; a window with no income row is "no rows", never 0."""
    sid, f = world

    def row(ref: str, day: date, borne: str | None) -> ShopeeOrderIncome:
        return ShopeeOrderIncome(
            shop_id=sid,
            platform="shopee",
            order_ref=ref,
            ordered_on=day,
            seller_voucher_borne=None if borne is None else Decimal(borne),
            source="file",
            source_rank=3,
            source_version="seller-centre-xlsx-1",
        )

    async with f() as s:
        s.add_all(
            [
                row("SYN-INC-1", date(2026, 10, 2), "5000"),
                row("SYN-INC-2", date(2026, 10, 3), "3000"),
                row("SYN-INC-3", date(2026, 10, 4), "0"),  # an income row with no voucher
                row("SYN-INC-4", date(2026, 10, 6), None),  # the export did not state it
                row("SYN-INC-5", date(2026, 10, 20), "9000"),  # outside the window
            ]
        )
        await s.commit()
    d = ServiceData(f, sid)
    got = await d.voucher_income(CUR_END - timedelta(days=6), CUR_END)
    assert got["rows"] == 4  # the 20/10 row is outside
    assert got["orders"] == 2  # only seller_voucher_borne > 0
    assert got["cost"] == Decimal("8000")  # NULL adds nothing, the outside row is not in
    assert got["income_to"] == date(2026, 10, 6)
    assert got["gmv"] == 0  # synthetic refs match no order line
    empty = await d.voucher_income(date(2026, 9, 1), date(2026, 9, 7))
    assert empty["rows"] == 0 and empty["orders"] == 0 and empty["income_to"] is None
    assert empty["cost"] is None  # no income row: not 0
