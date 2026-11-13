"""P99: a Shopee period total is spread over its days, never stamped on one day; one day without
giá vốn no longer blanks the funnel's profit.

The shape follows the production finding (a product whose 30-day period file has ~600 đơn and
~21k lượt xem, days without order lines) with invented numbers only.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.services.shopee_analytics import materialize, period_spread
from juli_backend.services.shopee_analytics.funnel import (
    FunnelRows,
    ScopeDay,
    SourceDay,
    base_from_rows,
)
from juli_backend.services.shopee_analytics.materialize import split_sources
from juli_backend.services.shopee_analytics.period_spread import ShopDay
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.flows import FlowRow, FlowSource, build_flow_tables
from tests.support.builders import make_shop, make_user
from tests.support.shopee_analytics import _daily, period_row

START = date(2026, 9, 1)
DAYS = [START + timedelta(days=i) for i in range(30)]
END = DAYS[-1]
ITEM, OTHER = "7001", "7002"
#: the product's period file: 600 đơn, unit price ~27.5k (Doanh số 16.524.000đ), 21k views
P_ORDERS, P_GMV, P_VIEWS, P_CLICKS = 600, 16_524_000, 21_000, 780
OTHER_ORDERS, OTHER_GMV = 90, 13_500_000


def _shop_orders(i: int) -> int:
    return 22 + (i * 7) % 11  # 22..32 a day, ~800 over the period


# ------------------------------------------------------------------------------- pure


def test_spread_adds_up_to_the_total_and_follows_the_weights():
    weights = {d: Decimal(_shop_orders(i)) for i, d in enumerate(DAYS)}
    got = period_spread.spread(Decimal(P_ORDERS), weights)
    assert sum(got.values()) == P_ORDERS
    big, small = max(weights, key=weights.__getitem__), min(weights, key=weights.__getitem__)
    assert got[big] > got[small]


def test_a_capped_day_gives_its_excess_to_the_days_with_room():
    weights = {DAYS[0]: Decimal(10), DAYS[1]: Decimal(1), DAYS[2]: Decimal(1)}
    caps = {DAYS[0]: Decimal(3), DAYS[1]: Decimal(10), DAYS[2]: Decimal(10)}
    got = period_spread.spread(Decimal(12), weights, caps)
    assert got[DAYS[0]] == 3 and sum(got.values()) == 12
    assert all(got[d] <= caps[d] for d in got)


def test_a_product_never_out_sells_its_shop_even_when_the_period_file_says_more():
    """The production shape: the period file claims 600 đơn while the shop sold ~82."""
    series = {d: ShopDay(orders=(i % 3 == 0) * 8 + (i % 3 == 1) * 1) for i, d in enumerate(DAYS)}
    shop_total = sum(s.orders or 0 for s in series.values())
    assert 70 <= shop_total <= 100
    per_day = {
        d: period_spread.spread_totals(d, (START, END), Decimal(P_GMV), P_ORDERS, series)
        for d in DAYS
    }
    assert all(per_day[d][0] <= (series[d].orders or 0) for d in DAYS)
    assert sum(o for o, _ in per_day.values()) == shop_total  # capped at the shop, not 600/day
    assert sum((g for _, g in per_day.values()), Decimal(0)) == P_GMV


def test_traffic_is_spread_by_the_shops_views_not_repeated():
    series = {d: ShopDay(orders=5, views=1000 + 50 * i) for i, d in enumerate(DAYS)}
    got = [period_spread.spread_traffic(d, (START, END), P_VIEWS, P_CLICKS, series) for d in DAYS]
    assert sum(v or 0 for v, _ in got) == P_VIEWS and sum(c or 0 for _, c in got) == P_CLICKS
    assert got[-1][0] > got[0][0]  # the busier day gets more


def test_residual_orders_carry_gmv_when_the_flows_took_it_all():
    rows = [FlowRow("p", FlowSource.THE_SAN_PHAM_TOTAL, 1, Decimal(95_000), 500, 25)]
    table = build_flow_tables(rows, shop_gmv=Decimal(0)).shop
    got = {s.source: s for s in split_sources(table, 3, Decimal(90_000), None)}
    res = got["chenh_lech_nguon"]
    assert res.orders == 2 and res.gmv == 60_000  # 2 of 3 đơn at the AOV, never 0đ
    assert sum(s.orders for s in got.values()) == 3
    assert sum((s.gmv for s in got.values()), Decimal(0)) == 90_000


# --------------------------------------------------------------------------- funnel profit


def _funnel_rows(profits: list[Decimal | None]) -> FunnelRows:
    days = DAYS[: len(profits)]
    return FunnelRows(
        Window(days[0], days[-1]),
        tuple(
            SourceDay(d, None, "the_san_pham_khac", 100, 5, 2, Decimal(60_000), p)
            for d, p in zip(days, profits, strict=True)
        ),
        tuple(ScopeDay(d, None, 2, Decimal(60_000), p) for d, p in zip(days, profits, strict=True)),
    )


def test_one_day_without_cost_does_not_blank_the_window_profit():
    base = base_from_rows(_funnel_rows([Decimal(9_000), None, Decimal(11_000)]), "s")
    assert base.total("profit") == 20_000
    assert base.total("orders") == 6
    assert base.total("profit_orders") == 4  # only the days whose profit is known
    assert (base.profit_days, base.days) == (2, 3)


def test_no_known_day_keeps_the_profit_unknown():
    base = base_from_rows(_funnel_rows([None, None]), "s")
    assert base.total("profit") is None
    assert base.total("profit_orders") == 0 and (base.profit_days, base.days) == (0, 2)


# ------------------------------------------------------------------------------ tables


@pytest.fixture
async def shop_id(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee", shop_name="Synthetic P99 Shop")
    rows = []
    for i, d in enumerate(DAYS):
        o = _shop_orders(i)
        rows.append(
            _daily(shop.id, d, "total", "all", orders=o, gmv=o * 150_000, dataset="shop_overview")
        )
    session.add_all(rows)
    for item, gmv, orders in ((ITEM, P_GMV, P_ORDERS), (OTHER, OTHER_GMV, OTHER_ORDERS)):
        session.add(
            period_row(
                shop.id, "product_period", START, END,
                item_id=item, gmv=Decimal(gmv), orders=Decimal(orders),
            )
        )  # fmt: skip
    session.add(
        period_row(
            shop.id, "item_by_source_period", START, END, item_id=ITEM, stream="product_card",
            impressions=Decimal(P_VIEWS), clicks=Decimal(P_CLICKS),
            orders=Decimal(P_ORDERS), gmv=Decimal(P_GMV),
        )
    )  # fmt: skip
    await session.flush()
    return shop.id


async def _products(session, shop_id, item):
    q = select(ShopeeProductMetricsDaily).where(
        ShopeeProductMetricsDaily.shop_id == shop_id, ShopeeProductMetricsDaily.item_id == item
    )
    return {r.day: r for r in (await session.execute(q)).scalars()}


async def _shop(session, shop_id):
    q = select(ShopeeShopMetricsDaily).where(ShopeeShopMetricsDaily.shop_id == shop_id)
    return {r.day: r for r in (await session.execute(q)).scalars()}


async def test_the_backfill_spreads_the_period_over_its_days(session, shop_id):
    report = await materialize.backfill_shop(session, shop_id)
    assert report.days_written == 30
    rows, shop = await _products(session, shop_id, ITEM), await _shop(session, shop_id)
    assert set(rows) == set(DAYS)
    assert sum(r.orders for r in rows.values()) == P_ORDERS
    assert all(rows[d].orders <= shop[d].orders for d in DAYS)
    gmv = sum((r.gmv for r in rows.values()), Decimal(0))
    aov = gmv / P_ORDERS
    assert Decimal(25_000) <= aov <= Decimal(P_GMV) / P_ORDERS * Decimal("1.01")
    for d in DAYS:
        if rows[d].orders:
            assert rows[d].gmv / rows[d].orders > 20_000  # no 0đ / ~1k đơn
        assert rows[d].source == period_spread.ROW_SOURCE and rows[d].scaled_to_totals
    assert sum(r.views or 0 for r in rows.values()) == P_VIEWS  # not 21k on every day
    assert sum(r.clicks or 0 for r in rows.values()) == P_CLICKS
    assert max(r.views or 0 for r in rows.values()) < P_VIEWS / 10
    assert shop[END].sources["product_splits"] == "spread_product_period"
    assert shop[END].sources["product_traffic"] == "spread_product_period"
    assert sum(r.views or 0 for r in shop.values()) == P_VIEWS  # the shop's views follow


async def test_products_and_residual_still_add_up_to_the_shop_each_day(session, shop_id):
    await materialize.backfill_shop(session, shop_id)
    shop = await _shop(session, shop_id)
    items = [
        await _products(session, shop_id, i) for i in (ITEM, OTHER, RESIDUAL_ITEM)
    ]  # fmt: skip
    for d in DAYS:
        assert sum((rows[d].gmv for rows in items), Decimal(0)) == shop[d].gmv
    other = items[1]
    assert sum(r.orders for r in other.values()) == OTHER_ORDERS


async def test_rebuilding_one_day_gives_the_same_row_as_the_backfill(session, shop_id):
    await materialize.backfill_shop(session, shop_id)
    r = (await _products(session, shop_id, ITEM))[DAYS[9]]
    before = (r.orders, r.gmv, r.views)
    await session.execute(
        ShopeeProductMetricsDaily.__table__.update()
        .where(ShopeeProductMetricsDaily.id == r.id)
        .values(orders=P_ORDERS, views=P_VIEWS)
    )
    session.expire_all()
    await materialize.rebuild_days(session, shop_id, [DAYS[9]])  # the ingest hook's path
    session.expire_all()
    r = (await _products(session, shop_id, ITEM))[DAYS[9]]
    assert (r.orders, r.gmv, r.views) == before


# ------------------------------------------------------------------------------ ads ROAS


async def test_the_stored_ads_gmv_goes_with_the_stored_ad_spend(session):
    """Campaign days (1–7/10) take spend and GMV from the campaign report, the days before from
    the daily ads table: ROAS 5.0 everywhere, never daily GMV ÷ report spend (10.5)."""
    from tests.support.shopee_analytics import CUR_END, CUR_START, PREV_START, seed_shopee_shop

    seeded = await seed_shopee_shop(session, rules=True)
    shop = await _shop(session, seeded.shop_id)

    def roas(start, end):
        days = [r for d, r in shop.items() if start <= d <= end and r.ads_spend]
        spend = sum((r.ads_spend for r in days), Decimal(0))
        gmv = sum((r.ads_gmv for r in days), Decimal(0))
        return (gmv / spend).quantize(Decimal("0.01"))

    assert roas(CUR_START, CUR_END) == Decimal("5.00")
    assert roas(PREV_START, CUR_END) == Decimal("5.00")
