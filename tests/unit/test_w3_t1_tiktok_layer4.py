"""W3 t1: TikTok days in layer 4 (shop / product / source rows). A synthetic TikTok shop.

Two products; four days:

- D1: shop-grain row (one order held both products: 7 đơn, GMV 950k) and A-34 rows with the
  channel blocks (the poll since W3; 8 product-orders, 900k), order lines with settlements;
- D2: shop-grain row and A-34 rows stored before W3 (totals only, no blocks);
- D3: order lines only (TikTok has not published the day yet);
- D4: shop-grain and A-34 rows that are all zero beside order lines (what a sandbox gets).

The repository reads are pointed at the shop's own platform (``own_platform``, t2's change to
``repositories.shopee_analytics``, which wins at merge) by :func:`_own_platform_reads`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok import mapping
from juli_backend.integrations.tiktok.mapping import (
    expand_analytics_product_list_item,
    expand_analytics_shop_performance,
)
from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.repositories.analytics import AnalyticsPerformanceRepo
from juli_backend.services.etl.transform import transform_for_channel
from juli_backend.services.shopee_analytics import loaders, materialize, service, tiktok_days
from juli_backend.services.shopee_analytics.shared import shop_profit_raw
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.builders import make_shop, make_user
from tests.support.tiktok_a34 import a34_row

D1, D2, D3, D4 = (date(2026, 11, 10) + timedelta(days=i) for i in range(4))
PRODUCTS = ("p1", "p2")
SUMMED = ("the_san_pham_khac", "video", "live", "lien_ket", "chenh_lech_nguon")


def _line(shop_id, n, day, item, *, status="delivered", deal=150_000, qty=1):
    when = datetime.combine(day, datetime.min.time()).replace(hour=10, minute=n)
    return ShopeeOrderLine(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="tiktok",
        order_ref=f"{n:032x}",
        line_no=0,
        ordered_at=when,
        paid_at=when,
        status=status,
        item_id=item,
        variation_id="",
        qty=qty,
        original_price=Decimal(deal),
        deal_price=Decimal(deal),
        source="api",
        source_version="test",
    )


def _settlement(shop_id, n, payout, *, price=150_000):
    return ShopeeOrderIncome(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="tiktok",
        order_ref=f"{n:032x}",
        payout=Decimal(payout),
        product_price=Decimal(price),
        fee_fixed=Decimal(-15_000),
        source="api",
        source_rank=1,
        source_version="test",
    )


async def _analytics(session, shop_id, day, row, *, blocks=True):
    payload = expand_analytics_product_list_item(
        row,
        start_date=day.isoformat(),
        end_date=(day + timedelta(days=1)).isoformat(),
        synced_at=1_763_000_000,
    )
    if not blocks:
        payload["traffic_breakdown"].pop(mapping.A34_BLOCKS_KEY)
    _, kwargs = transform_for_channel("tiktok.analytics.product.raw", payload)
    await AnalyticsPerformanceRepo(session).upsert(shop_id=shop_id, **kwargs)


@pytest.fixture(autouse=True)
def _own_platform_reads(monkeypatch):
    """Stand-in for t2's ``own_platform()`` filter: every TikTok shop here reads its own rows."""
    from juli_backend.repositories import shopee_analytics as repo

    monkeypatch.setattr(repo, "PLATFORM_SHOPEE", "tiktok")


async def _shop_grain(session, shop_id, day, *, gmv, orders, items):
    rows = expand_analytics_shop_performance(
        {
            "performance": {
                "intervals": [
                    {
                        "start_date": day.isoformat(),
                        "end_date": (day + timedelta(days=1)).isoformat(),
                        "sales": {
                            "gmv": {"amount": str(gmv), "currency": "VND"},
                            "orders_count": orders,
                            "sku_orders_count": orders,
                            "items_sold": items,
                        },
                        "traffic": {},
                    }
                ]
            }
        },
        synced_at=1_763_000_000,
    )
    _, kwargs = transform_for_channel("tiktok.analytics.shop.raw", rows[0])
    await AnalyticsPerformanceRepo(session).upsert(shop_id=shop_id, **kwargs)


