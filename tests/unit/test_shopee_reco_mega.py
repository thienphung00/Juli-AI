"""P90 step 8: `mega_sale`, the composite card for a campaign window (contract 12) --
Sigma of the children's certain layers on the SAME orders without double counting, one price
lever per order line, the floor across stacked discounts, one budget cap, the product lock."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_profit.money import to_dong
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.mega import (
    MegaWindow,
    build_mega_card,
    children_from_card,
    evaluate_mega,
    fit_children,
    precedence_lever,
    schedule_for,
    select_children,
    window_from_card,
)
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
WINDOW = MegaWindow(datetime(2026, 11, 11, 0, 0), datetime(2026, 11, 12, 0, 0))


@pytest.fixture
async def env(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    e = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert e is not None
    return e


def _children():
    return [
        Candidate("product_discount", ("1001",), {"discount_pct": 15}),
        Candidate("bundle_deal", ("1001",), {"tier2_pct": 4, "tier3_pct": 6}),
        Candidate(
            "min_spend_voucher",
            ("1002",),
            {"value": 3000, "min_spend": 50_000, "quantity": 100_000, "days": 1},
        ),
        Candidate("ads_budget", (), {"daily_budget": 40_000}, campaign_key="cgroup1"),
    ]


def test_the_window_counts_whole_days():
    assert WINDOW.days == 1 and MegaWindow(datetime(2026, 11, 10), datetime(2026, 11, 13)).days == 3


async def test_a_mega_sale_card_lists_its_children_one_schedule_one_budget_one_lock(env):
    card = build_mega_card(env, _children(), WINDOW, now=NOW, budget_cap_per_day=D(200_000))
    assert card is not None
    assert card["family"] == "mega_sale" and card["bundle"] is True
    assert [c["change_kind"] for c in card["children"]] == [
        "product_discount",
        "bundle_deal",
        "min_spend_voucher",
        "ads_budget",
    ]
    assert (
        card["locked_items"] == ["1001", "1002"] and card["lock"]["until"] == WINDOW.end.isoformat()
    )
    assert card["inputs"]["budget_cap_per_day"] == 200_000
    assert card["measurement_plan"]["bundle"] is True and "gói" in card["measurement_plan"]["note"]
    # one schedule: a single day -> every child goes on at the start and off at the end
    (day,) = card["schedule"]
    assert day["date"] == "2026-11-11"
    assert [e["action"] for e in day["events"]].count("bat") == 4 and [
        e["action"] for e in day["events"]
    ].count("tat") == 4
    # the sheet lists the children in schedule order, with their own pages
    steps = card["execution_sheet"]["steps"]
    assert [s["child_card_id"] for s in steps] == [None] * 4 and len(steps) == 4
    assert card["execution_sheet"]["time_window"]["days"] == 1
    assert {c["change_kind"] for c in card["execution_sheet"]["changes"]} >= {
        "price",
        "daily_budget",
    }


async def test_the_stacked_discount_is_counted_once_and_adds_up_by_lever(env):
    res = evaluate_mega(env, _children()[:3], WINDOW, D(500_000))
    c = res["certain"]
    assert c["by_lever_adds_up"] is True
    levers = {r["lever"]: r for r in c["by_lever"]}
    assert sum(r["discount"] for r in c["by_lever"]) == pytest.approx(c["total_discount"], abs=2)
    assert levers["khuyen_mai"]["lines"] > 0  # the promo price dominates the voucher by precedence
    # by hand: promo discount on every 1001 line, plus the voucher on orders reaching
    # 50.000 afterwards
    scale = D(1) / D(env.window_days)
    new = {s: (env.list_price(s) * D("0.85") // 100) * 100 for s in env.skus_of("1001")}
    orders: dict[str, D] = {}
    promo = D(0)
    for ln in env.lines_for(["1001", "1002"]):
        deal = new.get(ln.sku, ln.deal_price) if ln.sku in new else ln.deal_price
        deal = min(deal, ln.deal_price) if ln.sku in new else deal
        promo += (ln.original_price - deal) * ln.qty
        orders[ln.order_id] = orders.get(ln.order_id, D(0)) + deal * ln.qty
    # the bundle child is absent from [:3]? it is present: tiers apply only to qty >= 2 lines
    bundle = sum(
        (
            to_dong(
                min(new[ln.sku], ln.deal_price) * ln.qty * (D(6) if ln.qty >= 3 else D(4)) / 100
            )
            for ln in env.lines_for(["1001", "1002"])
            if ln.sku in new and ln.qty >= 2
        ),
        D(0),
    )
    voucher = sum((D(3000) for sub in orders.values() if sub >= 50_000), D(0))
    assert c["total_discount"] == pytest.approx(float((promo + bundle + voucher) * scale), abs=5)


async def test_stacking_is_not_the_sum_of_the_children_evaluated_alone(env):
    promo = Candidate("product_discount", ("1001",), {"discount_pct": 15})
    vou = Candidate(
        "min_spend_voucher",
        ("1001",),
        {"value": 30_000, "min_spend": 85_000, "quantity": 100_000, "days": 1},
    )
    alone = [evaluate_mega(env, [c], WINDOW, None)["certain"] for c in (promo, vou)]
    both = evaluate_mega(env, [promo, vou], WINDOW, None)["certain"]
    assert both["total_discount"] < alone[0]["total_discount"] + alone[1]["total_discount"]
    # (the voucher's minimum spend is reached less often once the promo price lowers subtotals)


async def test_one_price_lever_per_order_line_by_precedence():
    from juli_backend.services.shopee_profit.order_profit import OrderLine

    base = dict(
        order_id="o",
        sku="S",
        product_id="p",
        order_date=AS_OF,
        qty=2,
        original_price=D(100),
        deal_price=D(100),
    )
    assert precedence_lever(OrderLine(**base)) == "khong_uu_dai"
    assert precedence_lever(OrderLine(**{**base, "shop_voucher_share": D(5)})) == "voucher"
    assert (
        precedence_lever(OrderLine(**{**base, "deal_price": D(90), "shop_voucher_share": D(5)}))
        == "khuyen_mai"
    )
    assert (
        precedence_lever(OrderLine(**{**base, "deal_price": D(90), "bundle_discount": D(3)}))
        == "combo"
    )


async def test_the_floor_is_checked_per_sku_across_the_whole_stack(env):
    deep = [
        Candidate("product_discount", ("1001",), {"discount_pct": 40}),
        Candidate(
            "min_spend_voucher",
            ("1001",),
            {"value": 20_000, "min_spend": 10_000, "quantity": 100_000, "days": 1},
        ),
    ]
    res = evaluate_mega(env, deep, WINDOW, None)
    assert res["breaches"] and all(b["stacked"] for b in res["breaches"])
    assert res["breaches"][0]["sku"] == "G1"
    row = next(r for r in res["certain"]["skus"] if r["sku"] == "G1")
    assert row["below_floor"] and row["worst_unit_net_revenue"] < row["floor"]
    # each child alone stays above the floor; only the stack breaks it
    for c in deep:
        alone = evaluate_mega(env, [c], WINDOW, None)
        assert alone["breaches"] == [] or c.kind == "product_discount"
    mild = evaluate_mega(
        env, [Candidate("product_discount", ("1001",), {"discount_pct": 12})], WINDOW, None
    )
    assert mild["breaches"] == []


async def test_total_spend_per_day_is_checked_against_one_cap(env):
    ok = build_mega_card(env, _children(), WINDOW, now=NOW, budget_cap_per_day=D(1_000_000))
    tight = build_mega_card(env, _children(), WINDOW, now=NOW, budget_cap_per_day=D(1_000))
    assert ok["spend"]["over_cap"] is False and tight["spend"]["over_cap"] is True
    assert (
        tight["certain"]["spend"]["over_budget"] is True
        and tight["certain"]["spend"]["cap_per_day"] == 1000
    )
    assert tight["rank_inputs"]["spend_after"] == tight["certain"]["spend"]["mega_chi_per_day"]
    assert ok["spend"]["shop_chi_per_day_after"] > ok["spend"]["shop_chi_per_day_now"]
    # the ads child's budget increase is inside the total
    assert (
        ok["certain"]["spend"]["mega_chi_per_day"] > ok["certain"]["spend"]["baseline_chi_per_day"]
    )


async def test_the_bundle_gets_one_lift_not_the_sum_of_its_children(env):
    card = build_mega_card(env, _children(), WINDOW, now=NOW, budget_cap_per_day=D(500_000))
    lift = card["predicted"]["lift"]
    assert lift["metric"] == "orders" and lift["source"] == "prior" and lift["factor"] == 1.0
    assert lift["sim"]["applied"] is False
    kids = [evaluate(env, c) for c in _children()[:3]]
    assert card["certain"]["no_double_counting"]
    assert len(kids) == 3  # evaluated for their own pages, never credited separately


async def test_children_come_back_from_the_card_for_the_what_if(env):
    card = build_mega_card(
        env,
        _children(),
        WINDOW,
        now=NOW,
        budget_cap_per_day=D(500_000),
        child_ids=["a", "b", "c", "d"],
    )
    kids = children_from_card(card)
    assert [k.kind for k in kids] == [c.kind for c in _children()]
    assert kids[0].inputs == {"discount_pct": 15} and kids[3].campaign_key == "cgroup1"
    assert window_from_card(card) == WINDOW


async def test_select_children_takes_the_best_per_family_and_one_price_lever_per_product():
    def c(family, kind, item, n):
        return {"family": family, "change_kind": kind, "scope": {"product_ids": [item]}, "n": n}

    pool = [
        c("promotion", "product_discount", "1", 1),
        c("sale", "flash_sale", "1", 2),
        c("promotion", "price", "2", 3),
        c("voucher", "min_spend_voucher", "1", 4),
        c("promotion", "product_discount", "3", 5),
        c("mega_sale", "mega_sale", "1", 6),
    ]
    out = select_children(pool, per_family=2)
    assert [x["n"] for x in out] == [
        1,
        3,
        4,
    ]  # flash sale on item 1: a second price lever; n5: family quota; no mega


async def test_the_schedule_runs_day_by_day():
    kids = _children()
    sch = schedule_for(
        MegaWindow(datetime(2026, 11, 10, 20, 0), datetime(2026, 11, 13, 0, 0)),
        kids,
        ["a", "b", "c", "d"],
    )
    assert [d["date"] for d in sch] == ["2026-11-10", "2026-11-11", "2026-11-12"]
    assert [len(d["events"]) for d in sch] == [4, 0, 4]
    assert sch[0]["events"][0]["at"] == "20:00" and sch[2]["events"][-1]["at"] == "00:00"


async def test_a_mega_sale_without_orders_or_children_is_not_built(env):
    assert build_mega_card(env, [], WINDOW, now=NOW) is None
    ghost = [Candidate("product_discount", ("nope",), {"discount_pct": 10})]
    assert build_mega_card(env, ghost, WINDOW, now=NOW) is None


async def test_fit_drops_the_lowest_ranked_children_until_floors_and_cap_hold(env):
    kids = [
        Candidate(
            "min_spend_voucher",
            ("1001",),
            {"value": 20_000, "min_spend": 10_000, "quantity": 100_000, "days": 1},
        ),
        Candidate("product_discount", ("1002",), {"discount_pct": 15}),
        Candidate("product_discount", ("1001",), {"discount_pct": 40}),
        Candidate("ads_budget", (), {"daily_budget": 4_000_000}, campaign_key="cgroup1"),
    ]
    assert evaluate_mega(env, kids, WINDOW, D(200_000))["breaches"]
    kept, removed = fit_children(env, kids, WINDOW, D(200_000))
    assert evaluate_mega(env, kept, WINDOW, D(200_000))["breaches"] == []
    assert not evaluate_mega(env, kept, WINDOW, D(200_000))["cap"]["over_budget"]
    assert removed and {r["reason"] for r in removed} <= {"stacked_floor", "over_budget"}
    assert kept == [k for k in kids if k in kept]  # the rank order of the survivors is kept
    assert kept == [kids[0]]  # N1 breaks under voucher + its own discount: the discount goes
    # a stack that already fits loses nothing
    ok = [kids[1]]
    assert fit_children(env, ok, WINDOW, None) == (ok, [])
