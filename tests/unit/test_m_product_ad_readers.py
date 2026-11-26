"""Decision #39, M3: every product-level reader of the product ad cost reads the stored column
(the one cost per product). Excel product-day "Quảng cáo", the forecast base's ad days. Synthetic
shop; the stored rows are set by hand so the test names the value it expects."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import update

from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily
from juli_backend.services.exports.collect import collect_tong_quan
from juli_backend.services.shopee_analytics import forecast_base, funnel, materialize
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.shopee_reco import AS_OF, seed_reco_shop

ITEM = "1001"
NOW = datetime(2026, 11, 1, 9)
FIRST = date(2026, 10, 1)


async def _seeded(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    return seeded


async def _set_ads(session, shop_id, day, value):
    t = ShopeeProductMetricsDaily
    await session.execute(
        update(t)
        .where(t.shop_id == shop_id, t.item_id == ITEM, t.day == day, t.variation_id.is_(None))
        .values(ads_spend=value)
    )


async def test_the_excel_product_day_ad_cell_is_the_stored_cost_and_none_without_a_basis(session):
    seeded = await _seeded(session)
    sid = seeded.shop_id
    with_cost, without = FIRST + timedelta(days=2), FIRST + timedelta(days=3)
    await _set_ads(session, sid, with_cost, D("1234.00"))
    await _set_ads(session, sid, without, None)  # no basis that day: "—", never 0
    await session.flush()
    data = await collect_tong_quan(
        session, sid, shop_name="Mẫu", now=NOW, period="custom", start=FIRST, end=AS_OF,
        product_id=ITEM,
    )  # fmt: skip
    days = {d.day: d for d in data.days}
    assert days[with_cost].ads_cost == 1234.0
    assert days[without].ads_cost is None


async def test_the_forecast_base_ad_days_follow_the_stored_product_column(session):
    seeded = await _seeded(session)
    sid = seeded.shop_id
    w = Window(FIRST, AS_OF)
    for i in range((AS_OF - FIRST).days + 1):
        await _set_ads(session, sid, FIRST + timedelta(days=i), None)
    last = FIRST + timedelta(days=4)
    await _set_ads(session, sid, last, D("777.00"))
    await session.flush()
    rows = await funnel.load_rows(session, sid, w)
    mine = [d for d in rows.product_days if d.item_id == ITEM]
    assert [d.ads_spend for d in mine if d.day == last] == [D("777.00")]
    # the newest product ad day is the stored one; the shop-level source rows are not read here
    product_only = funnel.FunnelRows(w, (), (), tuple(mine), rows.unavailable)
    assert forecast_base.last_days(product_only).ads == last
    # a day after the ads figure is unknown (None), a day up to it keeps the stored cost
    cut = forecast_base._slice(product_only, FIRST, AS_OF, last)
    assert {d.day: d.ads_spend for d in cut.product_days}[last] == D("777.00")
    cut_before = forecast_base._slice(product_only, FIRST, AS_OF, last - timedelta(days=1))
    assert {d.day: d.ads_spend for d in cut_before.product_days}[last] is None
