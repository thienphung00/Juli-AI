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


async def test_ke_hoach_running_goal_is_the_baseline_when_no_plan_runs(session, shop, monkeypatch):
    """Kế hoạch's bars once drew nothing ("Đang chạy — → 12,92 tr"): with no executed plan the
    running goal is the baseline level. Tổng quan / the exports keep ``None`` (no goal to show)."""
    seeded, _ = shop

    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    await _save_and_plan(session, seeded, _voucher(date(2026, 10, 15), 10))
    screen = await month_plan.plan_with_month(session, seeded.shop_id, now=NOW, audience="seller")
    run = screen["month"]["running"]
    assert run["cards"] == 0 and run["baseline_gmv"] is not None
    assert run["goal_gmv"] == run["baseline_gmv"] and run["goal_profit"] == run["baseline_profit"]
    assert (
        screen["month"]["with_draft"]["goal_gmv"] > run["goal_gmv"]
    )  # the draft still adds on top
    plain = await month_plan.month_plan(
        session, seeded.shop_id, scope="running", now=NOW, anchor=AS_OF
    )
    assert plain["goal_gmv"] is None  # Tổng quan / exports: nothing runs, no goal


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
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    rng = await month_plan.range_plan(
        session, seeded.shop_id, first, last, scope="running", now=NOW, actual_to=AS_OF
    )
    screen = await month_plan.plan_with_month(session, seeded.shop_id, now=NOW, audience="seller")
    running = screen["month"]["running"]
    assert rng["goal_gmv"] == running["goal_gmv"] and rng["goal_gmv"] is not None
    assert rng["actual_profit"] == running["mtd_profit"]
    block = cs.plan_block_of(rng)
    assert block["gmv"]["goal"] == running["goal_gmv"] and block["days"] == 31
    assert screen["month"]["with_draft"]["cards"] == 2
    assert screen["month"]["with_draft"]["goal_gmv"] != running["goal_gmv"]


async def test_range_plan_sums_baseline_per_day_and_the_uplift_on_the_days_in_range(
    session, shop, monkeypatch
):
    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)  # card: 15-24 Oct
    week = await month_plan.range_plan(
        session, seeded.shop_id, date(2026, 10, 1), date(2026, 10, 7), scope="running", now=NOW,
        actual_to=AS_OF,
    )  # fmt: skip
    assert week["days"] == 7 and week["cards"] == 0 and week["goal_gmv"] is None  # card not in it
    month = await month_plan.range_plan(
        session, seeded.shop_id, date(2026, 10, 1), date(2026, 10, 31), scope="running", now=NOW,
        actual_to=AS_OF,
    )  # fmt: skip
    ten = await month_plan.range_plan(
        session, seeded.shop_id, date(2026, 10, 15), date(2026, 10, 24), scope="running", now=NOW,
    )  # fmt: skip
    assert ten["uplift_gmv"] == month["uplift_gmv"]  # all of the card's days are inside both
    assert ten["baseline_gmv"] * 31 == pytest.approx(month["baseline_gmv"] * 10)
    assert ten["goal_gmv"] == pytest.approx(ten["baseline_gmv"] + ten["uplift_gmv"])


async def test_today_marker_only_when_the_range_includes_today_and_ahead_is_pro_rated(
    session, shop, monkeypatch
):
    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)
    today = NOW.date()
    past = await month_plan.range_plan(
        session, seeded.shop_id, date(2026, 10, 1), date(2026, 10, 31), scope="running", now=NOW,
        actual_to=AS_OF,
    )  # fmt: skip
    if date(2026, 10, 1) <= today <= date(2026, 10, 31):
        assert past["today_marker"] == pytest.approx(past["day"] / 31)
    else:
        assert past["today_marker"] is None and past["day"] == 31
    gone = await month_plan.range_plan(
        session, seeded.shop_id, date(2026, 9, 1), date(2026, 9, 30), scope="running", now=NOW,
        actual_to=date(2026, 9, 30),
    )  # fmt: skip
    assert gone["today_marker"] is None and gone["day"] == 30
    assert gone["ahead_gmv"] is None or gone["ahead_gmv"] == (
        gone["actual_gmv"] >= gone["goal_gmv"]
    )


def _card(product, dgmv, dprofit, frm="2026-10-10", to="2026-10-19", days=10):
    return {
        "product_id": product,
        "result": {
            "own": {
                "dates": {"from": frm, "to": to},
                "days": days,
                "delta": {"p50": {"dgmv": dgmv, "dprofit": dprofit}},
            }
        },
    }


def test_product_uplifts_plus_shop_wide_uplift_make_the_shop_uplift():
    cards = [_card("A", 1000.0, 100.0), _card("B", 500.0, 50.0), _card(None, 200.0, 20.0)]
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    shop = month_plan.uplift_in_month(month_plan.cards_of_product(cards, None), first, last)
    a = month_plan.uplift_in_month(month_plan.cards_of_product(cards, "A"), first, last)
    b = month_plan.uplift_in_month(month_plan.cards_of_product(cards, "B"), first, last)
    wide = month_plan.uplift_in_month([c for c in cards if c["product_id"] is None], first, last)
    assert a[:2] == (1000.0, 100.0) and b[:2] == (500.0, 50.0)  # no shop-wide card in a product
    assert shop[0] == pytest.approx(a[0] + b[0] + wide[0]) and shop[2] == 3
    assert shop[1] == pytest.approx(a[1] + b[1] + wide[1])


