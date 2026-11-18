"""P100 exports: the numbers of the files are the screens' numbers -- the Kế hoạch export's goal
is ``month_plan.range_plan`` of the range; its cards are the ones active in the range. Synthetic
reco shop (SQLite)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_plans import PLAN_DRAFT, PLAN_EXECUTED, ShopRecoPlan
from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import collect_ke_hoach, collect_tong_quan
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_recommendations import fill_queue_port, month_plan, plans
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import _save_and_plan
from tests.unit.test_p100c_month_plan import _executed_plan_and_draft, _voucher
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor

FIRST = date(2026, 10, 1)
MONTH_END = date(2026, 10, 31)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


async def _running_from(session, seeded, monkeypatch, start: date):
    """One executed plan whose voucher card runs ``start`` + 10 days (inside the data window)."""

    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    await _save_and_plan(session, seeded, _voucher(start, 10))
    await plans.confirm(
        session, seeded.shop_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    plan = await session.scalar(select(ShopRecoPlan).where(ShopRecoPlan.status != PLAN_DRAFT))
    plan.status = PLAN_EXECUTED
    await session.commit()


async def test_ke_hoach_export_lists_the_cards_active_in_the_range_and_the_goal(
    session, shop, monkeypatch
):
    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)
    sid = seeded.shop_id
    data = await collect_ke_hoach(
        session, sid, shop_name="Mẫu", now=NOW, start=FIRST, end=MONTH_END
    )
    run = await month_plan.range_plan(
        session, sid, FIRST, MONTH_END, actual_to=AS_OF, scope=month_plan.SCOPE_RUNNING, now=NOW
    )
    assert data.start == FIRST and data.end == MONTH_END and data.shops == ["Mẫu"]
    assert data.goals[0].shop == "Mẫu"
    assert data.goals[0].baseline_gmv == pytest.approx(run["baseline_gmv"])
    assert len(data.days) == 31
    assert kh.DRAFT in {c.status for c in data.cards}
    assert all(kh.active_in(c, FIRST, MONTH_END) for c in data.cards)
    assert kh.SHEET_HISTORY in kh.build(data).sheetnames
    with pytest.raises(ValueError):
        await collect_ke_hoach(session, sid, shop_name="Mẫu", now=NOW, start=AS_OF, end=FIRST)


async def test_tong_quan_export_reads_each_window_once_not_per_product(session, shop, monkeypatch):
    """Speed guard: the per-product loop reuses the loaded views (the channel split of a loaded
    view), so the number of period views read does not grow with the number of products."""
    from juli_backend.services.shopee_analytics import service as analytics_service

    seeded, _ = shop
    await _running_from(session, seeded, monkeypatch, date(2026, 10, 2))
    real = analytics_service.load_view
    calls: list[int] = []

    async def counting(*a, **kw):
        calls.append(1)
        return await real(*a, **kw)

    monkeypatch.setattr(analytics_service, "load_view", counting)
    data = await collect_tong_quan(session, seeded.shop_id, shop_name="Shop", now=NOW, as_of=AS_OF)
    products = len([r for r in data.products if r.name])
    assert products >= 1
    # current + previous window, plus the baseline windows of the per-product plan levels
    # + the fixed reads of the report sheets (month before, KOC, critical metrics): none per product
    assert len(calls) <= 4 + products + 4


async def test_export_lists_every_active_listing_and_the_days_own_totals(session, shop):
    """ORY Oct export: 6 of ~28 active listings, days that only counted affiliate, a negative
    "Cả shop". Every active listing is a row, a stored day carries its own GMV / orders, and no
    "Cả shop" channel cell is negative."""
    from juli_backend.services.exports import collect
    from juli_backend.services.shopee_analytics import service as sa_service

    seeded, _ = shop
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="custom", start=FIRST, end=AS_OF
    )
    window = await sa_service.resolve(
        session, seeded.shop_id, period="custom", start=FIRST, end=AS_OF
    )
    view, rows = await collect._view(session, seeded.shop_id, window)
    listed = {p.product_id for p in data.products}
    assert set(view.active_items) <= listed
    stored = {d.day: d for d in rows.shop_days}
    for day in data.days:
        if day.day in stored:
            assert day.total_gmv == float(stored[day.day].gmv)
            assert day.total_orders == float(stored[day.day].orders)
    rest = data.products[-1]
    assert rest.product_id == tq.SHOP_ROW_LABEL
    for key in tq.CHANNELS:
        g = rest.now.channel(key).gmv
        assert g is None or g >= 0


async def test_the_profit_sheet_adds_up_to_the_dashboard_profit(session, shop):
    """Owner Q3 (2026-11-17): the "Lợi nhuận" sheet's cost lines take the revenue down to the
    same profit and margin the Tổng quan screen shows; the product level has no such sheet."""
    from juli_backend.services.exports import collect
    from juli_backend.services.shopee_analytics import service as sa_service
    from juli_backend.services.shopee_analytics.shared import shop_profit_of

    seeded, _ = shop
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="custom", start=FIRST, end=AS_OF
    )
    window = await sa_service.resolve(
        session, seeded.shop_id, period="custom", start=FIRST, end=AS_OF
    )
    view, _rows = await collect._view(session, seeded.shop_id, window)
    kp = shop_profit_of(view)
    b = data.bridge
    assert b is not None and kp.profit is not None
    assert b.profit == float(kp.profit) and b.margin_pct == float(kp.margin_pct)
    costs = (
        b.fees + b.cogs + b.packaging + b.commission + b.shipping_other + b.ads
        + b.other_marketing
    )  # fmt: skip
    assert b.revenue - costs == pytest.approx(b.profit, abs=1)  # whole-đồng bridge lines
    assert b.revenue == float(kp.buyer_paid)  # the margin base
    sheet = tq.build(data)[tq.SHEET_PROFIT]
    labels = [sheet.cell(r, 1).value for r in range(1, sheet.max_row + 1)]
    assert "Lợi nhuận bán hàng trên sàn" in labels
    assert not any(isinstance(v, str) and v.startswith("Tổng chi phí") for v in labels)
    product = data.products[0].product_id
    one = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="custom", start=FIRST,
        end=AS_OF, product_id=product,
    )  # fmt: skip
    assert one.bridge is None and tq.SHEET_PROFIT not in tq.build(one).sheetnames
