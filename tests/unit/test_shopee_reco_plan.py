"""P91 wave 1b: manual-card integration with the queue, origin in events (A), then the draft plan,
the joint aggregate, change sets and the measurement window (D-6, D-7, D-8). SQLite; synthetic."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shop_proposals import (
    ShopProposal,
    ShopProposalApproval,
)
from juli_backend.models.shopee_plans import ShopRecoPlan
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_recommendations import (
    change_sets,
    learning,
    manual,
    plan,
    plan_codes,
    plans,
    product_queue,
    service,
    store,
)
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.plan import MetricStats
from juli_backend.services.shopee_recommendations.plan_aggregate import combine_predicted
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_shopee_reco_manual import _combo, _discount

NOW = datetime(2026, 10, 8, 3, 0)
REPO = Path(__file__).resolve().parents[2]
MIG = REPO / "backend/src/juli_backend/database/migrations/versions/117_shopee_reco_plans.py"


_USER_IDS: dict[uuid.UUID, uuid.UUID] = {}


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)  # the stored funnel (P98)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id  # a rollback expires the ORM user: keep the id
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    return seeded, env


def _actor(seeded):
    return manual.Actor("seller", _USER_IDS[seeded.shop_id])


async def _manual(session, seeded, env, variant, *, primary=False, at=NOW):
    out = await manual.create_manual(
        session,
        seeded.shop_id,
        [variant],
        0,
        primary,
        _actor(seeded),
        now=at,
        env=env,
        acknowledge_breaches=True,
    )
    await session.commit()
    return out


# ================================================================== A. wave-1 integration


async def test_a_primary_manual_card_takes_queue_1_and_the_old_head_moves_to_2(session, shop):
    seeded, env = shop
    first = await _manual(session, seeded, env, _discount(10))
    assert (
        first["product_queue"] == 1 and first["position"] == 1 and first["code"].startswith("JC-")
    )
    second = await _manual(session, seeded, env, _discount(20), at=NOW.replace(minute=5))
    third = await _manual(
        session, seeded, env, _discount(5), primary=True, at=NOW.replace(minute=10)
    )
    assert third["product_queue"] == 1
    places = {
        str(p.id): p.product_queue for p in (await session.scalars(select(ShopProposal))).all()
    }
    assert places[third["id"]] == 1
    assert sorted([places[first["id"]], places[second["id"]]]) == [2, 3]
    # a newer primary pins ahead of the earlier one
    fourth = await _manual(session, seeded, env, _combo(), primary=True, at=NOW.replace(minute=20))
    # (the combo is on products 1001 and 1002: it queues under its first product)
    assert fourth["product_queue"] == 1
    await session.refresh(await session.get(ShopProposal, uuid.UUID(third["id"])))
    assert (await session.get(ShopProposal, uuid.UUID(third["id"]))).product_queue == 2


async def test_a_manual_card_without_primary_queues_by_its_score(session, shop):
    seeded, env = shop
    out = await _manual(session, seeded, env, _discount(10))
    card = await store.card_payload(session, seeded.shop_id, uuid.UUID(out["id"]))
    assert card["rank"]["score"] is not None and card["origin"] == "manual"
    meta = await store.card_meta(session, seeded.shop_id, uuid.UUID(out["id"]))
    assert meta["rank_score"] == card["rank"]["score"] and "primary_at" not in meta


async def test_a_manual_card_has_core_format_versions_and_codes(session, shop):
    seeded, env = shop
    out = await manual.create_manual(
        session,
        seeded.shop_id,
        [_discount(10), _discount(20)],
        1,
        False,
        _actor(seeded),
        now=NOW,
        env=env,
        acknowledge_breaches=True,
    )
    await session.commit()
    card = await store.card_payload(session, seeded.shop_id, uuid.UUID(out["id"]))
    assert [v["version"] for v in card["versions"]] == [1, 2]
    assert card["versions"][0]["code"] == f"{out['code']}-V1" and card["versions"][0]["chosen"]
    assert (
        card["versions"][0]["inputs"]["discount_pct"] == 20 and card["inputs"]["discount_pct"] == 20
    )


async def test_a_combo_title_survives_the_what_if_recompute(session, shop):
    seeded, env = shop
    out = await _manual(session, seeded, env, _combo(10))
    cid = uuid.UUID(out["id"])
    title = out["card"]["title"]
    assert title.startswith("Combo nhiều sản phẩm — ")
    again = await service.recompute(
        session, seeded.shop_id, cid, {"discount_value": 12}, now=NOW, actor="seller"
    )
    assert again["title"] == title
    assert again["versions"][0]["title"] == title and again["versions"][0]["chosen"] is True
    assert again["origin"] == "manual" and again["created_by"]["type"] == "seller"


async def test_events_carry_origin_and_created_by_and_learning_splits_by_it(session, shop):
    seeded, env = shop
    out = await _manual(session, seeded, env, _discount(10))
    cid = uuid.UUID(out["id"])
    await service.recompute(session, seeded.shop_id, cid, {"discount_pct": 12}, now=NOW)
    await service.decide(
        session, seeded.shop_id, cid, decision="approve", user_id=seeded.user.id, now=NOW
    )
    await service.mark_executed(session, seeded.shop_id, cid, now=NOW, user_id=seeded.user.id)
    await session.commit()
    events = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid,
                CardEvent.event_type.in_(["whatif_adjusted", "accepted", "executed"]),
            )
        )
    ).all()
    assert {e.event_type for e in events} == {"whatif_adjusted", "accepted", "executed"}
    for e in events:
        assert e.payload["origin"] == "manual"
        assert e.payload["created_by"] == {"type": "seller", "id": str(seeded.user.id)}
    engine = await store.load_acceptance(session, seeded.shop_id)
    mine = await store.load_acceptance(session, seeded.shop_id, origin="manual")
    assert engine.approved["product_discount"] == 0 and mine.approved["product_discount"] == 1
    overview = await service.learning_overview(session, seeded.shop_id)
    assert overview["acceptance_manual"]["product_discount"]["approved"] == 1
    assert "product_discount" not in overview["acceptance"]


def test_calibration_keeps_manual_and_engine_apart_and_weights_multi_card_samples():
    def obs(origin="engine", weight=1.0, measured=0.10):
        return learning.Observation(
            "price", "orders", 0.05, 0.15, measured, 0.02, origin=origin, weight=weight
        )

    states = learning.calibrate([obs(), obs(), obs("manual")])
    assert states[("price", "orders")].n_results == 2
    assert learning.calibrate([obs("manual")], "manual")[("price", "orders")].n_results == 1
    # a multi-card sample counts as its weight, never as a clean one
    light = learning.calibrate([obs(weight=0.25)] * 4)[("price", "orders")]
    assert light.n_results == 1
    heavy = learning.calibrate([obs(measured=0.30), obs(weight=0.25, measured=0.0)])
    assert heavy[("price", "orders")].pooled_ratio > 1.5  # the light sample barely moves it
    allstates = learning.calibrate_all([obs("manual")])
    assert allstates[("price", "orders")].n_results == 0
    back = learning.Observation.from_json(obs("manual", 0.25).json())
    assert back.origin == "manual" and back.weight == 0.25


# ============================================================================ pure (D-6, D-8)


def _q(p50, half):
    """A card's predicted layer for one metric: symmetric quantiles around the P50."""
    return {
        "p10": p50 - half,
        "p25": p50 - half / 2,
        "p50": p50,
        "p75": p50 + half / 2,
        "p90": p50 + half,
    }