async def seed_tiktok_shop(session, *, refund_settled: bool = True):
    shop = await make_shop(session, await make_user(session), platform="tiktok")
    sid = shop.id
    session.add_all(
        [
            _line(sid, 1, D1, "p1"),
            _line(sid, 2, D1, "p2", deal=120_000),
            _line(sid, 3, D1, "p2", status="returned", deal=120_000),
            _line(sid, 4, D3, "p1"),
            _line(sid, 5, D4, "p1"),
            _settlement(sid, 1, 120_000),
            _settlement(sid, 2, 95_000, price=120_000),
        ]
    )
    if refund_settled:
        session.add(_settlement(sid, 3, -30_000, price=120_000))
    await _shop_grain(session, sid, D1, gmv=950_000, orders=7, items=8)
    await _shop_grain(session, sid, D2, gmv=900_000, orders=8, items=8)
    await _shop_grain(session, sid, D4, gmv=0, orders=0, items=0)
    for p in PRODUCTS:
        await _analytics(session, sid, D1, a34_row(p))
        await _analytics(session, sid, D2, a34_row(p), blocks=False)
        zero = (0, 0, 0, 0)
        await _analytics(
            session,
            sid,
            D4,
            a34_row(p, card=zero, video=zero, live=zero, affiliate=zero, shop_tab=(0, 0, 0)),
        )
    await session.flush()
    return shop


async def _rows(session, model, shop_id):
    return list((await session.execute(select(model).where(model.shop_id == shop_id))).scalars())


@pytest.fixture
async def built(session):
    shop = await seed_tiktok_shop(session)
    report = await materialize.backfill_shop(session, shop.id)
    shops = {r.day: r for r in await _rows(session, ShopeeShopMetricsDaily, shop.id)}
    products = await _rows(session, ShopeeProductMetricsDaily, shop.id)
    sources = await _rows(session, ShopeeSourceMetricsDaily, shop.id)
    return shop, report, shops, products, sources


def test_the_blocks_key_is_the_mappers():
    assert tiktok_days.A34_BLOCKS_KEY == mapping.A34_BLOCKS_KEY


# ------------------------------------------------------------------------------- M-1


async def test_every_data_day_gets_shop_product_and_source_rows(built):
    _, report, shops, products, sources = built
    assert report.days_written == 4 and set(shops) == {D1, D2, D3, D4}
    assert {p.day for p in products} == {D1, D2, D3, D4}
    assert {s.day for s in sources} == {D1, D2, D3, D4}
    assert all(r.detail["rows_v"] == materialize.ROWS_VERSION for r in shops.values())


async def test_the_tiktok_ingest_hook_builds_the_day(session):
    from juli_backend.services.ingest.tiktok_canonical import record_touched_days

    shop = await seed_tiktok_shop(session)
    await record_touched_days(session, shop.id, frozenset({D1}))
    rows = await _rows(session, ShopeeShopMetricsDaily, shop.id)
    assert [r.day for r in rows] == [D1] and rows[0].gmv == Decimal(950_000)


async def test_the_nightly_rebuild_covers_the_recent_data_days(session):
    shop = await seed_tiktok_shop(session)
    assert await materialize.rebuild_recent(session, shop.id, today=D4 + timedelta(days=1)) == 4
    assert await materialize.rebuild_recent(session, shop.id, today=D4 + timedelta(days=200)) == 0


async def test_the_rebuild_is_idempotent(session, built):
    shop, _, shops, _, sources = built
    await materialize.backfill_shop(session, shop.id)
    again = {r.day: r for r in await _rows(session, ShopeeShopMetricsDaily, shop.id)}
    assert {d: (r.gmv, r.orders, r.profit) for d, r in again.items()} == {
        d: (r.gmv, r.orders, r.profit) for d, r in shops.items()
    }
    assert len(await _rows(session, ShopeeSourceMetricsDaily, shop.id)) == len(sources)


# ------------------------------------------------------------------------------- M-3