async def test_range_plan_at_product_level_counts_only_that_products_cards(
    session, shop, monkeypatch
):
    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)  # one running card on ITEM
    first, last = date(2026, 10, 1), date(2026, 10, 31)
    whole = await month_plan.range_plan(
        session, seeded.shop_id, first, last, scope="running", now=NOW, actual_to=AS_OF
    )
    mine = await month_plan.range_plan(
        session, seeded.shop_id, first, last, scope="running", now=NOW, actual_to=AS_OF,
        product_id=ITEM,
    )  # fmt: skip
    other = await month_plan.range_plan(
        session, seeded.shop_id, first, last, scope="running", now=NOW, actual_to=AS_OF,
        product_id="not-this-one",
    )  # fmt: skip
    assert mine["product_id"] == ITEM and mine["cards"] == 1
    assert mine["uplift_gmv"] == whole["uplift_gmv"]  # the only card is this product's
    assert other["cards"] == 0 and other["uplift_gmv"] == 0 and other["goal_gmv"] is None
    assert mine["actual_gmv"] is not None and mine["actual_gmv"] <= whole["actual_gmv"]


async def test_running_range_is_the_span_of_the_running_cards(session, shop, monkeypatch):
    seeded, _ = shop
    assert await month_plan.running_range(session, seeded.shop_id, now=NOW) is None  # none running
    await _executed_plan_and_draft(session, seeded, monkeypatch)  # running 15-24 Oct; draft 20-24
    span = (date(2026, 10, 15), date(2026, 10, 24))
    assert await month_plan.running_range(session, seeded.shop_id, now=NOW) == span
    assert await month_plan.running_range(session, seeded.shop_id, ITEM, now=NOW) == span
    assert await month_plan.running_range(session, seeded.shop_id, "other", now=NOW) is None


async def test_period_plan_falls_back_to_30_days_without_a_usable_span(session, shop, monkeypatch):
    from juli_backend.services.shopee_analytics import channel_split as cs

    seeded, _ = shop
    await _executed_plan_and_draft(session, seeded, monkeypatch)
    # the span starts after the newest data day (AS_OF): the 30-day window answers instead
    out = await cs.channel_split(session, seeded.shop_id, period="plan", as_of=AS_OF)
    assert out["days"] == 30 and out["plan_range"] == {"from": "2026-10-15", "to": "2026-10-24"}
    nope = await cs.channel_split(
        session, seeded.shop_id, period="plan", as_of=AS_OF, product_id="other"
    )
    assert nope["plan_range"] is None and nope["days"] == 30


async def test_ke_hoach_shows_the_running_totals_when_the_draft_is_empty(
    session, shop, monkeypatch
):
    """An executed plan and NO draft: Kế hoạch's "Đang chạy" and "Nếu áp dụng nháp" are both the
    running total (the one Tổng quan shows), never empty."""
    seeded, _ = shop

    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    await _save_and_plan(session, seeded, _voucher(date(2026, 10, 15), 10))
    await plans.confirm(
        session, seeded.shop_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    plan = await session.scalar(select(ShopRecoPlan).where(ShopRecoPlan.status != PLAN_DRAFT))
    plan.status = PLAN_EXECUTED
    await session.commit()
    screen = await month_plan.plan_with_month(session, seeded.shop_id, now=NOW, audience="seller")
    run, with_draft = screen["month"]["running"], screen["month"]["with_draft"]
    assert run["goal_gmv"] is not None and run["goal_profit"] is not None
    assert with_draft["goal_gmv"] == run["goal_gmv"]
    assert with_draft["goal_profit"] == run["goal_profit"]


async def test_ke_hoach_month_follows_the_running_cards_when_the_data_month_has_none(
    session, shop, monkeypatch
):
    """The running plan's days all fall after the data's month: the month bars show the month of
    the running cards, so "Đang chạy" is never empty while Tổng quan shows the plan."""
    seeded, _ = shop

    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    await _save_and_plan(session, seeded, _voucher(date(2026, 11, 5), 10))
    await plans.confirm(
        session, seeded.shop_id, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    plan = await session.scalar(select(ShopRecoPlan).where(ShopRecoPlan.status != PLAN_DRAFT))
    plan.status = PLAN_EXECUTED
    await session.commit()
    screen = await month_plan.plan_with_month(session, seeded.shop_id, now=NOW, audience="seller")
    run = screen["month"]["running"]
    assert run["month"] == "2026-11" and run["cards"] == 1
    assert screen["month"]["with_draft"]["goal_gmv"] == run["goal_gmv"]
