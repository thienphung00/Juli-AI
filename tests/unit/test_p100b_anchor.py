"""P100 B.2: the window anchor is the last day with ``shop_overview`` (Shopee's daily totals).
A missing ``traffic_overview`` day no longer holds the window back; that day's traffic figures
stay ``None``. Synthetic data, SQLite."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.shopee_analytics import loaders, materialize
from tests.support.shopee_analytics import CUR_END, _daily, seed_shopee_shop


async def test_the_anchor_is_the_last_shop_overview_day_even_when_traffic_lags(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    later = CUR_END + timedelta(days=2)
    for i in (1, 2):
        session.add(
            _daily(
                seeded.shop_id,
                CUR_END + timedelta(days=i),
                "total",
                "all",
                orders=4,
                gmv=500_000,
                dataset="shop_overview",
            )
        )
    await session.flush()
    anchor = await loaders.load_anchor(session, seeded.shop_id)
    assert anchor is not None and anchor.day == later
    assert anchor.limited_by is None


async def test_traffic_ahead_of_shop_overview_does_not_move_the_anchor(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    much_later = CUR_END + timedelta(days=6)
    session.add(_daily(seeded.shop_id, much_later, "product_card", "all", impressions=9, gmv=1))
    await session.flush()
    anchor = await loaders.load_anchor(session, seeded.shop_id)
    assert anchor is not None and anchor.day == CUR_END and anchor.newest == much_later
    assert anchor.limited_by == "shop_overview"


async def test_without_shop_overview_the_traffic_datasets_still_anchor(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    from juli_backend.models.ingest import PlatformDailyMetric

    for row in (
        await session.execute(
            select(PlatformDailyMetric).where(
                PlatformDailyMetric.shop_id == seeded.shop_id,
                PlatformDailyMetric.dataset == "shop_overview",
            )
        )
    ).scalars():
        await session.delete(row)
    await session.flush()
    anchor = await loaders.load_anchor(session, seeded.shop_id)
    assert anchor is not None and anchor.day == CUR_END


async def test_a_day_with_totals_but_no_traffic_is_complete_and_its_traffic_is_none(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    day = CUR_END + timedelta(days=1)
    session.add(
        _daily(seeded.shop_id, day, "total", "all", orders=4, gmv=500_000, dataset="shop_overview")
    )
    await session.flush()
    await materialize.rebuild_days(session, seeded.shop_id, [CUR_END, day])
    rows = {
        r.day: r
        for r in (
            await session.execute(
                select(ShopeeShopMetricsDaily).where(
                    ShopeeShopMetricsDaily.shop_id == seeded.shop_id
                )
            )
        ).scalars()
    }
    assert rows[day].complete is True
    assert rows[day].views is None and rows[day].product_clicks is None
    assert rows[CUR_END].views is not None
    assert await loaders.default_as_of(session, seeded.shop_id) == day