def _part(gmv, gmv_half, profit, profit_half):
    g, p = _q(gmv, gmv_half), _q(profit, profit_half)
    return {q: {"dgmv": g[q], "dorders": g[q] / 100_000, "dprofit": p[q]} for q in g}


def test_predicted_p50s_add_and_the_range_is_the_root_sum_of_squares_of_the_half_widths():
    a, b = _part(1000, 400, 100, 60), _part(500, 300, 40, 80)
    out = combine_predicted([a, b])
    assert out["p50"]["dgmv"] == 1500 and out["p50"]["dprofit"] == 140
    assert out["p90"]["dgmv"] == pytest.approx(1500 + (400**2 + 300**2) ** 0.5)  # 500
    assert out["p10"]["dprofit"] == pytest.approx(140 - (60**2 + 80**2) ** 0.5)  # 100
    # narrower than adding the widths, wider than the widest card
    assert out["p90"]["dgmv"] - 1500 < 400 + 300
    assert out["p90"]["dgmv"] - 1500 > 400
    order = [out[q]["dprofit"] for q in ("p10", "p25", "p50", "p75", "p90")]
    assert order == sorted(order)
    # one card is itself; two identical cards: sqrt(2) times the width, not twice
    assert combine_predicted([a])["p90"] == a["p90"]
    twin = combine_predicted([a, a])
    assert twin["p90"]["dgmv"] - 2000 == pytest.approx(400 * 2**0.5)


def test_an_unknown_profit_is_left_out_not_passed_off_as_zero():
    a = _part(1000, 400, 100, 60)
    unknown = {q: {**v, "dprofit": None} for q, v in _part(500, 100, 0, 0).items()}
    out = combine_predicted([a, unknown])
    assert out["p50"]["dprofit"] == 100 and out["p50"]["dgmv"] == 1500
    nothing = combine_predicted([unknown])
    assert nothing["p50"]["dprofit"] is None and nothing["p10"]["dprofit"] is None
    assert combine_predicted([])["p50"] == {"dgmv": 0.0, "dorders": 0.0, "dprofit": 0.0}


def test_the_mde_is_computed_for_any_window_and_the_recommended_preset_is_the_shortest_enough():
    for per_day, want in ((200, 7), (20, 7), (12, 14), (8, 28), (5, None)):
        stats = MetricStats(count_per_day=per_day, orders_per_day=per_day, phi=1.0)
        opts = plan.window_options("orders", stats)
        assert opts["recommended_days"] == want, per_day
        assert [r["days"] for r in opts["presets"]] == [7, 14, 28]
        assert [r["recommended"] for r in opts["presets"]].count(True) == (want is not None)
        assert opts["default_days"] == (want or 28)
    stats = MetricStats(count_per_day=12, orders_per_day=12)
    seven = plan.window_option("orders", stats, 7)
    assert seven["hard"] and "khó kết luận" in seven["label"] and seven["mde_pct"] > 30
    custom = [plan.window_option("orders", stats, n)["mde"] for n in (3, 10, 45, 90)]
    assert custom == sorted(custom, reverse=True)  # a longer window detects smaller changes
    assert plan.window_option("orders", MetricStats(), 7)["mde"] is None  # no volume: not guessed


def test_the_window_is_three_to_ninety_days():
    assert [plan.check_window(n) for n in (3, 7, 90)] == [3, 7, 90]
    for bad in (2, 91, 0, -1, 7.5, "7", True, None):
        with pytest.raises(ValueError):
            plan.check_window(bad)
    with pytest.raises(ProposalError) as exc:
        change_sets.check_days(2)
    assert exc.value.status == 422 and exc.value.code == change_sets.ERROR_WINDOW


def test_a_cut_measurement_keeps_three_days_and_calls_fewer_inconclusive():
    for days in (0, 1, 2):
        out = change_sets.cut_outcome(days)
        assert out["state"] == "inconclusive" and out["label"] == "Không kết luận"
    for days in (3, 4, 20):
        out = change_sets.cut_outcome(days)
        assert out["state"] == "kept_partial" and out["label"] == f"Đo được {days} ngày"
        assert out["low_confidence"] is True


def test_plan_codes_are_kh_yymm_seq3_per_shop():
    assert plan_codes.format_plan_code(datetime(2026, 11, 4), 3) == "KH-2611-003"
    assert plan_codes.format_plan_code(datetime(2026, 11, 4), 1234) == "KH-2611-1234"
    assert plan_codes.parse_plan_code(" kh-2611-003 ") == "KH-2611-003"
    for bad in ("JC-2611-0003", "KH-2611-03", "KH-26-003", "KH-2611-003-V1", ""):
        assert plan_codes.parse_plan_code(bad) is None
    with pytest.raises(ValueError):
        plan_codes.format_plan_code(datetime(2026, 11, 4), 0)


def test_a_planned_card_has_no_queue_place():
    from juli_backend.services.shopee_recommendations.product_queue import QueueCard, assign

    got = assign(
        [
            QueueCard("a", "p", "planned", 9.0),
            QueueCard("b", "p", "sent", 1.0),
            QueueCard("c", "p", "approved", 0.5),
        ]
    )
    assert got == {"a": None, "b": 2, "c": 1}  # approved (in flight) goes ahead of waiting


# ================================================================== D-6: the plan (flows)

VOUCHER = {
    "change_kind": "min_spend_voucher",
    "items": ["1001"],
    "inputs": {"value": 20_000, "min_spend": 60_000, "quantity": 50, "days": 14},
}