async def test_the_headline_is_the_analytics_total(built):
    _, _, shops, _, _ = built
    d1 = shops[D1]
    # the shop-grain row: one order held both products, so 7 đơn (A-34 per product says 8)
    assert d1.gmv == Decimal(950_000) and d1.orders == 7 and d1.units == 8
    assert d1.aov == (Decimal(950_000) / 7).quantize(Decimal("0.01"))
    # views / clicks: the products' A-34 totals (2 000 impressions, 100 clicks each)
    assert d1.views == 4000 and d1.product_clicks == 200 and d1.complete
    assert d1.sources["gmv"] == d1.sources["orders"] == tiktok_days.ROW_SOURCE
    # the returned line is not a sale (glossary: returned is out of đơn / GMV)
    assert d1.line_gmv == Decimal(270_000), "the order lines stay beside the headline"
    assert shops[D2].gmv == Decimal(900_000) and shops[D2].complete


async def test_a_day_without_analytics_uses_the_order_lines_and_says_through_when(built):
    _, _, shops, _, _ = built
    d3 = shops[D3]
    assert d3.gmv == Decimal(150_000) and d3.orders == 1 and not d3.complete
    assert d3.sources["gmv"] == "order_lines"
    assert d3.detail[tiktok_days.THROUGH_KEY] == D2.isoformat()
    assert tiktok_days.THROUGH_KEY not in shops[D1].detail


async def test_all_zero_analytics_beside_order_lines_is_not_a_zero_day(built):
    _, _, shops, _, _ = built
    d4 = shops[D4]
    assert d4.gmv == Decimal(150_000) and not d4.complete
    assert d4.detail[tiktok_days.THROUGH_KEY] == D2.isoformat()


# ------------------------------------------------------------------------------- M-4


def _by(sources, day, item=None):
    return {s.source: s for s in sources if s.day == day and s.item_id == item}


async def test_the_four_sources_add_up_to_the_shop_total_and_the_shop_tab_stays_out(built):
    _, _, shops, _, sources = built
    shop = _by(sources, D1)
    assert shop["the_san_pham_khac"].gmv == Decimal(400_000)
    assert shop["video"].gmv == Decimal(200_000)
    assert shop["live"].gmv == Decimal(0)
    assert shop["lien_ket"].gmv == Decimal(300_000)
    assert shop["chenh_lech_nguon"].gmv == Decimal(50_000), "the gap to the shop total"
    assert sum(shop[k].gmv for k in SUMMED) == shops[D1].gmv
    assert sum(shop[k].orders for k in SUMMED) == shops[D1].orders
    assert shop["the_san_pham_khac"].views == 2000 and shop["the_san_pham_khac"].clicks == 100


async def test_the_shop_tab_row_has_its_own_traffic_and_no_orders_or_profit(built):
    _, _, _, _, sources = built
    tab = _by(sources, D1)["trang_shop"]
    assert (tab.views, tab.clicks, tab.gmv) == (600, 30, Decimal(240_000))
    assert tab.orders == 0 and tab.profit is None and not tab.scaled_to_totals


async def test_no_ads_figure_is_invented(built):
    _, _, shops, _, sources = built
    assert shops[D1].ads_spend is None and shops[D1].ads_gmv is None
    assert all(s.ads_spend is None and s.ads_gmv is None for s in sources)


async def test_the_product_sources_add_up_to_the_product_row(built):
    _, _, _, products, sources = built
    for p in (r for r in products if r.day == D1 and r.item_id != RESIDUAL_ITEM):
        rows = _by(sources, D1, p.item_id)
        assert sum(rows[k].gmv for k in SUMMED) == p.gmv
        assert sum(rows[k].orders for k in SUMMED) == p.orders
        assert rows["trang_shop"].gmv == Decimal(120_000)


async def test_a_day_stored_without_blocks_keeps_its_total_in_the_residual(built):
    _, _, shops, _, sources = built
    shop = _by(sources, D2)
    assert shop["chenh_lech_nguon"].gmv == shops[D2].gmv
    assert shop["chenh_lech_nguon"].orders == shops[D2].orders
    assert set(shop) == {"chenh_lech_nguon"}, "W3.1: no source row (no 0) without A-34 blocks"


