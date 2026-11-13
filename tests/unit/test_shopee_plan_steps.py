"""P92 B-10: draft plans that build on each other -- per product the steps price -> giảm giá ->
voucher -> combo / mua kèm / quà tặng -> ads, each evaluated on top of the previous ones, with
margin and Δ profit after each step; reorder / remove re-evaluates. SQLite; synthetic."""

# ruff: noqa: F811
from __future__ import annotations

import uuid

import pytest

from juli_backend.services.shopee_recommendations import plan_steps as ps
from juli_backend.services.shopee_recommendations import plans
from tests.unit import test_shopee_reco_plan as _plan
from tests.unit.test_shopee_reco_manual import _combo, _discount

# The plan tests' fixtures, re-exported by name so pytest finds them in this module.
NOW, VOUCHER, _actor, _manual = _plan.NOW, _plan.VOUCHER, _plan._actor, _plan._manual
seller, shop = _plan.seller, _plan.shop

# ------------------------------------------------------------------ pure


def test_every_change_kind_is_one_step():
    assert ps.step_of("price") == "price" and ps.step_of("flash_sale") == "price"
    assert ps.step_of("product_discount") == "giam_gia"
    assert ps.step_of("min_spend_voucher") == "voucher"
    for kind in ("bundle_deal", "combo_multi", "add_on", "gift"):
        assert ps.step_of(kind) == "combo", kind
    assert ps.step_of("ads_budget") == "ads" and ps.step_of("title") == "other"


def test_a_new_card_takes_its_canonical_slot_among_the_products_cards():
    assert ps.slot_for([], "ads_budget") == 0
    assert ps.slot_for(["min_spend_voucher", "ads_budget"], "product_discount") == 0
    assert ps.slot_for(["product_discount", "ads_budget"], "min_spend_voucher") == 1
    assert ps.slot_for(["product_discount", "min_spend_voucher"], "gift") == 2
    assert ps.canonical(["ads_budget", "price", "min_spend_voucher"]) == [1, 2, 0]


# ------------------------------------------------------------------ the plan


async def _add(session, seeded, card_id):
    out = await plans.add_card(session, seeded.shop_id, card_id, actor=_actor(seeded), now=NOW)
    await session.commit()
    return out


def _steps(out, product="1001"):
    block = next(b for b in out["aggregate"]["products"] if b["product_id"] == product)
    return block["steps"]


async def test_steps_follow_the_canonical_order_and_add_up_to_the_joint_total(session, shop):
    seeded, env = shop
    # the voucher is added FIRST, the discount second: the discount still takes step 1
    v = uuid.UUID((await _manual(session, seeded, env, VOUCHER))["id"])
    d = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    await _add(session, seeded, v)
    out = await _add(session, seeded, d)
    steps = _steps(out)
    assert [i["step"] for i in steps["items"]] == ["giam_gia", "voucher"]
    assert steps["custom_order"] is False and [i["index"] for i in steps["items"]] == [1, 2]
    assert [c["card_id"] for c in out["cards"]] == [str(d), str(v)]
    first, last = steps["items"]
    agg = out["aggregate"]
    # the last step is the product's joint total, which is the plan's total for one product
    assert last["dprofit_total_p50"] == pytest.approx(agg["dprofit_month"]["total"]["p50"], abs=1)
    assert last["dprofit_total_certain"] == pytest.approx(agg["dprofit_month"]["certain"], abs=1)
    assert first["dprofit_step_p50"] + last["dprofit_step_p50"] == pytest.approx(
        last["dprofit_total_p50"], abs=1
    )
    # step 1 is the discount alone; step 2 is evaluated on top of it
    by = {c["card_id"]: c for c in agg["cards"]}
    assert first["dprofit_total_certain"] == pytest.approx(
        by[str(d)]["alone"]["dprofit"]["certain"], abs=1
    )
    # margin after each step is carried: step 2 starts from step 1's margin
    assert first["margin_pct_after"] is not None
    assert last["margin_pct_before"] == first["margin_pct_after"]
    assert steps["total"]["margin_pct_after"] == last["margin_pct_after"]
    assert steps["total"]["margin_pct_before"] == first["margin_pct_before"]
    assert "margin_basis" in steps