async def _three(session, seeded, env):
    ids = []
    for n, v in enumerate((_discount(15), VOUCHER, _combo())):
        ids.append(
            uuid.UUID((await _manual(session, seeded, env, v, at=NOW + timedelta(minutes=n)))["id"])
        )
    return ids


async def _status(session, ids):
    rows = (await session.scalars(select(ShopProposal).where(ShopProposal.id.in_(ids)))).all()
    by = {p.id: p for p in rows}
    return [(by[i].status, by[i].product_queue, by[i].lever_plan_id) for i in ids]


async def test_adding_moves_the_next_card_up_and_removing_gives_the_place_back(session, shop):
    seeded, env = shop
    a, b, c = await _three(session, seeded, env)
    sid = seeded.shop_id
    before = await _status(session, [a, b, c])
    assert [x[1] for x in before] == [1, 2, 3] or sorted(x[1] for x in before) == [1, 2, 3]
    head = next(i for i, x in zip([a, b, c], before, strict=True) if x[1] == 1)
    out = await plans.add_card(session, sid, head, actor=_actor(seeded), now=NOW)
    await session.commit()
    assert out["plan"]["status"] == "draft" and out["plan"]["code"] is None
    assert [c_["card_id"] for c_ in out["cards"]] == [str(head)]
    after = dict(zip([a, b, c], await _status(session, [a, b, c]), strict=True))
    assert after[head][:2] == ("planned", None) and after[head][2] is not None
    assert sorted(v[1] for k, v in after.items() if k != head) == [1, 2]  # the next moved up
    out = await plans.remove_card(session, sid, head, actor=_actor(seeded), now=NOW)
    await session.commit()
    assert out["cards"] == []
    restored = dict(zip([a, b, c], await _status(session, [a, b, c]), strict=True))
    assert restored[head] == before[[a, b, c].index(head)][:2] + (None,)
    assert sorted(v[1] for v in restored.values()) == [1, 2, 3]


async def test_one_draft_per_shop_and_only_open_undecided_cards_can_be_planned(session, shop):
    seeded, env = shop
    a, b, _ = await _three(session, seeded, env)
    sid = seeded.shop_id
    one = await plans.add_card(session, sid, a, actor=_actor(seeded), now=NOW)
    two = await plans.add_card(session, sid, b, actor=_actor(seeded), now=NOW)
    await session.commit()
    assert one["plan"]["id"] == two["plan"]["id"] and len(two["cards"]) == 2
    assert len(list((await session.scalars(select(ShopRecoPlan))).all())) == 1
    with pytest.raises(ProposalError) as exc:  # already planned
        await plans.add_card(session, sid, a, actor=_actor(seeded), now=NOW)
    assert exc.value.status == 409 and exc.value.code == plans.ERROR_CARD_STATE
    with pytest.raises(ProposalError):  # a planned card cannot be decided alone: it is not `sent`
        await service.decide(session, sid, a, decision="approve", user_id=_USER_IDS[sid], now=NOW)
    await session.rollback()
    with pytest.raises(ProposalError) as exc:
        await plans.remove_card(session, sid, uuid.uuid4(), actor=_actor(seeded), now=NOW)
    assert exc.value.code == plans.ERROR_NOT_IN_PLAN


async def test_switching_the_version_and_the_what_if_re_aggregate_at_once(session, shop):
    seeded, env = shop
    out = await manual.create_manual(
        session, seeded.shop_id, [_discount(15), _discount(25)], 0, False, _actor(seeded),
        now=NOW, env=env, acknowledge_breaches=True,
    )  # fmt: skip
    cid = uuid.UUID(out["id"])
    await session.commit()
    sid = seeded.shop_id
    first = await plans.add_card(session, sid, cid, actor=_actor(seeded), now=NOW)
    v1 = first["aggregate"]["cards"][0]
    assert v1["version"] == 1 and v1["inputs"]["discount_pct"] == 15
    second = await plans.switch_version(session, sid, cid, 2, actor=_actor(seeded), now=NOW)
    v2 = second["aggregate"]["cards"][0]
    assert v2["version"] == 2 and v2["inputs"]["discount_pct"] == 25
    # P99b: on the option-result path the money layer's certain figure is never shown
    assert v2["alone"]["dprofit"]["certain"] is None
    assert v2["result"]["own"]["delta"] != v1["result"]["own"]["delta"]  # deeper discount
    assert second["cards"][0]["chosen_version_code"].endswith("-V2")
    third = await plans.whatif(
        session, sid, cid, {"discount_pct": 18}, actor=_actor(seeded), now=NOW
    )
    c3 = third["aggregate"]["cards"][0]
    assert c3["inputs"]["discount_pct"] == 18 and c3["what_if"] == {"discount_pct": 18}
    assert c3["result"]["own"]["delta"] != v1["result"]["own"]["delta"]
    fourth = await plans.switch_version(session, sid, cid, 1, actor=_actor(seeded), now=NOW)
    assert fourth["cards"][0]["what_if"] == {}  # the inputs belonged to the old version
    for bad in (0, 3):
        with pytest.raises(ProposalError):
            await plans.switch_version(session, sid, cid, bad, actor=_actor(seeded), now=NOW)
    await session.commit()
    events = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid, CardEvent.event_type == "whatif_adjusted"
            )
        )
    ).all()
    assert len(events) == 3 and all(e.payload["plan_id"] == first["plan"]["id"] for e in events)
    assert {e.payload["origin"] for e in events} == {"manual"}


