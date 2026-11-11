"""P100-A data repair (brief A.1-A.3, A.7; B.17): a day whose order data never arrived is
"chưa có dữ liệu" (NULL, out of every total and rate, the window says "N/30 ngày có dữ liệu"); an
order whose cost is unknown has a NULL profit, never 0; a product never out-sells its shop on
any window; one coverage for every surface.

Synthetic shop, invented figures only (the shape of the P99 check: a 10-day window with a day
Shopee posted as all-zero with no traffic, a day without any order data, a day of order lines
without costs, a stale period stamp on a day without data).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily, ShopeeShopMetricsDaily
from juli_backend.services.shopee_analytics import funnel, loaders, materialize, service, stored
from juli_backend.services.shopee_analytics.funnel import FunnelRows, ScopeDay, base_from_rows
from juli_backend.services.shopee_analytics.matrix import build_matrix
from juli_backend.services.shopee_analytics.product import kpi_block
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine_families import integrate
from tests.support.builders import make_shop, make_user
from tests.support.shopee_analytics import _daily, _line, period_row

START = date(2026, 10, 1)
DAYS = [START + timedelta(days=i) for i in range(10)]
WINDOW = Window(DAYS[0], DAYS[-1])
ZERO_NO_TRAFFIC = DAYS[3]  # Shopee posted 0 đơn / 0đ and no visitor at all: never arrived
NO_ROW = DAYS[5]  # traffic only, no order totals, no order lines
REAL_ZERO = DAYS[7]  # 0 đơn but 40 visitors: a real day without sales
LINES_NO_COST = DAYS[8]  # 2 order lines whose cost is unknown (affiliate, no commission known)
NO_LINES = DAYS[9]  # Shopee's 4 đơn, no order line yet: profit unknown
ITEM = "9001"
SHOP_ORDERS = 4
SHOP_GMV = 400_000


def _shop_day(shop_id, day, *, orders, gmv, visitors=None):
    row = _daily(shop_id, day, "total", "all", orders=orders, gmv=gmv, dataset="shop_overview")
    row.visitors = None if visitors is None else Decimal(visitors)
    return row


@pytest.fixture
async def shop_id(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee", shop_name="Synthetic P100-A Shop")
    rows = []
    for d in DAYS:
        if d == NO_ROW:
            continue
        if d == ZERO_NO_TRAFFIC:
            rows.append(_shop_day(shop.id, d, orders=0, gmv=0))
        elif d == REAL_ZERO:
            rows.append(_shop_day(shop.id, d, orders=0, gmv=0, visitors=40))
        elif d == LINES_NO_COST:
            rows.append(_shop_day(shop.id, d, orders=2, gmv=180_000, visitors=60))
        else:
            rows.append(_shop_day(shop.id, d, orders=SHOP_ORDERS, gmv=SHOP_GMV, visitors=80))
    # the traffic table posts every day, the day without order totals too
    for d in DAYS:
        rows.append(_daily(shop.id, d, "product_card", "all", impressions=500, clicks=20))
    session.add_all(rows)
    # two paid lines on LINES_NO_COST: affiliate orders without a known commission
    session.add_all(
        [
            _line(shop.id, n, LINES_NO_COST, ITEM, deal=90_000, affiliate=True, sku_only=False)
            for n in (1, 2)
        ]
    )
    await session.flush()
    await materialize.backfill_shop(session, shop.id)
    await session.flush()
    return shop.id


async def _shop_rows(session, shop_id):
    q = select(ShopeeShopMetricsDaily).where(ShopeeShopMetricsDaily.shop_id == shop_id)
    return {r.day: r for r in (await session.execute(q)).scalars()}


async def _product_rows(session, shop_id, item=ITEM):
    q = select(ShopeeProductMetricsDaily).where(
        ShopeeProductMetricsDaily.shop_id == shop_id, ShopeeProductMetricsDaily.item_id == item
    )
    return {r.day: r for r in (await session.execute(q)).scalars()}


# --------------------------------------------------------------------- A.1 missing days


async def test_a_day_whose_order_data_never_arrived_is_stored_null_not_zero(session, shop_id):
    shop = await _shop_rows(session, shop_id)
    assert shop[ZERO_NO_TRAFFIC].orders is None and shop[ZERO_NO_TRAFFIC].gmv is None
    assert shop[NO_ROW].orders is None and shop[NO_ROW].gmv is None
    assert shop[REAL_ZERO].orders == 0  # a real day without sales stays 0


async def test_the_window_sums_only_its_days_with_data_and_says_how_many(session, shop_id):
    sw = await stored.load_stored(session, shop_id, WINDOW)
    assert sw is not None
    assert sw.days_with_data == 8  # 10 days, 2 never arrived
    assert sw.orders == 6 * SHOP_ORDERS + 0 + 2
    # traffic of the days without order data stays out of the rates (CTOR = đơn ÷ lượt nhấp)
    assert sw.clicks == 8 * 20
    ctx = await loaders.load_context(session, shop_id)
    view = await service.load_view(session, shop_id, ctx, WINDOW, funnel=True)
    m = view.metrics
    cov = m.json()["coverage"]
    assert cov == {
        "days_with_data": 8,
        "window_days": 10,
        "label": "8/10 ngày có dữ liệu",
    }
    assert m.orders == 26 and m.clicks == 160
    assert m.ctor == Decimal(26) / Decimal(160)


async def test_the_funnel_base_leaves_the_days_without_data_out(session, shop_id):
    rows = await funnel.load_rows(session, shop_id, WINDOW)
    assert {d.day for d in rows.shop_days} == set(DAYS) - {ZERO_NO_TRAFFIC, NO_ROW}
    assert all(r.day not in (ZERO_NO_TRAFFIC, NO_ROW) for r in rows.sources)
    base = base_from_rows(rows, str(shop_id))
    assert base.total("orders") == 26
    assert base.days == 8 and base.window_days == 10


def test_a_product_base_counts_the_windows_data_days_not_its_own_rows():
    w = Window(DAYS[0], DAYS[-1])
    shop = tuple(ScopeDay(d, None, 3, Decimal(300_000), None) for d in DAYS[:9])
    prod = tuple(ScopeDay(d, ITEM, 1, Decimal(90_000), Decimal(9_000)) for d in DAYS[:3])
    base = base_from_rows(FunnelRows(w, (), shop, prod), "s", item_ids=(ITEM,))
    assert (base.profit_days, base.days, base.window_days) == (3, 9, 10)
    note = integrate.profit_coverage_note(base)
    assert note == (
        "Lợi nhuận mỗi đơn tính trên 3 ngày có dữ liệu chi phí (trong 9/10 ngày có dữ liệu)."
    )


async def test_a_shopee_row_without_orders_is_not_a_zero_order_day(session, shop_id):
    day = DAYS[0] - timedelta(days=1)
    row = _shop_day(shop_id, day, orders=0, gmv=120_000, visitors=30)
    row.orders = None
    session.add(row)
    await session.flush()
    totals = await loaders.load_shop_totals(session, shop_id, Window(day, day))
    assert totals.orders is None and totals.basis == "none"


# -------------------------------------------------------------------- A.2 unknown cost


async def test_orders_without_costs_have_a_null_profit_never_zero(session, shop_id):
    shop = await _shop_rows(session, shop_id)
    assert shop[LINES_NO_COST].orders == 2
    assert shop[LINES_NO_COST].profit is None
    assert shop[NO_LINES].orders == SHOP_ORDERS and shop[NO_LINES].profit is None
    prod = await _product_rows(session, shop_id)
    assert prod[LINES_NO_COST].orders == 2 and prod[LINES_NO_COST].profit is None
    rows = await funnel.load_rows(session, shop_id, WINDOW)
    base = base_from_rows(rows, str(shop_id), item_ids=(ITEM,))
    assert base.total("profit") is None and base.profit_days == 0


# --------------------------------------------------------------- A.3 product <= shop


async def test_a_stale_period_stamp_on_a_day_without_data_never_reaches_a_window(session, shop_id):
    """Rows built before P99 for a day that is no data day (the backfill never revisits it):
    74 đơn stamped on a day the shop has no order data for, and a data day where the product
    claims more than the shop sold."""
    for day, orders, gmv in ((NO_ROW, 74, 5_000), (DAYS[0], 74, 9_000)):
        await session.execute(
            ShopeeProductMetricsDaily.__table__.update()
            .where(
                ShopeeProductMetricsDaily.shop_id == shop_id,
                ShopeeProductMetricsDaily.day == day,
                ShopeeProductMetricsDaily.item_id == "__residual__",
            )
            .values(item_id=ITEM, orders=orders, gmv=Decimal(gmv), source="file")
        )
    session.expire_all()
    sw = await stored.load_stored(session, shop_id, WINDOW)
    assert sw is not None
    p = sw.products[ITEM]
    assert p.orders == SHOP_ORDERS + 2  # DAYS[0] capped at the shop's 4, NO_ROW left out
    assert p.orders <= (sw.orders or 0)


async def test_the_backfill_rewrites_stored_days_that_are_no_data_day_any_more(session, shop_id):
    orphan = DAYS[0] - timedelta(days=3)
    session.add(
        ShopeeProductMetricsDaily(
            shop_id=shop_id, day=orphan, order_type="confirmed", item_id=ITEM,
            gmv=Decimal(5_000), orders=74, units=74, line_gmv=Decimal(0), line_orders=0,
            source="file",
        )
    )  # fmt: skip
    await session.flush()
    report = await materialize.backfill_shop(session, shop_id)
    assert report.days_found == 11
    row = (await _product_rows(session, shop_id))[orphan]
    assert row.orders == 0


async def test_a_raw_window_never_gives_a_product_more_orders_than_the_shop(session, shop_id):
    """The raw path (a comparison window without stored rows) used to stamp a longer Shopee
    period's đơn on the window unscaled."""
    session.add(
        period_row(
            shop_id, "product_period", DAYS[0], DAYS[-1] + timedelta(days=20),
            item_id="9002", gmv=Decimal(9_000_000), orders=Decimal(300),
        )
    )  # fmt: skip
    await session.flush()
    ctx = await loaders.load_context(session, shop_id)
    w = Window(DAYS[0], DAYS[4])
    view = await service.load_view(session, shop_id, ctx, w, rows="raw")
    m = view.metrics
    split = m.split("9002")
    assert split is not None and m.orders is not None
    assert split.orders <= m.orders