async def test_a_rebuild_drops_the_zero_source_rows_an_earlier_build_stored(session, built):
    """W3.1 (V-2a): rows stored by the old rule (the five sources at 0) go on the next build."""
    shop, _, _, _, sources = built
    for src in SUMMED[:-1] + ("trang_shop",):
        session.add(
            ShopeeSourceMetricsDaily(
                shop_id=shop.id, day=D2, item_id=None, source=src, views=None, clicks=None,
                orders=0, gmv=Decimal(0),
            )
        )  # fmt: skip
    await session.flush()
    await materialize.rebuild_days(session, shop.id, [D2])
    again = await _rows(session, ShopeeSourceMetricsDaily, shop.id)
    assert set(_by(again, D2)) == {"chenh_lech_nguon"}
    assert set(_by(again, D1)) >= set(SUMMED), "a day with blocks is untouched"


async def test_the_sum_check_passes_on_a_day_without_a_breakdown(session, built):
    from juli_backend.services.shopee_analytics import funnel_check

    shop, *_ = built
    assert await funnel_check.check_day(session, shop.id, D2) == []
    assert await funnel_check.check_day(session, shop.id, D1) == []


# ------------------------------------------------------------------------------- M-5


async def _engine_profit(session, shop_id, day):
    ctx = await loaders.load_context(session, shop_id)
    view = await service.load_view(session, shop_id, ctx, Window(day, day))
    # the stored before-ads value is the UNGATED engine figure (#103 11a gates only what is shown)
    return shop_profit_raw(view).profit, view.profit.covered_margin_profit


def _before_ads(row, key="profit_before_ads"):
    value = row.detail.get(key)
    return None if value is None else Decimal(value)


async def test_without_an_ads_source_profit_and_margins_are_none(built):
    """Owner W3-Q5 = a: no ads spend source (TikTok before the Business API scope) means no
    profit and no margin, never a before-ads number; the components are kept."""
    _, _, shops, products, sources = built
    for row in shops.values():
        assert row.profit is None and row.margin_profit is None
        assert row.detail[tiktok_days.PROFIT_REASON_KEY] == tiktok_days.ADS_SCOPE_MISSING
    assert shops[D1].buyer_paid_known is not None and shops[D1].cogs_coverage is not None
    assert all(p.profit is None for p in products) and all(s.profit is None for s in sources)


async def test_the_before_ads_figures_are_the_order_line_engines(session, built):
    shop, _, shops, _, _ = built
    profit, margin = await _engine_profit(session, shop.id, D1)
    assert profit is not None
    assert _before_ads(shops[D1]) == profit.quantize(Decimal("0.01"))
    assert _before_ads(shops[D1], "margin_profit_before_ads") == margin.quantize(Decimal("0.01"))


async def test_the_refund_cost_is_the_settled_deduction(session):
    with_refund = await seed_tiktok_shop(session, refund_settled=True)
    without = await seed_tiktok_shop(session, refund_settled=False)
    await materialize.rebuild_days(session, with_refund.id, [D1])
    await materialize.rebuild_days(session, without.id, [D1])

    async def profit(shop_id):
        row = (
            await session.execute(
                select(ShopeeShopMetricsDaily).where(
                    ShopeeShopMetricsDaily.shop_id == shop_id, ShopeeShopMetricsDaily.day == D1
                )
            )
        ).scalar_one()
        return _before_ads(row)

    assert await profit(without.id) - await profit(with_refund.id) == Decimal(30_000)


# ------------------------------------------------------------------------- X-1 backend half


async def test_one_number_per_metric_across_the_three_tables(built):
    _, _, shops, products, sources = built
    for day in (D1, D2):
        day_products = [p for p in products if p.day == day]
        assert sum(p.gmv for p in day_products) == shops[day].gmv, "the residual row closes it"
        shop_sources = _by(sources, day)
        assert sum(r.gmv for k, r in shop_sources.items() if k in SUMMED) == shops[day].gmv


# --------------------------------------------- M-5: settlement-only profit (coordinator note)


