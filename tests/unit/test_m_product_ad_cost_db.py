"""Decision #39 on the stored rows (SQLite, synthetic shop): an ads-by-product upload rebuilds the
days it covers, a product with an ad cost and no order keeps a row, the stored days add up to the
window figure of the screens."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import select

from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily
from juli_backend.services.shopee_analytics import loaders, materialize, service
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.shopee_analytics import (
    CUR_END,
    CUR_START,
    _daily,
    period_row,
    seed_shopee_shop,
)

AD_ONLY = "9999"


def _connector_day(shop_id, day, segment, cost):
    return _daily(
        shop_id, day, "ads", segment, dataset="ads_campaign_daily", order_type="placed",
        extra={"cost": cost, "ad_type": "product_mpd"},
    )  # fmt: skip


def _report(shop_id, item, segment, spend):
    return period_row(
        shop_id, "ads_campaign_period", CUR_START, CUR_END, item_id=item, order_type="placed",
        stream="ads", platform_source="Nhóm", segment=segment,
        extra={"ads_expense": spend},
    )  # fmt: skip


async def _stored(session, shop_id, item):
    t = ShopeeProductMetricsDaily
    rows = (await session.scalars(select(t).where(t.shop_id == shop_id, t.item_id == item))).all()
    return {r.day: r for r in rows}


async def test_an_ads_by_product_upload_rebuilds_the_days_and_they_add_up_to_the_window(session):
    seeded = await seed_shopee_shop(session)
    shop_id = seeded.shop_id
    days = [CUR_START + timedelta(days=i) for i in range((CUR_END - CUR_START).days + 1)]
    for d in days:
        session.add(_connector_day(shop_id, d, "cgroup1", 20_000))  # the seeded group campaign
        session.add(
            _connector_day(shop_id, d, "cx", 5_000)
        )  # a campaign of a product with no order
    session.add(_report(shop_id, AD_ONLY, "cx", 80))
    await session.flush()

    await materialize.after_ingest(
        session, shop_id, platform="shopee", dataset="ads_campaign_period",
        start=CUR_START, end=CUR_END,
    )  # fmt: skip
    session.expunge_all()

    one = await _stored(session, shop_id, "1001")
    assert one[days[0]].ads_spend == D(12_000)  # 20.000 x 60 / 100 of the group campaign
    only = await _stored(session, shop_id, AD_ONLY)
    row = only[days[0]]
    assert (row.gmv, row.orders, row.ads_spend, row.profit) == (D(0), 0, D(5_000), D(-5_000))
    # the days add up to the window figure the screens show (same helper, by construction)
    ctx = await loaders.load_context(session, shop_id)
    view = await service.load_view(session, shop_id, ctx, Window(CUR_START, CUR_END), rows="raw")
    for item in ("1001", "1002", "1003", AD_ONLY):
        stored = sum(
            (r.ads_spend or D(0) for r in (await _stored(session, shop_id, item)).values()), D(0)
        )
        assert abs(stored - view.ads.product_spend[item]) <= D(len(days)) / 2, item
    # a product with no basis is NULL, never 0
    t = ShopeeProductMetricsDaily
    others = await session.scalars(
        select(t).where(
            t.shop_id == shop_id,
            t.item_id.not_in(["1001", "1002", "1003", AD_ONLY]),
            t.item_id != "__other__",
        )
    )
    assert all(r.ads_spend is None for r in others.all() if r.gmv)
