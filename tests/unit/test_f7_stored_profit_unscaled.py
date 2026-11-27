"""F7.10 (owner rule P100 B.5): the stored daily profit (shop and product rows) is the unscaled
known-cost profit, the figure ``shop_profit_of`` shows on the dashboard; rows built by an older
rule are rebuilt automatically. Synthetic shop only (SQLite, invented figures)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from sqlalchemy import func, select, update

from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.shopee_analytics import loaders, materialize, service
from juli_backend.services.shopee_analytics.shared import shop_profit_of
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.shopee_analytics import CUR_END, CUR_START, seed_shopee_shop

pytestmark = pytest.mark.usefixtures("ungated_profit")


async def _window_sum(session, shop_id) -> D:
    t = ShopeeShopMetricsDaily
    return D(
        (
            await session.execute(
                select(func.sum(t.profit)).where(
                    t.shop_id == shop_id, t.day >= CUR_START, t.day <= CUR_END
                )
            )
        ).scalar_one()
    )


async def test_the_stored_window_profit_is_the_dashboard_known_cost_profit(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    ctx = await loaders.load_context(session, sid)
    view = await service.load_view(session, sid, ctx, Window(CUR_START, CUR_END))
    # a day where the order lines are not the shop's GMV: the old stored profit was scaled
    assert view.metrics.gmv_scale is not None and view.metrics.gmv_scale != 1
    headline = shop_profit_of(view).profit
    assert headline is not None
    assert abs(await _window_sum(session, sid) - headline) <= 7  # whole đồng per day
    assert (await _window_sum(session, sid)) != (headline * view.metrics.gmv_scale).quantize(D(1))
    detail = (
        await session.execute(
            select(ShopeeShopMetricsDaily.detail).where(ShopeeShopMetricsDaily.shop_id == sid)
        )
    ).scalars()
    assert {d.get("rows_v") for d in detail} == {materialize.ROWS_VERSION}


async def test_rows_built_by_an_older_rule_are_rebuilt_automatically(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    good = await _window_sum(session, sid)
    t = ShopeeShopMetricsDaily
    old = (await session.execute(select(t.detail).where(t.shop_id == sid).limit(1))).scalar_one()
    await session.execute(update(t).where(t.shop_id == sid).values(profit=D(1), detail={}))
    await session.flush()
    session.expunge_all()
    assert len(await materialize.outdated_days(session, sid)) > 0
    assert await materialize.rebuild_outdated(session, sid) > 0
    session.expunge_all()
    assert await _window_sum(session, sid) == good
    assert await materialize.outdated_days(session, sid) == []
    assert await materialize.rebuild_outdated(session, sid) == 0
    assert old.get("rows_v") == materialize.ROWS_VERSION