async def test_a_previous_window_that_cannot_be_compared_shows_no_previous_numbers(
    session, shop_id
):
    ctx = await loaders.load_context(session, shop_id)
    now = await service.load_view(session, shop_id, ctx, WINDOW, funnel=True)
    before = await service.load_view(
        session, shop_id, ctx, WINDOW.previous(), funnel=True, rows="soft"
    )
    assert before.comparable_as_previous is False
    block = kpi_block(now, before, ITEM)
    assert block["orders"]["previous"] is None
    assert block["gmv"]["previous"] is None and block["gmv"]["change_pct"] is None
    assert block["coverage"]["label"] == "8/10 ngày có dữ liệu"
    assert build_matrix(now)["coverage"]["days_with_data"] == 8


async def test_a_zero_order_shop_day_never_keeps_the_period_counts_of_a_product(session, shop_id):
    """The prod shape (days before the Connector's daily totals): the shop's day says 0 đơn / 0đ
    while a product's period file covers the day; the product row used to keep the period's đơn
    unscaled (GMV 0)."""
    day = REAL_ZERO
    session.add(
        period_row(
            shop_id, "product_period", day - timedelta(days=20), day + timedelta(days=9),
            item_id="9003", gmv=Decimal(2_000_000), orders=Decimal(83),
        )
    )  # fmt: skip
    await session.flush()
    await materialize.rebuild_days(session, shop_id, [day])
    row = (await _product_rows(session, shop_id, "9003")).get(day)
    assert row is None or row.orders == 0
    # a row stored before the fix is read as the shop's 0, not 83
    await session.execute(
        ShopeeProductMetricsDaily.__table__.update()
        .where(
            ShopeeProductMetricsDaily.shop_id == shop_id,
            ShopeeProductMetricsDaily.day == day,
            ShopeeProductMetricsDaily.item_id == "__residual__",
        )
        .values(item_id="9003", orders=83, gmv=Decimal(0), source="file")
    )
    session.expire_all()
    sw = await stored.load_stored(session, shop_id, Window(day, day))
    assert sw is not None and sw.products["9003"].orders == 0
    rows = await funnel.load_rows(session, shop_id, Window(day, day))
    assert all(d.orders == 0 for d in rows.product_days if d.item_id == "9003")


async def test_a_stored_day_with_orders_and_no_costed_line_is_no_profit_on_read(session, shop_id):
    """Rows built before the fix hold profit = -ads_spend on such a day."""
    await session.execute(
        ShopeeShopMetricsDaily.__table__.update()
        .where(ShopeeShopMetricsDaily.shop_id == shop_id, ShopeeShopMetricsDaily.day == NO_LINES)
        .values(profit=Decimal("-35670.55"), buyer_paid_known=None)
    )
    session.expire_all()
    sw = await stored.load_stored(session, shop_id, Window(NO_LINES, NO_LINES))
    assert sw is not None and sw.orders == SHOP_ORDERS and sw.profit is None
    rows = await funnel.load_rows(session, shop_id, Window(NO_LINES, NO_LINES))
    assert all(d.profit is None for d in rows.shop_days)