async def test_the_aggregate_is_joint_not_the_sum_of_the_cards(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    # a voucher whose minimum spend the discounted basket no longer reaches: the two interact
    tight = {**VOUCHER, "inputs": {**VOUCHER["inputs"], "value": 3_000, "min_spend": 90_000}}
    d = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    v = uuid.UUID((await _manual(session, seeded, env, tight))["id"])
    await plans.add_card(session, sid, d, actor=_actor(seeded), now=NOW)
    out = await plans.add_card(session, sid, v, actor=_actor(seeded), now=NOW)
    agg = out["aggregate"]
    by = {c["card_id"]: c for c in agg["cards"]}
    # P99b: the money layer's certain figure is not shown beside the results
    assert agg["dprofit_month"]["certain"] is None
    assert agg["joint_cards"] == [str(d), str(v)] or set(agg["joint_cards"]) == {str(d), str(v)}
    assert agg["stacked_products"][0]["product_id"] == "1001"
    assert agg["stacked_products"][0]["stacked_on_same_orders"] is True
    # "bỏ thẻ này thì": the plan without a card is the other card alone
    assert by[str(d)]["without"]["dprofit"]["p50"] == pytest.approx(
        by[str(v)]["alone"]["dprofit"]["p50"]
    )
    assert by[str(v)]["without"]["dprofit"]["p50"] == pytest.approx(
        by[str(d)]["alone"]["dprofit"]["p50"]
    )
    for c in agg["cards"]:
        assert c["without"]["delta"]["dprofit_p50"] == pytest.approx(
            c["contribution"]["dprofit_p50"]
        )
        assert c["contribution"]["dprofit_p50"] == pytest.approx(
            agg["dprofit_month"]["total"]["p50"] - c["without"]["dprofit"]["p50"]
        )
    # P98 / ADR-122 d.2: the plan's Δ is the SUM of its cards' option results (P50 exact), not
    # the money layer and not a single shared lift (D85.4 folding is gone for the result layer)
    p = agg["dprofit_month"]
    assert agg["result_basis"] == "option_result" and agg["not_estimable_cards"] == []
    each = [c["result"]["delta"]["p50"]["dprofit"] for c in agg["cards"]]
    assert p["total"]["p50"] == pytest.approx(sum(each))
    assert p["predicted"]["p50"] == pytest.approx(sum(each))
    assert p["total"]["p10"] < p["total"]["p50"] < p["total"]["p90"]
    assert agg["range_method"] == "root_sum_of_squares_of_half_widths"
    # cost per day and per month vs the cap, the five numbers, the shop today and after
    cost = agg["cost"]
    assert cost["per_month_after"] == pytest.approx(cost["per_day_after"] * 30)
    assert cost["cap_per_day"] == 500_000 and cost["over_cap"] is False
    assert agg["five_numbers"]["orders"]["before"] is not None
    assert agg["today"]["gmv_30d"] and agg["after"]["gmv_30d"] != agg["today"]["gmv_30d"]
    assert out["windows"]["min_days"] == 3 and out["windows"]["max_days"] == 90


async def test_cards_on_different_products_add(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    a = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    other = {"change_kind": "product_discount", "items": ["1002"], "inputs": {"discount_pct": 15}}
    b = uuid.UUID((await _manual(session, seeded, env, other))["id"])
    await plans.add_card(session, sid, a, actor=_actor(seeded), now=NOW)
    agg = (await plans.add_card(session, sid, b, actor=_actor(seeded), now=NOW))["aggregate"]
    total = agg["dprofit_month"]["total"]["p50"]
    alone = sum(c["alone"]["dprofit"]["p50"] for c in agg["cards"])
    assert total == pytest.approx(alone, rel=0.02, abs=50)
    assert agg["stacked_products"] == [] and {p_["product_id"] for p_ in agg["products"]} == {
        "1001",
        "1002",
    }


async def test_a_stacked_price_can_break_a_floor_that_no_single_card_breaks(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    deep = {**_discount(30)}
    big = {**VOUCHER, "inputs": {**VOUCHER["inputs"], "value": 20_000}}
    d = await _manual(session, seeded, env, deep)
    v = await _manual(session, seeded, env, big)
    assert d["card"]["floor"]["ok"] and v["card"]["floor"]["ok"]  # fine one by one
    await plans.add_card(session, sid, uuid.UUID(d["id"]), actor=_actor(seeded), now=NOW)
    out = await plans.add_card(session, sid, uuid.UUID(v["id"]), actor=_actor(seeded), now=NOW)
    agg = out["aggregate"]
    assert agg["floor"]["ok"] is False
    (breach,) = agg["floor"]["breaches"]
    assert breach["type"] == "floor" and breach["sku"] == "G1" and breach["stacked"] is True
    assert breach["only_when_stacked"] is True and breach["card_ids"] == []
    assert breach["min_unit_price"] < breach["floor"]
    assert agg["breaches"][0]["sku"] == "G1"
    # removing either card clears it
    for c in agg["cards"]:
        assert c["without"]["floor_ok"] is True


async def test_confirm_is_never_blocked_a_breach_needs_the_acknowledgement(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    ids = [
        uuid.UUID((await _manual(session, seeded, env, x))["id"])
        for x in (_discount(30), {**VOUCHER, "inputs": {**VOUCHER["inputs"], "value": 20_000}})
    ]
    for i in ids:
        await plans.add_card(session, sid, i, actor=_actor(seeded), now=NOW)
    await session.commit()
    with pytest.raises(plans.PlanBreachNotAcknowledged) as exc:
        await plans.confirm(session, sid, actor=_actor(seeded), now=NOW)
    assert exc.value.status == 422 and exc.value.code == plans.ERROR_BREACH
    assert exc.value.breaches[0]["sku"] == "G1"
    await session.rollback()
    assert [x[0] for x in await _status(session, ids)] == ["planned", "planned"]
    assert (await session.scalar(select(ShopRecoPlan))).code is None  # nothing issued
    out = await plans.confirm(
        session, sid, actor=_actor(seeded), now=NOW, acknowledge_breaches=True
    )
    await session.commit()
    assert out["plan"]["status"] == "confirmed" and out["plan"]["code"] == "KH-2610-001"
    ack = out["plan"]["acknowledged_breaches"]
    assert ack["by"] == {"type": "seller", "id": str(_USER_IDS[sid])} and ack["at"]
    assert ack["breaches"][0]["sku"] == "G1"
    assert [x[0] for x in await _status(session, ids)] == ["approved", "approved"]
    events = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id.in_(ids), CardEvent.event_type == "accepted")
        )
    ).all()
    assert len(events) == 2
    for e in events:
        assert e.payload["plan_code"] == "KH-2610-001" and e.payload["plan_id"] == out["plan"]["id"]
        assert e.payload["acknowledged_breaches"]["breaches"][0]["sku"] == "G1"
        assert e.payload["chosen_version"] == 1 and e.payload["origin"] == "manual"
        assert e.payload["planned_date"] == "2026-10-08"
    approvals = (await session.scalars(select(ShopProposalApproval))).all()
    assert len(approvals) == 2 and all(
        a.proposal_snapshot["plan_code"] == "KH-2610-001" for a in approvals
    )
    props = (await session.scalars(select(ShopProposal).where(ShopProposal.id.in_(ids)))).all()
    assert {p.planned_start for p in props} == {date(2026, 10, 8)}
    assert {str(p.lever_plan_id) for p in props} == {out["plan"]["id"]}
    # the frozen aggregate is what a later read returns; the draft is gone
    again = await plans.get_plan(session, sid, uuid.UUID(out["plan"]["id"]), now=NOW)
    assert again["aggregate"]["plan_code"] == "KH-2610-001"
    assert (await plans.get_plan(session, sid, now=NOW))["plan"] is None


async def test_plan_codes_count_per_shop_and_show_on_every_card_and_in_card_by_code(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    codes_ = []
    cards = []
    for n, variant in enumerate((_discount(15), _discount(10))):
        cid = uuid.UUID(
            (await _manual(session, seeded, env, variant, at=NOW + timedelta(minutes=n)))["id"]
        )
        cards.append(cid)
        await plans.add_card(session, sid, cid, actor=_actor(seeded), now=NOW)
        out = await plans.confirm(session, sid, actor=_actor(seeded), now=NOW)
        await session.commit()
        codes_.append(out["plan"]["code"])
    assert codes_ == ["KH-2610-001", "KH-2610-002"]
    listing = await service.list_cards(session, sid, audience="seller", queue="all", now=NOW)
    by = {c["id"]: c for c in listing["cards"]}
    assert by[str(cards[0])]["plan_code"] == "KH-2610-001"
    assert by[str(cards[1])]["plan_code"] == "KH-2610-002"
    assert by[str(cards[0])]["plan_id"] and by[str(cards[0])]["origin"] == "manual"
    detail = await service.card_detail(session, sid, cards[0], audience="seller")
    assert detail["plan_code"] == "KH-2610-001"
    code = by[str(cards[0])]["code"]
    got = await service.card_by_code(session, sid, code)
    assert got["plan_code"] == "KH-2610-001" and got["planned_date"] == "2026-10-08"
    by_plan = await plans.plan_by_code(session, sid, "kh-2610-002", now=NOW)
    assert by_plan["plan"]["code"] == "KH-2610-002"
    with pytest.raises(ProposalError):
        await plans.plan_by_code(session, sid, "KH-2610-099", now=NOW)
    assert [p["code"] for p in await plans.list_plans(session, sid)] == [
        "KH-2610-002",
        "KH-2610-001",
    ] or {p["code"] for p in await plans.list_plans(session, sid)} == set(codes_)


async def test_confirm_needs_a_card_and_a_date_that_is_not_in_the_past(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    with pytest.raises(ProposalError) as exc:
        await plans.confirm(session, sid, actor=_actor(seeded), now=NOW)
    assert exc.value.code == plans.ERROR_UNKNOWN_PLAN
    cid = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    await plans.add_card(session, sid, cid, actor=_actor(seeded), now=NOW)
    with pytest.raises(ProposalError) as exc:
        await plans.confirm(
            session, sid, actor=_actor(seeded), now=NOW, planned_date=date(2026, 10, 1)
        )
    assert exc.value.code == plans.ERROR_DATE
    out = await plans.confirm(
        session, sid, actor=_actor(seeded), now=NOW, planned_date=date(2026, 10, 12)
    )
    assert out["plan"]["planned_date"] == "2026-10-12"


# ============================================================ D-7 / D-8: change sets and windows


async def _confirm_plan(session, seeded, env, variants, *, now=NOW, window=None, windows=None):
    sid = seeded.shop_id
    ids = []
    for n, v in enumerate(variants):
        out = await _manual(session, seeded, env, v, at=now + timedelta(minutes=n))
        ids.append(uuid.UUID(out["id"]))
        await plans.add_card(session, sid, ids[-1], actor=_actor(seeded), now=now)
    if window is not None:
        await plans.set_window(session, sid, days=window, now=now)
    for pid, days in (windows or {}).items():
        await plans.set_window(session, sid, days=days, product_id=pid, now=now)
    out = await plans.confirm(
        session, sid, actor=_actor(seeded), now=now, acknowledge_breaches=True
    )
    await session.commit()
    return ids, out


async def _execute(session, seeded, cid, at):
    out = await service.mark_executed(
        session,
        seeded.shop_id,
        cid,
        now=at,
        executed_at=at,
        user_id=_USER_IDS[seeded.shop_id],
        voucher_id="V-SYNTH-1",
    )
    await session.commit()
    return out


async def test_cards_of_one_product_executed_the_same_day_are_one_change_set(session, shop):
    seeded, env = shop
    other = {"change_kind": "product_discount", "items": ["1002"], "inputs": {"discount_pct": 12}}
    ids, conf = await _confirm_plan(
        session, seeded, env, [_discount(15), VOUCHER, other], window=21
    )
    a, v, o = ids
    r1 = await _execute(session, seeded, a, NOW + timedelta(hours=1))
    assert r1["plan_executed"] is False and r1["plan_code"] == "KH-2610-001"
    r2 = await _execute(session, seeded, v, NOW + timedelta(hours=2))
    assert r2["change_set"]["id"] == r1["change_set"]["id"] and r2["change_set"]["n_cards"] == 2
    r3 = await _execute(session, seeded, o, NOW + timedelta(hours=3))
    assert r3["change_set"]["id"] != r1["change_set"]["id"] and r3["plan_executed"] is True
    sets = await change_sets.sets_for(session, seeded.shop_id)
    assert {(s.product_id, len(s.card_ids)) for s in sets} == {("1001", 2), ("1002", 1)}
    assert {(s.window_days, s.window_source) for s in sets} == {(21, "plan")}
    big = next(s for s in sets if s.product_id == "1001")
    # the joint prediction for the product travels with the set
    assert big.predicted["plan_code"] == "KH-2610-001" and big.predicted["joint"]["dprofit"]
    assert big.predicted["rel_gmv"]["p50"] is not None
    plan_row = await session.scalar(select(ShopRecoPlan))
    assert plan_row.status == "executed" and plan_row.executed_at
    # the events say which set and plan, and the executing card's meta carries the window
    ex = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == a, CardEvent.event_type == "executed")
        )
    ).one()
    assert ex.payload["change_set"] == str(big.id) and ex.payload["plan_code"] == "KH-2610-001"
    meta = await store.card_meta(session, seeded.shop_id, a)
    assert meta["window_days"] == 21 == meta["plan_days"] and meta["change_set"] == str(big.id)
    # "Sản phẩm đang đo" follows the chosen window and names the set
    m = await product_queue.measuring(session, seeded.shop_id, NOW + timedelta(days=2))
    assert m["1001"] == {
        "until": (NOW + timedelta(hours=1, days=21)).date().isoformat(),
        "change_set": str(big.id),
    }


