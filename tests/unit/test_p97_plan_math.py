"""P97 D85.4: Kế hoạch totals do not depend on which options are present or their order; the base
is frozen per draft plan; remove then re-add restores the option; an exclusive field takes one
option. SQLite, synthetic."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_metrics import ShopeePlanBaseSnapshot
from juli_backend.models.shopee_plans import ShopRecoPlan
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import manual, plans
from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_analytics import CUR_END, _daily
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_reco_manual import _discount
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW, VOUCHER, _actor, _manual


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    return seeded, await load_env(session, seeded.shop_id, as_of=AS_OF)


def _totals(plan_out):
    agg = plan_out["aggregate"]
    return (
        round(agg["dgmv_month"]["total"]["p50"], 2),
        round(agg["dprofit_month"]["total"]["p50"], 2),
        round(agg["dorders_month"]["p50"], 2),
        round(agg["dprofit_month"]["certain"], 2),
    )


async def _add(session, seeded, cid):
    return await plans.add_card(session, seeded.shop_id, cid, actor=_actor(seeded), now=NOW)


async def _remove(session, seeded, cid):
    return await plans.remove_card(session, seeded.shop_id, cid, actor=_actor(seeded), now=NOW)


async def _card(session, seeded, env, variant, minute=0):
    out = await _manual(session, seeded, env, variant, at=NOW + timedelta(minutes=minute))
    return uuid.UUID(out["id"])


async def test_add_remove_add_returns_the_identical_total(session, shop):
    seeded, env = shop
    a = await _card(session, seeded, env, _discount(15))
    b = await _card(session, seeded, env, VOUCHER, 1)
    await _add(session, seeded, a)
    first = await _add(session, seeded, b)
    await _remove(session, seeded, b)
    again = await _add(session, seeded, b)
    assert _totals(first) == _totals(again)


async def test_re_adding_restores_the_removed_rows_version_and_what_if(session, shop):
    seeded, env = shop
    out = await manual.create_manual(
        session, seeded.shop_id, [_discount(10), _discount(20)], 0, False, _actor(seeded),
        now=NOW, env=env, acknowledge_breaches=True,
    )  # fmt: skip
    await session.commit()
    cid = uuid.UUID(out["id"])
    await _add(session, seeded, cid)
    await plans.switch_version(session, seeded.shop_id, cid, 2, actor=_actor(seeded), now=NOW)
    await plans.whatif(
        session, seeded.shop_id, cid, {"discount_pct": 12}, actor=_actor(seeded), now=NOW
    )
    before = (await plans.get_plan(session, seeded.shop_id, now=NOW))["cards"][0]
    await _remove(session, seeded, cid)
    after = (await plans.get_plan(session, seeded.shop_id, now=NOW))["cards"]
    assert after == []
    back = (await _add(session, seeded, cid))["cards"][0]  # the UI sends no version
    assert back["chosen_version"] == before["chosen_version"] == 2
    assert back["what_if"] == before["what_if"] == {"discount_pct": 12}
    assert back["evaluation"]["contribution"] == before["evaluation"]["contribution"]


async def test_the_total_does_not_depend_on_the_order_the_options_were_added(session, shop):
    seeded, env = shop
    a = await _card(session, seeded, env, _discount(15))
    b = await _card(session, seeded, env, VOUCHER, 1)
    await _add(session, seeded, a)
    ab = _totals(await _add(session, seeded, b))
    await _remove(session, seeded, a)
    await _remove(session, seeded, b)
    await _add(session, seeded, b)
    ba = _totals(await _add(session, seeded, a))
    assert ab == ba


async def test_a_shop_vouchers_reach_is_every_shop_order_whatever_else_is_in_the_plan(
    session, shop, monkeypatch
):
    from juli_backend.services.shopee_recommendations import mega

    seeded, env = shop
    v = mega.candidate_of_card(await _built(env, VOUCHER))  # a voucher on product 1001
    other = mega.candidate_of_card(await _built(env, {**_discount(15), "items": ["1002"]}))
    window = pa._window(env)
    alone = mega.evaluate_mega(env, [v], window, env.daily_cap, all_orders=True)
    with_other = mega.evaluate_mega(env, [v, other], window, env.daily_cap, all_orders=True)
    assert (
        alone["certain"]["voucher"]["qualifying_orders"]
        == with_other["certain"]["voucher"]["qualifying_orders"]
        > 0
    )
    # the plan asks for that reach whenever a voucher is in it
    seen = []
    real = mega.evaluate_mega

    def spy(*a, **kw):
        seen.append(kw.get("all_orders"))
        return real(*a, **kw)

    monkeypatch.setattr(pa, "evaluate_mega", spy)
    ev_v = pa.evaluate_entry(env, pa.Entry("v", "V", await _payload(env, VOUCHER)), now=NOW)
    pa.joint(env, [ev_v])
    assert seen == [True]


async def _built(env, variant):
    card, why = manual.build_variant(env, variant, now=NOW)
    assert card is not None, why
    return card


async def _payload(env, variant):
    card = await _built(env, variant)
    return {**card, "id": "v", "code": None}


async def test_a_second_option_on_an_exclusive_field_is_refused_in_vietnamese(session, shop):
    seeded, env = shop
    a = await _card(session, seeded, env, _discount(10))
    b = await _card(session, seeded, env, _discount(20), 1)
    await _add(session, seeded, a)
    with pytest.raises(ProposalError) as err:
        await _add(session, seeded, b)
    assert err.value.code == plans.ERROR_EXCLUSIVE and err.value.status == 422
    assert "chỉ giữ một giá trị" in err.value.detail and "giá bán" in err.value.detail
    await _remove(session, seeded, a)  # after the first leaves, the second fits
    assert (await _add(session, seeded, b))["cards"]


def _ev(card_id, product, dgmv):
    zero = {m: 0.0 for m in pa.METRICS}
    money = {"predicted": {q: {**zero, "dgmv": dgmv} for q in pa.QUANTILES}}
    return SimpleNamespace(
        entry=SimpleNamespace(card_id=card_id), product=product, money=money, is_line=True
    )


def test_one_joint_lift_per_product_never_a_sum_of_the_options_p50s():
    x1, x2, y1 = _ev("b", "1001", 100.0), _ev("a", "1001", 300.0), _ev("c", "1002", 50.0)
    keep, folded = pa.joint_lifts([x1, x2, y1])
    assert {e.entry.card_id for e in keep} == {"a", "c"} and folded == ["b"]
    # the same whatever the order they arrive in
    keep2, folded2 = pa.joint_lifts([y1, x2, x1])
    assert {e.entry.card_id for e in keep2} == {"a", "c"} and folded2 == folded
    # a tie breaks on the card id, not on position
    keep3, _ = pa.joint_lifts([_ev("z", "1", 5.0), _ev("m", "1", 5.0)])
    assert [e.entry.card_id for e in keep3] == ["m"]


async def test_the_base_is_frozen_until_the_person_refreshes_it(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    a = await _card(session, seeded, env, _discount(15))
    first = await _add(session, seeded, a)
    base = first["plan"]["base"]
    assert base["version"] == 1 and base["as_of"] == CUR_END.isoformat()
    assert base["newer_available"] is False
    # an ingest lands: two newer days of Shopee numbers
    for d in (1, 2):
        day = CUR_END + timedelta(days=d)
        session.add(
            _daily(sid, day, "total", "all", orders=5, gmv=900_000, dataset="shop_overview")
        )
        session.add(
            _daily(
                sid, day, "product_card", "all", orders=5, gmv=900_000, impressions=900, clicks=90
            )
        )
    await session.commit()
    again = await plans.get_plan(session, sid, now=NOW)
    assert _totals(again) == _totals(first)
    assert again["aggregate"]["today"] == first["aggregate"]["today"]
    assert again["plan"]["as_of"] == CUR_END.isoformat()
    assert again["plan"]["base"]["newer_available"] is True
    assert "Cập nhật số" in again["plan"]["base"]["note"]
    # editing the plan does not move the base either
    edited = await plans.whatif(
        session, sid, a, {"discount_pct": 12}, actor=_actor(seeded), now=NOW
    )
    assert edited["plan"]["as_of"] == CUR_END.isoformat()
    # only "Cập nhật số" does
    fresh = await plans.refresh_base(session, sid, actor=_actor(seeded), now=NOW)
    assert fresh["plan"]["as_of"] == (CUR_END + timedelta(days=2)).isoformat()
    assert (
        fresh["plan"]["base"]["version"] == 2 and fresh["plan"]["base"]["newer_available"] is False
    )
    snaps = (await session.scalars(select(ShopeePlanBaseSnapshot))).all()
    assert sorted(s.version for s in snaps) == [1, 2]
    plan = await session.scalar(select(ShopRecoPlan))
    assert plan.as_of == CUR_END + timedelta(days=2)


async def test_one_option_shows_the_same_p50_and_range_on_the_card_the_compare_and_the_plan(
    session, shop
):
    """D85.10: headline = P50 with P10-P90 beside it; cards stop showing P25."""
    from juli_backend.services.shopee_recommendations import manual as man
    from juli_backend.services.shopee_recommendations import store

    seeded, env = shop
    cid = await _card(session, seeded, env, _discount(15))
    card = await store.card_payload(session, seeded.shop_id, cid)
    total = card["predicted"]["money_per_month"]["total"]
    compare = man.compare(env, [_discount(15), _discount(25)], now=NOW)
    row = compare["variants"][0]["metrics"]
    assert row["dprofit_p50"] == total["p50"]["dprofit"]
    assert (row["dprofit_p10"], row["dprofit_p90"]) == (
        total["p10"]["dprofit"],
        total["p90"]["dprofit"],
    )
    assert "aov_p25" not in row and "margin_points_p25" not in row
    assert "aov_p50" in row and "margin_points_p50" in row
    assert compare["vs_today"][0]["delta"].keys() >= {"aov_p50", "margin_points_p50"}
    out = await _add(session, seeded, cid)
    contribution = out["aggregate"]["cards"][0]["contribution"]
    assert contribution["dprofit_p50"] == pytest.approx(total["p50"]["dprofit"], abs=1)
    assert out["aggregate"]["dprofit_month"]["total"]["p50"] == pytest.approx(
        total["p50"]["dprofit"], abs=1
    )
