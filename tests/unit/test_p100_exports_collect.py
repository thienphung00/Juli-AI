"""P100 exports: the numbers of the files are the screens' numbers -- the Tổng quan export's
baseline / goal (shop, one product, the days) are ``month_plan.range_plan`` of the same period and
level; the Kế horatch export's month equals ``month_plans``. Synthetic reco shop (SQLite)."""

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
from tests.unit.test_p99_one_base import ITEM, _save_and_plan
from tests.unit.test_p100c_month_plan import _executed_plan_and_draft, _voucher
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor

FIRST = date(2026, 10, 1)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


KEYS = ("baseline_gmv", "goal_gmv", "baseline_profit", "goal_profit")


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


def _same(fig: tq.Figures, plan: dict) -> None:
    for k in KEYS:
        got, want = getattr(fig, k), plan[k]
        assert (got is None) == (want is None), k
        assert got is None or got == pytest.approx(want), k


async def test_export_goal_equals_range_plan_for_the_shop_and_a_product(session, shop, monkeypatch):
    seeded, _ = shop
    await _running_from(session, seeded, monkeypatch, date(2026, 10, 3))
    sid = seeded.shop_id
    kw = {"period": "custom", "start": FIRST, "end": AS_OF}

    data = await collect_tong_quan(session, sid, shop_name="Mẫu", now=NOW, **kw)
    plan = await month_plan.range_plan(
        session, sid, FIRST, AS_OF, scope=month_plan.SCOPE_RUNNING, now=NOW
    )
    assert plan["goal_gmv"] is not None
    _same(data.now, plan)
    for k in ("goal_gmv", "goal_profit", "baseline_gmv", "baseline_profit"):  # the days add up
        assert sum(getattr(d, k) for d in data.days) == pytest.approx(plan[k])
    assert len(data.days) == (AS_OF - FIRST).days + 1
    rows_total = sum(r.now.goal_gmv or 0 for r in data.products)
    assert rows_total == pytest.approx(plan["goal_gmv"])  # the "Cả shop" row closes the column

    one = await collect_tong_quan(session, sid, shop_name="Mẫu", now=NOW, product_id=ITEM, **kw)
    pplan = await month_plan.range_plan(
        session, sid, FIRST, AS_OF, scope=month_plan.SCOPE_RUNNING, now=NOW, product_id=ITEM
    )
    assert pplan["goal_gmv"] is not None
    _same(one.now, pplan)
    assert [r.product_id for r in one.products] == [ITEM] and one.product_id == ITEM
    assert sum(d.goal_gmv for d in one.days) == pytest.approx(pplan["goal_gmv"])
    wb = tq.build(one)
    assert wb.sheetnames == [
        tq.SHEET_OVERVIEW,
        tq.SHEET_CHANNEL,
        tq.SHEET_DAY,
        tq.SHEET_PRODUCT,
        tq.SHEET_SKU,
    ]
    assert ITEM in tq.file_name(one)


async def test_no_running_card_means_no_goal_in_the_export(session, shop):
    seeded, _ = shop
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="custom", start=FIRST, end=AS_OF
    )
    assert data.now.goal_gmv is None and data.now.goal_profit is None
    assert all(d.goal_gmv is None for d in data.days)


async def test_ke_hoach_export_month_equals_month_plans(session, shop, monkeypatch):
    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)
    sid = seeded.shop_id
    data = await collect_ke_hoach(session, sid, shop_name="Mẫu", now=NOW, month="2026-10")
    both = await month_plan.month_plans(session, sid, now=NOW, anchor=AS_OF)
    run = both[month_plan.SCOPE_RUNNING]
    assert data.month_first == FIRST and data.last_data_day == AS_OF
    assert data.baseline_gmv == pytest.approx(run["baseline_gmv"])
    rows = kh.daily_targets(data)
    assert sum(r["goal_gmv"] for r in rows) == pytest.approx(run["goal_gmv"])
    assert sum(r["goal_profit"] for r in rows) == pytest.approx(run["goal_profit"])
    assert kh.build(data).sheetnames == [kh.SHEET_CARDS, kh.SHEET_GOAL]
    with pytest.raises(ValueError):
        await collect_ke_hoach(session, sid, shop_name="Mẫu", now=NOW, month="2027-01")


async def test_sku_sheet_goals_sum_to_the_product_goal_and_actuals_to_the_product(
    session, shop, monkeypatch
):
    seeded, _ = shop
    await _running_from(session, seeded, monkeypatch, date(2026, 10, 3))
    kw = {"period": "custom", "start": FIRST, "end": AS_OF}
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, product_id=ITEM, **kw
    )
    pplan = await month_plan.range_plan(
        session, seeded.shop_id, FIRST, AS_OF, scope=month_plan.SCOPE_RUNNING, now=NOW,
        product_id=ITEM,
    )  # fmt: skip
    assert data.skus and all(k.product_name == data.product_name for k in data.skus)
    assert sum(k.revenue_goal or 0 for k in data.skus) == pytest.approx(pplan["goal_gmv"])
    assert sum(k.profit_goal or 0 for k in data.skus) == pytest.approx(pplan["goal_profit"])
    # actuals: the lines of the product (cancelled / returned left out)
    assert sum(k.revenue or 0 for k in data.skus) > 0
    assert all(k.need == 0 for k in data.skus if k.units_goal is not None)  # a finished period
    tq.build(data)


async def test_no_running_card_leaves_the_sku_goals_empty(session, shop):
    seeded, _ = shop
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="custom", start=FIRST, end=AS_OF
    )
    assert data.skus
    assert all(k.revenue_goal is None and k.units_goal is None for k in data.skus)