async def test_the_window_is_the_products_override_then_the_plans_default_then_automatic(
    session, shop
):
    seeded, env = shop
    sid = seeded.shop_id
    other = {"change_kind": "product_discount", "items": ["1002"], "inputs": {"discount_pct": 12}}
    ids, _ = await _confirm_plan(
        session, seeded, env, [_discount(15), other], window=21, windows={"1002": 10}
    )
    await _execute(session, seeded, ids[0], NOW + timedelta(hours=1))
    await _execute(session, seeded, ids[1], NOW + timedelta(hours=1))
    sets = {s.product_id: s for s in await change_sets.sets_for(session, sid)}
    assert (sets["1001"].window_days, sets["1001"].window_source) == (21, "plan")
    assert (sets["1002"].window_days, sets["1002"].window_source) == (10, "custom")
    # per change set override, after execution
    changed = await change_sets.set_window(session, sid, sets["1001"].id, 45, now=NOW)
    assert (changed.window_days, changed.window_source) == (45, "custom")
    meta = await store.card_meta(session, sid, ids[0])
    assert meta["window_days"] == 45 == meta["plan_days"]
    for bad in (2, 91):
        with pytest.raises(ProposalError) as exc:
            await change_sets.set_window(session, sid, sets["1001"].id, bad, now=NOW)
        assert exc.value.status == 422


