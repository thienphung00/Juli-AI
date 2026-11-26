"""batch-1117b K1-K3 / C1-C3: one card, one number, one total. A draft plan's rows, its aggregate
and the month view count the same cards and give the same Dự kiến (an estimable card run together
in a group is never left out of the plan total); a card's cost is one figure (per day x days); a
planned card is re-based on the plan's data day; an estimable card with no amount says why.
Synthetic reco shop only (SQLite, invented figures)."""

from __future__ import annotations

import copy
import uuid
from datetime import date, timedelta

import pytest

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_recommendations import (
    fill_queue_port,
    month_plan,
    plans,
    result_store,
    service,
    store,
)
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p99_one_base import COMBO, ITEM, _save_and_plan
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, _actor


@pytest.fixture
async def shop(session, monkeypatch):
    async def spy(_session, **kw):
        return None

    monkeypatch.setattr(fill_queue_port, "enqueue_for_approval", spy)
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded


def _voucher():
    """Starts today and ends inside today's month: every view counts it on all its days."""
    return sp.VoucherSpec(
        kind="voucher", scope="product", item_ids=[ITEM], discount_type="amount", value=20_000,
        min_spend=60_000, usage_limit=50, start=NOW.date(), end=NOW.date() + timedelta(days=6),
    )  # fmt: skip


async def _views(session, seeded):
    out = await month_plan.plan_with_month(session, seeded.shop_id, now=NOW, audience="seller")
    agg = out["aggregate"]
    rows = out["cards"]
    return out, agg, rows


async def _assert_agree(session, seeded):
    out, agg, rows = await _views(session, seeded)
    assert len(rows) == 2
    assert agg["n_cards"] == 2  # the plan counts every card, grouped or not
    assert agg["totals_estimable"] is True
    est = [
        c["result"]
        for g in [agg, *[g["aggregate"] for g in out["groups"]]]
        for c in g["cards"]
        if (c.get("result") or {}).get("estimable")
    ]
    # batch-1124-a R (#27 / #29): the combo is estimable too now (the combo prior), so both
    # cards are in the total -- was "the voucher is estimable, the combo is not"
    assert len(est) == 2
    assert agg["not_estimable_cards"] == []
    dgmv = sum(r["delta"]["p50"]["dgmv"] for r in est)
    dprofit = sum(r["delta"]["p50"]["dprofit"] for r in est)
    total = agg["dgmv_month"]["total"]
    assert total["p50"] == pytest.approx(dgmv)
    assert agg["dprofit_month"]["total"]["p50"] == pytest.approx(dprofit)
    assert agg["deltas_p50"]["gmv"] == pytest.approx(dgmv)
    assert agg["after"]["gmv_30d"] == pytest.approx(agg["today"]["gmv_30d"] + dgmv)
    # the month view is the same cards, the same Dự kiến per day: each card's own Δ x its days
    # inside the month (the voucher lies inside it; the undated combo runs 30 days from today,
    # so only its days up to the month's end count there)
    month = out["month"]["with_draft"]
    assert month["cards"] == 2
    first = date.fromisoformat(f"{month['month']}-01")
    last = first.replace(day=month["days_in_month"])

    def in_month(r) -> float:
        d = r["own"]["dates"]
        lo, hi = max(date.fromisoformat(d["from"]), first), min(date.fromisoformat(d["to"]), last)
        return max((hi - lo).days + 1, 0) / r["own"]["days"]

    assert any(in_month(r) < 1 for r in est)  # the month is not the 30-day plan horizon
    want_gmv = sum(r["own"]["delta"]["p50"]["dgmv"] * in_month(r) for r in est)
    want_profit = sum(r["own"]["delta"]["p50"]["dprofit"] * in_month(r) for r in est)
    assert month["uplift_gmv"] == pytest.approx(want_gmv, abs=1.0)
    assert month["uplift_profit"] == pytest.approx(want_profit, abs=1.0)
    # and the plan's own rows: the own Δ of a card whose dates are the horizon is its plan Δ
    for r in est:
        if r["own"]["days"] == agg["horizon"]["days"]:
            assert r["own"]["delta"]["p50"]["dgmv"] == pytest.approx(r["delta"]["p50"]["dgmv"])


async def test_k_rows_aggregate_and_month_agree_for_an_ungrouped_draft(session, shop):
    await _save_and_plan(session, shop, COMBO)
    await _save_and_plan(session, shop, _voucher())
    out, _, _ = await _views(session, shop)
    assert out["groups"] == []  # neither card was run together, so no group holds them
    await _assert_agree(session, shop)


async def test_k_an_estimable_card_run_together_is_never_left_out_of_the_total(session, shop):
    await _save_and_plan(session, shop, COMBO)
    saved, _ = await _save_and_plan(session, shop, _voucher())
    await plans.run_together(
        session, shop.shop_id, [(uuid.UUID(saved["id"]), 1)], actor=_actor(shop), now=NOW
    )
    out, agg, _ = await _views(session, shop)
    assert len(out["groups"]) == 1 and out["groups"][0]["aggregate"]["n_cards"] == 1
    await _assert_agree(session, shop)