async def test_a_delivered_order_without_a_settlement_has_no_profit(built):
    _, _, shops, products, sources = built
    for day in (D3, D4):  # p1's line on each day has no settlement row: no estimate either
        assert _before_ads(shops[day]) is None
    assert _before_ads(shops[D1]) is not None, "a day whose delivered orders all settled has one"


async def test_a_tiktok_profit_never_reads_the_shopee_fee_formulas(session):
    from juli_backend.models.shopee_profit import PlatformFeeFormula

    plain = await seed_tiktok_shop(session)
    await materialize.rebuild_days(session, plain.id, [D1, D3])
    session.add(
        PlatformFeeFormula(
            id=uuid.uuid4(),
            platform="shopee",
            category_path=[],
            effective_from=date(2026, 1, 1),
            components=[{"name": "fixed", "rate": "0.90"}],
        )
    )
    other = await seed_tiktok_shop(session)
    await session.flush()
    await materialize.rebuild_days(session, other.id, [D1, D3])

    async def day_profits(shop_id):
        rows = await _rows(session, ShopeeShopMetricsDaily, shop_id)
        return {r.day: _before_ads(r) for r in rows}

    assert await day_profits(other.id) == await day_profits(plain.id)
    assert (await day_profits(other.id))[D3] is None, "no settlement: no formula estimate"


async def test_the_rebuild_hands_a_tiktok_shop_no_fee_formula_rows(session, monkeypatch):
    from juli_backend.services.shopee_analytics import fee_table

    shop = await seed_tiktok_shop(session)
    sentinel = fee_table.FormulaRow((), date(2026, 1, 1), ())
    real_context = loaders.load_context

    async def with_formula(session, shop_id):
        ctx = await real_context(session, shop_id)
        ctx.formula_rows.append(sentinel)
        return ctx

    seen: list[list] = []
    real_view = service.load_view

    async def spy(session, shop_id, ctx, window, **kw):
        seen.append(list(ctx.formula_rows))
        return await real_view(session, shop_id, ctx, window, **kw)

    monkeypatch.setattr(loaders, "load_context", with_formula)
    monkeypatch.setattr(service, "load_view", spy)
    await materialize.rebuild_days(session, shop.id, [D1])
    assert seen == [[]]


async def test_a_multi_product_order_is_one_order_in_the_headline(built):
    _, _, shops, products, sources = built
    per_product = sum(p.orders for p in products if p.day == D1 and p.item_id != RESIDUAL_ITEM)
    assert per_product == 8 and shops[D1].orders == 7
    assert sum(_by(sources, D1)[k].orders for k in SUMMED) == 7


# ---------------------------------------------------- Tab cửa hàng orders are not a count


async def test_the_shop_tab_zero_orders_are_flagged_not_a_count(built):
    _, _, shops, _, _ = built
    assert shops[D1].detail[tiktok_days.SHOP_TAB_ORDERS_KNOWN_KEY] is False


def _surfaces_tab_orders(node) -> bool:
    if isinstance(node, dict):
        named = any(v == "trang_shop" for v in node.values()) or "trang_shop" in node
        if named and node.get("orders") == 0:
            return True
        return any(_surfaces_tab_orders(v) for v in node.values())
    if isinstance(node, list):
        return any(_surfaces_tab_orders(v) for v in node)
    return False


ROUTES = (
    "overview",
    "matrix",
    "critical",
    "ranking",
    "channel-split",
    "channel-split/products",
    "metric-view",
    "products/p1",
)


async def test_no_route_surfaces_the_shop_tab_zero_as_orders(session, built):
    from juli_backend.models.models import User
    from tests.support.api import authenticate, build_app, client_for

    shop = built[0]
    user = await session.get(User, shop.user_id)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    params = {"period": "7d", "as_of": D2.isoformat()}
    async with client_for(app) as client:
        responses = {r: await client.get(f"/v1/demo/shopee/{r}", params=params) for r in ROUTES}
    app.dependency_overrides.clear()
    for route, response in responses.items():
        if response.status_code == 200:
            assert not _surfaces_tab_orders(response.json()), route