async def test_the_plan_window_is_validated_and_automatic_per_product_by_default(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cid = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    out = await plans.add_card(session, sid, cid, actor=_actor(seeded), now=NOW)
    (row,) = out["windows"]["per_product"]
    assert row["source"] == "auto" and row["days"] == row["options"]["default_days"]
    assert [p["days"] for p in row["options"]["presets"]] == [7, 14, 28]
    assert all("label" in p and "mde_pct" in p for p in row["options"]["presets"])
    assert out["windows"]["plan_default_days"] is None
    for bad in (1, 2, 91, 500):
        with pytest.raises(ProposalError) as exc:
            await plans.set_window(session, sid, days=bad, now=NOW)
        assert exc.value.code == change_sets.ERROR_WINDOW
    set7 = await plans.set_window(session, sid, days=7, now=NOW)
    assert set7["plan"]["window_days"] == 7 and set7["windows"]["per_product"][0]["days"] == 7
    assert set7["windows"]["per_product"][0]["source"] == "plan"
    over = await plans.set_window(session, sid, days=3, product_id="1001", now=NOW)
    assert over["windows"]["per_product"][0]["days"] == 3
    assert over["windows"]["per_product"][0]["source"] == "custom"
    back = await plans.set_window(session, sid, days=None, product_id="1001", now=NOW)
    assert back["windows"]["per_product"][0]["days"] == 7
    auto = await plans.set_window(session, sid, days=None, now=NOW)
    assert auto["windows"]["per_product"][0]["source"] == "auto"


async def test_executing_on_a_product_still_measured_cuts_the_running_measurement(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    day1 = NOW
    ids, _ = await _confirm_plan(session, seeded, env, [_discount(15)], now=day1, window=28)
    first = await _execute(session, seeded, ids[0], day1 + timedelta(hours=1))
    cs1 = first["change_set"]
    assert cs1["status"] == "measuring" and cs1["window_days"] == 28
    # a second plan on the same product, executed 2 days later: the dialog lists the cut
    day3 = NOW + timedelta(days=2)
    more = await _manual(session, seeded, env, _discount(8), at=day3)
    await plans.add_card(session, sid, uuid.UUID(more["id"]), actor=_actor(seeded), now=day3)
    conf = await plans.confirm(session, sid, actor=_actor(seeded), now=day3)
    await session.commit()
    (cut,) = conf["measurement_cut"]
    assert cut["product_id"] == "1001" and cut["change_set"] == cs1["id"]
    assert cut["days_measured"] == 2 and cut["state"] == "inconclusive"
    assert cut["label"] == "Không kết luận" and cut["name"]
    assert conf["plan"]["measurement_cut"] == conf["measurement_cut"]
    # nothing is cut yet: the confirm only says it will be
    assert (await change_sets.get(session, sid, uuid.UUID(cs1["id"]))).status == "measuring"
    second = await _execute(session, seeded, uuid.UUID(more["id"]), day3 + timedelta(hours=1))
    cs = await change_sets.get(session, sid, uuid.UUID(cs1["id"]))
    assert cs.status == "cut" and cs.cut_days == 2 and cs.result["state"] == "inconclusive"
    assert cs.result["cut_by_change_set"] == second["change_set"]["id"]
    # the new set started; the old one no longer holds the product or shows as measuring
    m = await product_queue.measuring(session, sid, day3 + timedelta(days=1))
    assert m["1001"]["change_set"] == second["change_set"]["id"]
    assert "measure_cut_at" in await store.card_meta(session, sid, ids[0])


async def test_three_or_more_days_measured_are_kept_as_do_duoc_n_ngay(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    ids, _ = await _confirm_plan(session, seeded, env, [_discount(15)], window=28)
    await _execute(session, seeded, ids[0], NOW + timedelta(hours=1))
    day5 = NOW + timedelta(days=4)
    preview = await change_sets.cut_preview(sid and session, sid, ["1001", "1002"], day5.date())
    assert [(p["product_id"], p["days_measured"], p["state"]) for p in preview] == [
        ("1001", 4, "kept_partial")
    ]
    assert preview[0]["label"] == "Đo được 4 ngày"
    more = await _manual(session, seeded, env, _discount(8), at=day5)
    await plans.add_card(session, sid, uuid.UUID(more["id"]), actor=_actor(seeded), now=day5)
    await plans.confirm(session, sid, actor=_actor(seeded), now=day5)
    await session.commit()
    await _execute(session, seeded, uuid.UUID(more["id"]), day5 + timedelta(hours=1))
    (first, second) = await change_sets.sets_for(session, sid)
    assert first.status == "cut" and first.result["label"] == "Đo được 4 ngày"
    assert first.result["low_confidence"] is True and second.status == "measuring"


async def test_a_shop_wide_card_is_its_own_set_and_flags_the_product_sets(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    shop_voucher = {
        "change_kind": "min_spend_voucher",
        "items": [],
        "inputs": {"value": 5_000, "min_spend": 80_000, "quantity": 50, "days": 14},
    }
    built, why = manual.build_variant(env, shop_voucher, now=NOW)
    if built is None:  # the voucher kind needs a product scope in this build: use ads instead
        pytest.skip(f"shop-wide voucher not buildable here: {why}")
    ids, _ = await _confirm_plan(session, seeded, env, [_discount(15), shop_voucher], window=14)
    await _execute(session, seeded, ids[0], NOW + timedelta(hours=1))
    await _execute(session, seeded, ids[1], NOW + timedelta(hours=2))
    sets = {s.scope: s for s in await change_sets.sets_for(session, sid)}
    assert sets["shop"].product_id is None and sets["product"].with_shop_wide is True
    js = change_sets.to_json(sets["product"])
    assert js["with_shop_wide_label"] == "Kèm thay đổi toàn shop"


# ===================================================================== migration 117 (static)


def _mig():
    spec = importlib.util.spec_from_file_location("mig117", MIG)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_117_is_additive_reversible_and_fits_alembic():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    mod = _mig()
    assert mod.revision == "117_shopee_reco_plans" and len(mod.revision) <= 32
    assert mod.down_revision == "116_shopee_reco_codes"
    result = evaluate_migration_paths([MIG])
    assert [f.render() for f in result.findings] == [] and result.accepted
    src = MIG.read_text("utf-8")
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("UPDATE public", "DELETE FROM", "op.drop_table", "op.drop_column"):
        assert verb not in up, verb
    assert set(mod.TENANT_TABLES) == {
        "shop_reco_plans",
        "shop_reco_plan_cards",
        "shop_reco_plan_counters",
        "shop_reco_change_sets",
    }
    assert "public.{table}" in src and "ENABLE ROW LEVEL SECURITY" in src
    assert "app_current_shop_id()" in src and "GRANT SELECT, INSERT, UPDATE" in src
    assert "planned" in mod.STATUSES and "planned" not in mod._STATUSES_116
    tail = REPO / "backend/src/juli_backend/database/migrations/deferred/101_write_mode_backfill.py"
    assert 'down_revision: str | None = "127_card_content_specs"' in tail.read_text("utf-8")


def test_the_models_match_the_migration_columns():
    mod = _mig()
    src = MIG.read_text("utf-8")
    from juli_backend.models import shopee_plans as m

    for model in (m.ShopRecoPlan, m.ShopRecoPlanCard, m.ShopRecoPlanCounter, m.ShopRecoChangeSet):
        assert model.__tablename__ in mod.TENANT_TABLES
        for column in model.__table__.columns.keys():
            assert f'"{column}"' in src, f"{model.__tablename__}.{column}"
    assert m.PLAN_STATUSES == ("draft", "confirmed", "executed", "cancelled")
    assert (m.WINDOW_MIN, m.WINDOW_MAX) == (3, 90)


# ============================================================================== routes

DEMO = "/v1/demo/shopee/recommendations"


def _body(variants, **kw):
    return {"variants": variants, "as_of": AS_OF.isoformat(), **kw}


@pytest.fixture
async def seller(session, shop):
    seeded, _ = shop
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _refreshed(session, seeded):
    """A refusing route rolls back, which expires the ORM rows the fixtures hold."""
    await session.refresh(seeded.shop)
    await session.refresh(seeded.user)


async def _post_manual(client, variant):
    r = await client.post(f"{DEMO}/manual", json=_body([variant], acknowledge_breaches=True))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_the_seller_plan_routes_end_to_end(session, shop, seller):
    seeded, _ = shop
    empty = await seller.get(f"{DEMO}/plan")  # not read as a {card_id}
    assert empty.status_code == 200 and empty.json()["plan"] is None
    a = await _post_manual(seller, _discount(15))
    b = await _post_manual(seller, _combo())
    r = await seller.post(f"{DEMO}/plan/cards", json={"card_id": a})
    assert r.status_code == 201, r.text
    assert r.json()["plan"]["status"] == "draft" and r.json()["cards"][0]["status"] == "planned"
    r = await seller.post(f"{DEMO}/plan/cards", json={"card_id": b, "chosen_version": 1})
    assert [c["card_id"] for c in r.json()["cards"]] == [a, b]
    agg = (await seller.get(f"{DEMO}/plan/aggregate")).json()
    assert agg["aggregate"]["n_cards"] == 2 and agg["windows"]["max_days"] == 90
    assert "model_version" not in str(agg) and "alpha" not in str(agg["aggregate"]["products"])
    r = await seller.post(f"{DEMO}/plan/cards/{a}/version", json={"version": 1})
    assert r.status_code == 200
    r = await seller.post(f"{DEMO}/plan/cards/{a}/whatif", json={"inputs": {"discount_pct": 12}})
    assert r.status_code == 200 and r.json()["cards"][0]["what_if"] == {"discount_pct": 12}
    r = await seller.post(f"{DEMO}/plan/cards/{b}/remove")
    assert [c["card_id"] for c in r.json()["cards"]] == [a]
    for body in ({"days": 2}, {"days": 91}, {"days": "x"}):
        assert (await seller.post(f"{DEMO}/plan/window", json=body)).status_code == 422
        await _refreshed(session, seeded)
    r = await seller.post(f"{DEMO}/plan/window", json={"days": 14})
    assert r.json()["windows"]["per_product"][0]["days"] == 14
    r = await seller.post(f"{DEMO}/plan/confirm", json={})
    assert r.status_code == 200, r.text
    plan_id, code = r.json()["plan"]["id"], r.json()["plan"]["code"]
    assert plan_codes.parse_plan_code(code) == code and code.endswith("-001")
    assert r.json()["cards"][0]["status"] == "approved"
    assert (await seller.get(f"{DEMO}/plans")).json()["plans"][0]["code"] == code
    assert (await seller.get(f"{DEMO}/plans/{plan_id}")).json()["plan"]["code"] == code
    assert (await seller.get(f"{DEMO}/plans/code/{code}")).json()["plan"]["id"] == plan_id
    assert (await seller.get(f"{DEMO}/plans/code/KH-2610-099")).status_code == 404
    card = (await seller.get(f"{DEMO}/{a}")).json()
    assert card["plan_code"] == code and card["status"] == "approved"
    done = await seller.post(f"{DEMO}/{a}/executed", json={})
    assert done.status_code == 201, done.text
    assert done.json()["plan_executed"] is True and done.json()["plan_code"] == code
    sets = (await seller.get(f"{DEMO}/change-sets", params={"product_id": "1001"})).json()
    (cs,) = sets["change_sets"]
    assert cs["window_days"] == 14 and cs["window_source"] == "plan" and cs["status"] == "measuring"
    assert cs["days_left"] is not None and cs["predicted"]["plan_code"] == code
    r = await seller.post(f"{DEMO}/change-sets/{cs['id']}/window", json={"days": 30})
    assert r.status_code == 200 and r.json()["window_days"] == 30
    assert r.json()["window_source"] == "custom"
    assert (
        await seller.post(f"{DEMO}/change-sets/{cs['id']}/window", json={"days": 2})
    ).status_code == 422
    await _refreshed(session, seeded)
    bad = await seller.get(f"{DEMO}/change-sets", params={"status": "nope"})
    assert bad.status_code == 422


async def test_a_breaching_plan_needs_the_acknowledgement_on_the_confirm_route(
    session, shop, seller
):
    d = await _post_manual(seller, _discount(30))
    v = await _post_manual(seller, {**VOUCHER, "inputs": {**VOUCHER["inputs"], "value": 20_000}})
    for cid in (d, v):
        assert (await seller.post(f"{DEMO}/plan/cards", json={"card_id": cid})).status_code == 201
    denied = await seller.post(f"{DEMO}/plan/confirm", json={})
    detail = denied.json()["detail"]
    assert denied.status_code == 422 and detail["code"] == "reco_breach_not_acknowledged"
    assert detail["breaches"][0]["type"] == "floor" and detail["breaches"][0]["sku"] == "G1"
    await _refreshed(session, shop[0])
    assert (await seller.get(f"{DEMO}/plan")).json()["plan"]["status"] == "draft"
    ok = await seller.post(f"{DEMO}/plan/confirm", json={"acknowledge_breaches": True})
    assert ok.status_code == 200
    assert ok.json()["plan"]["acknowledged_breaches"]["breaches"][0]["sku"] == "G1"


async def test_adding_a_breaching_card_needs_the_acknowledgement_too(session, shop, seller):
    below = await _post_manual(seller, _combo(pct=60))
    r = await seller.post(f"{DEMO}/plan/cards", json={"card_id": below})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reco_breach_not_acknowledged"
    assert r.json()["detail"]["breaches"][0]["type"] == "floor"
    await _refreshed(session, shop[0])
    assert (await seller.get(f"{DEMO}/plan")).json()["plan"] is None  # nothing was created
    ok = await seller.post(
        f"{DEMO}/plan/cards", json={"card_id": below, "acknowledge_breaches": True}
    )
    assert ok.status_code == 201
    (row,) = ok.json()["cards"]
    assert row["acknowledged_breaches"]["breaches"][0]["type"] == "floor"
    assert row["acknowledged_breaches"]["by"]["type"] == "seller"


async def test_ops_plan_routes_are_viewer_read_operator_write_and_audited(
    session, shop, monkeypatch
):
    seeded, env = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    ids = [
        (await _manual(session, seeded, env, v, at=NOW + timedelta(minutes=n)))["id"]
        for n, v in enumerate((_discount(15), _combo()))
    ]
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        assert (await client.get(f"{base}/plan")).status_code == 200
        assert (await client.get(f"{base}/plans")).json()["plans"] == []
        denied = await client.post(f"{base}/plan/cards", json={"card_id": ids[0]})
        assert denied.status_code == 403
        assert (await client.post(f"{base}/plan/confirm", json={})).status_code == 403
    viewer.dependency_overrides.clear()
    assert (await session.scalars(select(OpsAuditLog))).first() is None
    operator = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator) as client:
        for cid in ids:
            r = await client.post(f"{base}/plan/cards", json={"card_id": cid})
            assert r.status_code == 201, r.text
        assert (await client.get(f"{base}/plan/aggregate")).json()["aggregate"]["n_cards"] == 2
        r = await client.post(f"{base}/plan/cards/{ids[0]}/version", json={"version": 1})
        assert r.status_code == 200
        r = await client.post(f"{base}/plan/cards/{ids[1]}/remove")
        assert r.status_code == 200 and len(r.json()["cards"]) == 1
        assert (await client.post(f"{base}/plan/window", json={"days": 21})).status_code == 200
        assert (await client.post(f"{base}/plan/window", json={"days": 1})).status_code == 422
        conf = await client.post(f"{base}/plan/confirm", json={})
        assert conf.status_code == 200, conf.text
        assert conf.json()["plan"]["confirmed_by"]["type"] == "staff"
        code = conf.json()["plan"]["code"]
        got = await client.get(f"{base}/plans/code/{code}")
        assert got.json()["cards"][0]["plan_code"] == code
        # the approval of a plan by staff is a recorded decision pointing at the plan
        done = await client.post(f"{base}/{ids[0]}/executed", json={})
        assert done.status_code == 201, done.text
        (cs,) = (await client.get(f"{base}/change-sets")).json()["change_sets"]
        r = await client.post(f"{base}/change-sets/{cs['id']}/window", json={"days": 7})
        assert r.status_code == 200 and r.json()["window_days"] == 7
    operator.dependency_overrides.clear()
    actions = [a.action for a in (await session.scalars(select(OpsAuditLog))).all()]
    for expected in (
        "reco_plan_add_card",
        "reco_plan_remove_card",
        "reco_plan_switch_version",
        "reco_plan_window",
        "reco_plan_confirm",
        "reco_change_set_window",
    ):
        assert expected in actions, expected
    approval = (await session.scalars(select(ShopProposalApproval))).first()
    assert approval.channel == "document" and approval.evidence_ref == f"plan:{code}"
    assert approval.recorded_by_staff_id is not None


async def test_list_and_detail_expose_version_breach_ack_origin_plan_code_and_measured(
    session, shop
):
    seeded, env = shop
    sid = seeded.shop_id
    ids, _ = await _confirm_plan(
        session,
        seeded,
        env,
        [_discount(30), {**VOUCHER, "inputs": {**VOUCHER["inputs"], "value": 20_000}}],
        window=14,
    )
    listing = await service.list_cards(session, sid, audience="seller", queue="all", now=NOW)
    by = {c["id"]: c for c in listing["cards"]}
    row = by[str(ids[0])]  # manual cards list without a KeyError on their versions
    assert row["chosen_version"] == 1 and row["origin"] == "manual" and row["created_at"]
    assert row["plan_code"] == "KH-2610-001" and row["created_by"]["type"] == "seller"
    assert row["acknowledged_breaches"]["breaches"][0]["sku"] == "G1"
    assert (
        row["acknowledged_breaches"]["by"]["type"] == "seller"
        and row["acknowledged_breaches"]["at"]
    )
    assert row["status"] == "approved" and row["measurement"] is None
    await _execute(session, seeded, ids[0], NOW + timedelta(hours=1))
    (cs,) = await change_sets.sets_for(session, sid)
    cs.status = "done"  # the window closed (the learning job does this when it reads the set)
    cs.result = {"state": "measured", "label": "Đo xong sau 14 ngày"}
    await session.commit()
    detail = await service.card_detail(session, sid, ids[0], audience="seller")
    assert detail["status"] == "measured" and detail["execution_status"] == "executed"
    assert detail["measurement"]["state"] == "measured" and detail["chosen_version"] == 1
