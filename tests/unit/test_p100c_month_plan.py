"""P100 canvas: Kế hoạch's month figures come from ONE function -- Tổng quan's plan block and the
Kế hoạch "Đang chạy" total are the same numbers; "Nếu áp dụng nháp" adds the draft. Running =
executed plans only; goals are baseline + the cards' Δ on their days inside the month. Synthetic
reco shop only (SQLite, invented figures)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_plans import PLAN_DRAFT, PLAN_EXECUTED, ShopRecoPlan
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_analytics.channel_split import plan_block_of
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import fill_queue_port, month_plan, plans
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import ITEM, _save_and_plan
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


def _voucher(start: date, days: int, value: int = 20_000):
    return sp.VoucherSpec(
        kind="voucher", scope="product", item_ids=[ITEM], discount_type="amount", value=value,
        min_spend=60_000, usage_limit=50, start=start, end=start + timedelta(days=days - 1),
    )  # fmt: skip


async def _executed_plan_and_draft(session, seeded, monkeypatch):
    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    # the running card starts mid-month (15 Oct, 10 days); the draft card is 20 Oct, 5 days
    await _save_and_plan(session, seeded, _voucher(date(2026, 10, 15), 10))
    await plans.confirm(
        session, seeded.shop_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    plan = await session.scalar(select(ShopRecoPlan).where(ShopRecoPlan.status != PLAN_DRAFT))
    plan.status = PLAN_EXECUTED
    await session.commit()
    await _save_and_plan(session, seeded, _voucher(date(2026, 10, 20), 5, value=30_000))


async def test_running_is_executed_plans_only_and_draft_adds_on_top(session, shop, monkeypatch):
    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)
    both = await month_plan.month_plans(session, seeded.shop_id, now=NOW, anchor=AS_OF)
    run, with_draft = both["running"], both["running+draft"]
    assert run["cards"] == 1 and with_draft["cards"] == 2
    assert run["month"] == "2026-10" and run["days_in_month"] == 31 and run["day"] == 7
    assert run["goal_gmv"] == pytest.approx(run["baseline_gmv"] + run["uplift_gmv"])
    assert with_draft["baseline_gmv"] == run["baseline_gmv"]
    assert with_draft["uplift_gmv"] != run["uplift_gmv"]
    assert with_draft["goal_gmv"] == pytest.approx(
        with_draft["baseline_gmv"] + with_draft["uplift_gmv"]
    )
    assert run["mtd_gmv"] == with_draft["mtd_gmv"] and run["mtd_gmv"] > 0


async def test_a_confirmed_plan_does_not_run_and_no_running_card_means_no_goal(
    session, shop, monkeypatch
):
    seeded, _ = shop

    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    await _save_and_plan(session, seeded, _voucher(date(2026, 10, 15), 10))
    out = await month_plan.month_plans(session, seeded.shop_id, now=NOW, anchor=AS_OF)
    assert out["running"]["cards"] == 0 and out["running"]["goal_gmv"] is None
    assert out["running"]["goal_profit"] is None and out["running"]["uplift_gmv"] == 0
    assert out["running+draft"]["cards"] == 1 and out["running+draft"]["goal_gmv"] is not None
    await plans.confirm(
        session, seeded.shop_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )  # confirmed: still not running
    again = await month_plan.month_plan(
        session, seeded.shop_id, scope="running", now=NOW, anchor=AS_OF
    )
    assert again["cards"] == 0 and again["goal_gmv"] is None


async def test_a_card_counts_only_its_days_inside_the_month():
    card = {
        "result": {
            "own": {
                "dates": {"from": "2026-10-28", "to": "2026-11-06"},
                "days": 10,
                "delta": {"p50": {"dgmv": 1000.0, "dprofit": 100.0}},
            }
        }
    }
    gmv, profit, n = month_plan.uplift_in_month([card], date(2026, 10, 1), date(2026, 10, 31))
    assert (gmv, profit, n) == (400.0, 40.0, 1)  # 4 of its 10 days are in October
    assert month_plan.uplift_in_month([card], date(2026, 12, 1), date(2026, 12, 31)) == (0, 0, 0)


async def test_tong_quan_and_the_ke_hoach_total_come_from_the_same_function(
    session, shop, monkeypatch
):
    from juli_backend.services.shopee_analytics import channel_split as cs

    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)
    split = await cs._plan_block(session, seeded.shop_id, None, AS_OF)
    screen = await month_plan.plan_with_month(session, seeded.shop_id, now=NOW, audience="seller")
    running = screen["month"]["running"]
    assert split == plan_block_of(running)  # Tổng quan's block IS the Kế hoạch "Đang chạy" total
    assert split["gmv"]["goal"] == running["goal_gmv"] and split["gmv"]["goal"] is not None
    assert split["profit"]["now"] == running["mtd_profit"]
    assert screen["month"]["with_draft"]["cards"] == 2
    assert screen["month"]["with_draft"]["goal_gmv"] != running["goal_gmv"]