# ------------------------------------------------------------------------------------------ C2


async def test_c2_one_cost_per_card_per_day_times_days(session, shop):
    saved, _ = await _save_and_plan(session, shop, _voucher())
    card_id = uuid.UUID(saved["id"])
    listed = await service.list_cards(session, shop.shop_id, audience="seller", now=NOW)
    row = next(c for c in listed["cards"] if c["id"] == str(card_id))
    detail = await service.card_detail(session, shop.shop_id, card_id, audience="seller")
    cost = detail["result"]["cost_total"]
    days = detail["result"]["own"]["days"]
    assert cost and cost > 0 and days == 7
    assert row["cost"] == detail["cost"] == cost
    spend = detail["card"]["spend"]
    assert spend["card_days"] == days
    assert spend["card_dchi_per_day"] * spend["card_days"] == pytest.approx(cost)
    assert row["cost_per_day"] * row["cost_days"] == pytest.approx(cost)
    assert spend["shop_chi_per_day_after"] == pytest.approx(
        spend["shop_chi_per_day_now"] + spend["card_dchi_per_day"]
    )


def test_c2_align_spend_replaces_the_certain_layers_rate_with_the_results():
    card = {
        "spend": {
            "shop_chi_per_day_now": 1000, "card_dchi_per_day": 2833.33, "cap": 5000,
            "shop_chi_per_day_after": 3833.33, "over_cap": False,
        }
    }  # fmt: skip
    block = {"cost_total": 119_769.0, "own": {"days": 30}}
    result_store.align_spend(card, block)
    s = card["spend"]
    assert s["card_dchi_per_day"] == pytest.approx(119_769 / 30)
    assert s["card_days"] == 30 and s["card_cost_total"] == 119_769.0
    assert s["shop_chi_per_day_after"] == pytest.approx(1000 + 119_769 / 30)
    assert s["over_cap"] is False
    card["spend"]["cap"] = 3000  # an over-cap card is flagged on the one cost
    result_store.align_spend(card, block)
    assert card["spend"]["over_cap"] is True
    # no result, no cost: the line is left as it was
    untouched = {"spend": {"card_dchi_per_day": 7}}
    result_store.align_spend(untouched, None)
    result_store.align_spend(untouched, {"cost_total": None, "own": {"days": 3}})
    assert untouched == {"spend": {"card_dchi_per_day": 7}}


# ------------------------------------------------------------------------------------------ C3


async def test_c3_a_planned_card_is_rebased_on_the_plans_data_day(session, shop):
    saved, _ = await _save_and_plan(session, shop, _voucher())
    card = await store.card_payload(session, shop.shop_id, uuid.UUID(saved["id"]))
    env = await load_env(session, shop.shop_id, as_of=AS_OF)
    block = result_store.version_result(card, 1)
    assert block["as_of"] == AS_OF.isoformat()
    assert result_store.is_fresh(block, env, card)
    assert result_store.is_fresh(block, env, card, same_day=True)
    newer = copy.copy(env)
    newer.as_of = AS_OF + timedelta(days=1)
    # F7.4: a newer data day makes every open card's result stale (recomputed each morning)
    assert not result_store.is_fresh(block, newer, card)
    assert not result_store.is_fresh(block, newer, card, same_day=True)


# ------------------------------------------------------------------------------------------ C1


def _block(estimable=True, noise=()):
    delta = {m: {"p10": -10.0, "p50": 50.0, "p90": 200.0} for m in ("gmv", "profit", "orders")}
    return {
        "estimable": estimable, "basis": "prior", "reason": None, "message": None,
        "own": {"days": 7, "dates": None, "delta": delta if estimable else None},
        "option": {"within_noise": list(noise)}, "cost_total": 700.0,
    }  # fmt: skip


def test_c1_an_estimable_card_with_amounts_shows_its_range():
    s = result_store.summary(_block())
    assert s["dgmv"] == {"p10": -10.0, "p50": 50.0, "p90": 200.0}
    assert s["dprofit"]["p50"] == 50.0 and s["no_amount_reason"] is None and s["within_noise"] == []


def test_c1_an_estimable_card_inside_the_noise_says_why_instead_of_a_blank():
    s = result_store.summary(_block(noise=("gmv", "profit", "orders")))
    assert s["estimable"] is True and s["dgmv"]["p50"] is None
    assert s["no_amount_reason"] == "Trong biên dao động"
    assert s["within_noise"] == ["gmv", "orders", "profit"]
    part = result_store.summary(_block(noise=("gmv",)))
    assert part["dgmv"]["p50"] is None and part["dprofit"]["p50"] == 50.0
    assert part["no_amount_reason"] is None
    gone = result_store.summary(_block(estimable=False))
    assert gone["not_estimable"] is True and gone["no_amount_reason"] is None