async def test_reordering_and_removing_re_evaluate_the_steps(session, shop):
    seeded, env = shop
    d = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    v = uuid.UUID((await _manual(session, seeded, env, VOUCHER))["id"])
    await _add(session, seeded, d)
    base = await _add(session, seeded, v)
    before = _steps(base)
    moved = await plans.move_card(session, seeded.shop_id, v, 1, actor=_actor(seeded), now=NOW)
    await session.commit()
    after = _steps(moved)
    assert [c["card_id"] for c in moved["cards"]] == [str(v), str(d)]
    assert [i["step"] for i in after["items"]] == ["voucher", "giam_gia"]
    assert after["custom_order"] is True
    # the same two cards stacked: the same total, a different split between the steps
    assert after["total"]["dprofit_p50"] == pytest.approx(before["total"]["dprofit_p50"], abs=1)
    assert after["items"][0]["dprofit_total_p50"] != pytest.approx(
        before["items"][0]["dprofit_total_p50"], abs=1
    )
    # moving back to the canonical place clears the custom flag; out-of-range positions clamp
    again = await plans.move_card(session, seeded.shop_id, v, 99, actor=_actor(seeded), now=NOW)
    await session.commit()
    assert _steps(again)["custom_order"] is False
    gone = await plans.remove_card(session, seeded.shop_id, d, actor=_actor(seeded), now=NOW)
    await session.commit()
    only = _steps(gone)
    assert [i["step"] for i in only["items"]] == ["voucher"]
    assert only["items"][0]["dprofit_step_p50"] == only["items"][0]["dprofit_total_p50"]
    assert only["total"]["dprofit_p50"] == only["items"][0]["dprofit_total_p50"]


async def test_cards_of_different_products_stay_independent_with_shop_totals(session, shop):
    seeded, env = shop
    a = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    other = {"change_kind": "product_discount", "items": ["1002"], "inputs": {"discount_pct": 15}}
    b = uuid.UUID((await _manual(session, seeded, env, other))["id"])
    await _add(session, seeded, a)
    out = await _add(session, seeded, b)
    agg = out["aggregate"]
    s1, s2 = _steps(out, "1001"), _steps(out, "1002")
    assert len(s1["items"]) == len(s2["items"]) == 1
    shop_total = agg["steps_summary"]["shop"]
    assert shop_total["products"] == 2
    assert shop_total["dprofit_p50"] == pytest.approx(agg["dprofit_month"]["total"]["p50"])
    # P99b: no money-layer certain figure on the option-result path
    assert s1["total"]["dprofit_certain"] is None and shop_total["dprofit_certain"] is None
    assert s1["total"]["dprofit_p50"] + s2["total"]["dprofit_p50"] == pytest.approx(
        shop_total["dprofit_p50"], rel=0.02, abs=100
    )
    assert shop_total["margin_pct_after"] is not None


async def test_a_combo_step_without_the_stacking_model_still_gets_a_margin(session, shop):
    seeded, env = shop
    d = uuid.UUID((await _manual(session, seeded, env, _discount(20)))["id"])
    c = uuid.UUID((await _manual(session, seeded, env, _combo()))["id"])
    await _add(session, seeded, d)
    out = await _add(session, seeded, c)
    steps = _steps(out)  # the combo is listed under its first product
    assert [i["step"] for i in steps["items"]][-1] == "combo"
    assert all(i["dprofit_total_p50"] is not None for i in steps["items"])


async def test_the_move_route_reorders_for_the_seller(session, shop, seller):
    seeded, env = shop
    d = uuid.UUID((await _manual(session, seeded, env, _discount(15)))["id"])
    v = uuid.UUID((await _manual(session, seeded, env, VOUCHER))["id"])
    await _add(session, seeded, d)
    await _add(session, seeded, v)
    await session.refresh(seeded.shop)
    await session.refresh(seeded.user)
    base = "/v1/demo/shopee/recommendations"
    r = await seller.post(f"{base}/plan/cards/{v}/move", json={"position": 1})
    assert r.status_code == 200, r.text
    steps = next(b for b in r.json()["aggregate"]["products"] if b["product_id"] == "1001")["steps"]
    assert [i["step"] for i in steps["items"]] == ["voucher", "giam_gia"]
    assert steps["custom_order"] is True
    bad = await seller.post(f"{base}/plan/cards/{v}/move", json={"position": 0})
    assert bad.status_code == 422
    unknown = await seller.post(f"{base}/plan/cards/{uuid.uuid4()}/move", json={"position": 1})
    assert unknown.status_code == 404
