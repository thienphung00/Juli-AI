"""P90 step 8: the Demo (seller) and Ops routes of the recommendation cards and the service
behind them -- list in ranking order, detail, what-if recompute, approve / request change /
dismiss, "Đã làm" with the `executed` event's `change`, publish, expiry, staleness, the
simulation import, the learning routes. SQLite; synthetic shops."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shop_proposals import ShopProposal, ShopProposalApproval
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.card_events import verification
from juli_backend.services.shopee_recommendations import store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_shop, make_user
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.support.shopee_worked import AS_OF as WORKED_AS_OF
from tests.support.shopee_worked import ITEM, seed_worked_example
from tests.unit.test_ops_shopee_dashboards import _ops_client

NOW = datetime(2026, 10, 8, 3, 0)
DEMO = "/v1/demo/shopee/recommendations"


async def _persist(session, shop_id, env, cands, *, start=1):
    ids = []
    for n, cand in enumerate(cands, start):
        card = build_card(env, cand, now=NOW)
        assert card is not None, cand.kind
        card["rank"] = {
            "position": n,
            "score": 1.0 / n,
            "detail": {},
            "mode": "gap_share_p25",
            "explore": False,
        }
        ids.append(
            await store.save_card(session, shop_id, card, cycle="2026-10", position=n, now=NOW)
        )
    await session.commit()
    return ids


def _cands():
    return [
        Candidate(
            "product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor", gap_pct=25.0
        ),
        Candidate(
            "min_spend_voucher",
            ("1002",),
            {"value": 3000, "min_spend": 90_000, "quantity": 50, "days": 14},
            wiring_key="aov",
        ),
        Candidate(
            "ads_budget", (), {"daily_budget": 36_000}, campaign_key="cgroup1", wiring_key="views"
        ),
        Candidate("bundle_deal", ("1003",), {"tier2_pct": 4, "tier3_pct": 6}, wiring_key="aov"),
    ]


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    ids = await _persist(session, seeded.shop_id, env, _cands())
    return seeded, env, ids


@pytest.fixture
async def seller(session, shop):
    seeded, _, _ = shop
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


async def _fresh(session, seeded):
    """A route that refuses rolls back; the app would load the shop afresh next request."""
    await session.refresh(seeded.shop)
    await session.refresh(seeded.user)


async def _publish(session, seeded, ids=None):
    sent = await reco.publish(session, seeded.shop_id, ids, now=NOW)
    await session.commit()
    return sent


async def _events(session, shop_id, card_id, event_type=None):
    q = select(CardEvent).where(CardEvent.shop_id == shop_id, CardEvent.card_id == card_id)
    if event_type:
        q = q.where(CardEvent.event_type == event_type)
    return list((await session.scalars(q.order_by(CardEvent.occurred_at))).all())


# ------------------------------------------------------------------- persistence shape


async def test_a_card_is_one_id_across_action_card_proposal_and_proposed_event(session, shop):
    seeded, _, ids = shop
    p = await session.get(ShopProposal, ids[0])
    assert p.status == "draft" and p.platform == "shopee" and p.kind == "price"
    assert p.item_id == "1001" and p.change_after["change_kind"] == "product_discount"
    (ev,) = await _events(session, seeded.shop_id, ids[0], "proposed")
    assert (
        ev.model_version.startswith("rules:ADR-121")
        and ev.payload["change_kind"] == "product_discount"
    )
    assert ev.workflow_key == "shopee_reco:promotion" and ev.dedup_key == f"proposed:{ids[0]}"
    frozen = await store.card_payload(session, seeded.shop_id, ids[0])
    assert (
        frozen["predicted"]["model_version"]
        and frozen["measurement_plan"]
        and frozen["inputs"] == {"discount_pct": 15}
    )
    meta = await store.card_meta(session, seeded.shop_id, ids[0])
    assert meta["locked_items"] == ["1001"] and meta["stale"] is False


# --------------------------------------------------------------------------- seller


async def test_the_seller_sees_published_cards_only_in_ranking_order(session, shop, seller):
    seeded, _, ids = shop
    assert (await seller.get(DEMO)).json()["cards"] == []  # drafts are Ops' until published
    assert (await seller.get(f"{DEMO}/{ids[0]}")).status_code == 404
    await _publish(session, seeded)
    body = (await seller.get(DEMO)).json()
    assert [c["id"] for c in body["cards"]] == [str(i) for i in ids]
    assert body["counts"]["family"] == {"promotion": 1, "voucher": 1, "ads": 1, "combo": 1}
    first = body["cards"][0]
    assert first["rank"]["position"] == 1 and first["predicted_summary"]["label"] == "Dự kiến"
    assert first["section"] == "ctor" and first["floor_ok"] is True


async def test_filters_by_family_and_section_and_the_xep_theo_switch(session, shop, seller):
    seeded, _, ids = shop
    await _publish(session, seeded)
    voucher = (await seller.get(DEMO, params={"family": "voucher"})).json()["cards"]
    assert [c["change_kind"] for c in voucher] == ["min_spend_voucher"]
    aov = (await seller.get(DEMO, params={"section": "aov"})).json()["cards"]
    assert {c["change_kind"] for c in aov} == {"min_spend_voucher", "bundle_deal"}
    for xep in ("diem", "gmv_per_day", "profit_per_day", "bien", "orders", "aov"):
        r = await seller.get(DEMO, params={"xep_theo": xep})
        assert r.status_code == 200 and len(r.json()["cards"]) == 4
    gmv = (await seller.get(DEMO, params={"xep_theo": "gmv_per_day"})).json()["cards"]
    vals = [
        (c["predicted_summary"]["dgmv_month"]["p50"] + c["certain_summary"]["dgmv_month"])
        / c["predicted_summary"]["effect_days"]
        for c in gmv
    ]
    assert vals == sorted(vals, reverse=True)
    assert (await seller.get(DEMO, params={"xep_theo": "nope"})).status_code == 422
    assert (await seller.get(DEMO, params={"family": "nope"})).status_code == 422


async def test_the_detail_has_certain_predicted_five_numbers_floor_plan_and_sheet(
    session, shop, seller
):
    seeded, _, ids = shop
    await _publish(session, seeded)
    body = (await seller.get(f"{DEMO}/{ids[1]}")).json()
    card = body["card"]
    assert card["certain"]["label"] == "Chắc chắn" and card["predicted"]["label"] == "Dự kiến"
    five = card["five_numbers"]
    assert set(five) >= {"discount", "extra_revenue_per_extra_spend", "margin", "orders", "aov"}
    assert card["measurement_plan"]["label"] and card["execution_sheet"]["page"]["deep_link"]
    assert card["execution_sheet"]["changes"][0]["change_kind"] == "voucher"
    assert [e["event"] for e in body["journey"]] == ["proposed"]
    text = json.dumps(body)
    # ADR-121 d.1: ranges and results, never the model or method
    for hidden in (
        "model_version",
        "shopee-reco-v1",
        "gate_weight",
        "run_id",
        "range_scale",
        "gap_bucket",
        "rank_inputs",
        "candidate_extra",
        "mde_14",
        "factor",
    ):
        assert hidden not in text, hidden
    assert card["predicted"]["lift"]["lift"]["p10"] <= card["predicted"]["lift"]["lift"]["p90"]
    for banned in ('"order_ref"', '"buyer', "recipient", '"phone', '"address'):
        assert banned not in text
    for ref in seeded.order_refs:
        assert ref not in text


async def test_whatif_recomputes_the_whole_card_and_records_the_adjustment(session, shop, seller):
    seeded, _, ids = shop
    await _publish(session, seeded)
    base = (await seller.get(f"{DEMO}/{ids[0]}")).json()["card"]
    r = await seller.post(f"{DEMO}/{ids[0]}/whatif", json={"inputs": {"discount_pct": 18}})
    assert r.status_code == 200, r.text
    new = r.json()["card"]
    assert new["inputs"]["discount_pct"] == 18
    assert new["certain"]["skus"][0]["price_after"] < base["certain"]["skus"][0]["price_after"]
    assert (
        new["five_numbers"]["discount"]["vnd_after"] > base["five_numbers"]["discount"]["vnd_after"]
    )
    assert new["id"] == base["id"] and "model_version" not in json.dumps(new)
    (adj,) = await _events(session, seeded.shop_id, ids[0], "whatif_adjusted")
    assert (
        adj.payload["inputs"] == {"discount_pct": 18}
        and adj.payload["change_kind"] == "product_discount"
    )
    # the frozen card did not move
    assert (await seller.get(f"{DEMO}/{ids[0]}")).json()["card"]["inputs"] == {"discount_pct": 15}
    deep = (
        await seller.post(f"{DEMO}/{ids[0]}/whatif", json={"inputs": {"discount_pct": 70}})
    ).json()["card"]
    assert deep["floor"]["ok"] is False and deep["floor"]["breaches"][0]["sku"] == "G1"
    assert len(await _events(session, seeded.shop_id, ids[0], "whatif_adjusted")) == 2


async def test_whatif_refuses_unknown_inputs_cards_and_other_shops(session, shop, seller):
    seeded, _, ids = shop
    await _publish(session, seeded)
    assert (await seller.post(f"{DEMO}/{ids[0]}/whatif", json={"nope": 1})).status_code == 422
    assert (
        await seller.post(f"{DEMO}/{uuid.uuid4()}/whatif", json={"inputs": {}})
    ).status_code == 404
    other = await make_user(session)
    other_shop = await make_shop(session, other, platform="shopee")
    await session.commit()
    app = build_app(session)
    authenticate(app, user=other, shop=other_shop)
    async with client_for(app) as stranger:
        assert (await stranger.get(f"{DEMO}/{ids[0]}")).status_code == 404
    app.dependency_overrides.clear()


async def test_a_tiktok_shop_is_refused(session):
    user = await make_user(session)
    tiktok = await make_shop(session, user, platform="tiktok")
    await session.commit()
    app = build_app(session)
    authenticate(app, user=user, shop=tiktok)
    async with client_for(app) as client:
        r = await client.get(DEMO)
    app.dependency_overrides.clear()
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_a_shopee_shop"


# ------------------------------------------------------------------------ decisions


async def test_approve_records_the_approval_and_the_accepted_event(session, shop, seller):
    seeded, _, ids = shop
    await _publish(session, seeded)
    r = await seller.post(f"{DEMO}/{ids[0]}/approve", json={})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    (acc,) = await _events(session, seeded.shop_id, ids[0], "accepted")
    assert acc.actor == "seller" and acc.payload["change_kind"] == "product_discount"
    assert acc.payload["final"] is None
    again = await seller.post(f"{DEMO}/{ids[0]}/approve", json={})
    assert again.status_code == 409  # a decided card is not decided twice


async def test_approving_with_adjusted_inputs_carries_them_to_the_sheet_and_the_defaults(
    session, shop, seller
):
    seeded, _, ids = shop
    await _publish(session, seeded)
    r = await seller.post(f"{DEMO}/{ids[0]}/approve", json={"inputs": {"discount_pct": 16}})
    assert r.status_code == 200, r.text
    (acc,) = await _events(session, seeded.shop_id, ids[0], "accepted")
    assert acc.payload["final"]["inputs"]["discount_pct"] == 16
    assert acc.payload["final_vs_default"] == {"discount_pct": pytest.approx(16 / 15)}
    detail = (await seller.get(f"{DEMO}/{ids[0]}")).json()
    assert detail["approved_with"]["inputs"]["discount_pct"] == 16


async def test_approving_inputs_that_break_a_floor_needs_the_acknowledgement(session, shop, seller):
    """P91 (owner 2026-11-04): a breach never blocks; it is refused until acknowledged, and the
    acknowledgement (who, when, which breaches) is recorded on the snapshot and the event."""
    seeded, _, ids = shop
    await _publish(session, seeded)
    body = {"inputs": {"discount_pct": 70}}
    r = await seller.post(f"{DEMO}/{ids[0]}/approve", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reco_breach_not_acknowledged"
    assert (await session.get(ShopProposal, ids[0])).status == "sent"
    await _fresh(session, seeded)
    r = await seller.post(f"{DEMO}/{ids[0]}/approve", json={**body, "acknowledge_breaches": True})
    assert r.status_code == 200, r.text
    (acc,) = await _events(session, seeded.shop_id, ids[0], "accepted")
    ack = acc.payload["acknowledged_breaches"]
    assert ack["by"] == str(seeded.user.id) and ack["at"] and ack["breaches"][0]["type"] == "floor"
    approval = await session.scalar(
        select(ShopProposalApproval).where(ShopProposalApproval.proposal_id == ids[0])
    )
    assert approval.proposal_snapshot["acknowledged_breaches"]["breaches"]


async def test_request_change_and_dismiss_with_an_adr_107_reason(session, shop, seller):
    seeded, _, ids = shop
    await _publish(session, seeded)
    r = await seller.post(f"{DEMO}/{ids[0]}/request-change", json={"note": "giảm nhẹ hơn"})
    assert r.status_code == 200 and r.json()["status"] == "changes_requested"
    (edited,) = await _events(session, seeded.shop_id, ids[0], "edited")
    assert edited.payload["request"] == "giảm nhẹ hơn"
    d = await seller.post(f"{DEMO}/{ids[1]}/dismiss", json={"reason_code": "not_needed"})
    assert d.status_code == 200 and d.json()["status"] == "rejected"
    (dis,) = await _events(session, seeded.shop_id, ids[1], "dismissed")
    assert dis.reason_code == "not_needed"
    quiet = await seller.post(f"{DEMO}/{ids[2]}/dismiss", json={})
    assert quiet.json()["reason_code"] == "unspecified"
    bad = await seller.post(f"{DEMO}/{ids[3]}/dismiss", json={"reason_code": "because"})
    assert bad.status_code == 422
    await _fresh(session, seeded)
    assert (await seller.post(f"{DEMO}/{ids[3]}/request-change", json={})).status_code == 422


async def test_acceptance_statistics_follow_the_decisions_and_never_touch_the_effect(
    session, shop, seller
):
    seeded, _, ids = shop
    await _publish(session, seeded)
    await seller.post(f"{DEMO}/{ids[0]}/approve", json={})
    await seller.post(f"{DEMO}/{ids[1]}/dismiss", json={"reason_code": "later"})
    stats = await store.load_acceptance(session, seeded.shop_id)
    assert stats.approved["product_discount"] == 1 and stats.dismissed["min_spend_voucher"] == 1
    assert stats.reasons["min_spend_voucher"]["later"] == 1
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert env.acceptance.rate("product_discount") == pytest.approx(2 / 3)
    plain = build_card(env, _cands()[0], now=NOW)
    env.acceptance = None
    assert build_card(env, _cands()[0], now=NOW)["predicted"]["lift"] == plain["predicted"]["lift"]


# --------------------------------------------------------------------------- executed


async def test_marking_done_writes_executed_events_with_the_change_for_the_read_back(
    session, shop, seller
):
    seeded, _, ids = shop
    await _publish(session, seeded)
    too_early = await seller.post(f"{DEMO}/{ids[2]}/executed", json={})
    assert too_early.status_code == 409
    await _fresh(session, seeded)
    await seller.post(f"{DEMO}/{ids[2]}/approve", json={})
    r = await seller.post(f"{DEMO}/{ids[2]}/executed", json={})
    assert r.status_code == 201 and r.json()["events"] == 1
    (ex,) = await _events(session, seeded.shop_id, ids[2], "executed")
    assert ex.payload["change"] == {
        "change_kind": "daily_budget",
        "target": {"campaign_id": None},
        "expected": {"daily_budget": 36000},
    }
    assert ex.payload["executor_role"] == "client_representative"
    assert (await session.get(ShopProposal, ids[2])).status == "executed"
    pending = await verification.pending_changes(session, seeded.shop_id, NOW + timedelta(hours=1))
    assert [c.change_kind for c in pending] == ["daily_budget"] and pending[0].card_id == ids[2]
    assert (await seller.post(f"{DEMO}/{ids[2]}/executed", json={})).status_code == 409


async def test_a_voucher_needs_its_id_to_be_read_back_and_a_price_change_is_a_price_event(
    session, shop, seller
):
    seeded, _, ids = shop
    await _publish(session, seeded)
    for i in (ids[0], ids[1]):
        await seller.post(f"{DEMO}/{i}/approve", json={})
    assert (await seller.post(f"{DEMO}/{ids[1]}/executed", json={})).status_code == 422
    await _fresh(session, seeded)
    ok = await seller.post(f"{DEMO}/{ids[1]}/executed", json={"voucher_id": "9001"})
    assert ok.status_code == 201
    (v,) = await _events(session, seeded.shop_id, ids[1], "executed")
    assert v.payload["change"]["change_kind"] == "voucher" and v.payload["change"]["target"] == {
        "voucher_id": "9001"
    }
    assert v.payload["change"]["expected"] == {
        "discount_amount": 3000,
        "min_spend": 90000,
        "usage_limit": 50,
    }
    p = await seller.post(f"{DEMO}/{ids[0]}/executed", json={})
    assert p.status_code == 201
    (pe,) = await _events(session, seeded.shop_id, ids[0], "executed")
    assert (
        pe.payload["change"]["change_kind"] == "price"
        and pe.payload["change"]["target"]["item_id"] == "1001"
    )


# ----------------------------------------------------------------------------- expiry


async def test_a_card_unanswered_for_seven_days_expires(session, shop):
    seeded, _, ids = shop
    await _publish(session, seeded)
    assert await reco.expire_old(session, seeded.shop_id, now=NOW + timedelta(days=6)) == 0
    assert await reco.expire_old(session, seeded.shop_id, now=NOW + timedelta(days=8)) == 4
    await session.commit()
    assert await reco.expire_old(session, seeded.shop_id, now=NOW + timedelta(days=9)) == 0  # once
    assert len(await _events(session, seeded.shop_id, ids[0], "expired")) == 1


# ------------------------------------------------------------------------------ locks


async def test_open_plans_lock_their_products_until_the_plan_ends(session, shop, seller):
    seeded, _, ids = shop
    assert await store.locked_products(session, seeded.shop_id, NOW) == {}  # drafts hold nothing
    await _publish(session, seeded)
    locked = await store.locked_products(session, seeded.shop_id, NOW)
    assert set(locked) == {"1001", "1002", "1003"}
    await seller.post(f"{DEMO}/{ids[0]}/dismiss", json={})
    assert "1001" not in await store.locked_products(session, seeded.shop_id, NOW)
    await seller.post(f"{DEMO}/{ids[3]}/approve", json={})
    await seller.post(f"{DEMO}/{ids[3]}/executed", json={"executed_at": NOW.isoformat()})
    plan_days = (await store.card_meta(session, seeded.shop_id, ids[3]))["plan_days"] or 14
    assert "1003" in await store.locked_products(
        session, seeded.shop_id, NOW + timedelta(days=plan_days - 1)
    )
    assert "1003" not in await store.locked_products(
        session, seeded.shop_id, NOW + timedelta(days=plan_days + 1)
    )


# --------------------------------------------------------------------------- staleness


async def test_mark_stale_for_flags_only_the_affected_cards_and_rerun_recomputes_only_those(
    session, shop
):
    seeded, _, ids = shop
    await _publish(session, seeded, [ids[0], ids[1]])
    n = await reco.mark_stale_for(session, seeded.shop_id, product_ids=["1001"])
    assert n == 1
    assert (await store.card_meta(session, seeded.shop_id, ids[0]))["stale"] is True
    assert (await store.card_meta(session, seeded.shop_id, ids[1]))["stale"] is False
    assert (await store.card_meta(session, seeded.shop_id, ids[3]))[
        "stale"
    ] is False  # a draft of 1003
    # by SKU: the imported scope may be "item:variation"
    assert await reco.mark_stale_for(session, seeded.shop_id, sku_ids=["1002:77"]) == 1
    assert await reco.mark_stale_for(session, seeded.shop_id, product_ids=["9999"]) == 0
    assert await reco.mark_stale_for(session, seeded.shop_id) == 0
    counts = await reco.rerun_stale(session, seeded.shop_id, now=NOW)
    await session.commit()
    assert counts["stale"] == 2 and counts["revised"] == 2 and counts["replaced"] == 0
    old = await session.get(ShopProposal, ids[0])
    assert old.status == "superseded"
    sent = (
        await session.scalars(select(ShopProposal).where(ShopProposal.supersedes_id == ids[0]))
    ).one()
    assert sent.status == "draft" and sent.revision == 2
    (proposed,) = await _events(session, seeded.shop_id, sent.id, "proposed")
    assert proposed.payload["change_kind"] == "product_discount"
    assert (await reco.rerun_stale(session, seeded.shop_id, now=NOW))["stale"] == 0


async def test_shop_wide_changes_flag_every_target_sensitive_card(session, shop):
    seeded, _, ids = shop
    await _publish(session, seeded)
    assert await reco.mark_stale_for(session, seeded.shop_id, shop_wide=True) == 4


async def test_the_importer_hook_is_registered_and_marks_through_it(session, shop):
    from juli_backend.services.shop_inputs.affected import StaleRequest, mark_stale

    seeded, _, ids = shop
    await _publish(session, seeded)
    req = StaleRequest(("1001",), False, "seller_inputs_changed", NOW)
    assert await mark_stale(session, seeded.shop_id, req) >= 1
    assert (await store.card_meta(session, seeded.shop_id, ids[0]))["stale"] is True
    assert (await store.card_meta(session, seeded.shop_id, ids[0]))[
        "stale_reason"
    ] == "seller_inputs_changed"


# --------------------------------------------------------------------- contract 7 worked example


async def test_the_worked_example_numbers_come_out_of_the_api_what_if(session):
    seeded = await seed_worked_example(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=WORKED_AS_OF)
    today = {"value": 10_000, "min_spend": 200_000, "quantity": None, "days": 30}
    (cid,) = await _persist(
        session,
        seeded.shop_id,
        env,
        [Candidate("min_spend_voucher", (ITEM,), {**today, "baseline": today}, wiring_key="aov")],
    )
    await _publish(session, seeded)
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        r = await client.post(f"{DEMO}/{cid}/whatif", json={"inputs": {"value": 15_000}})
    app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    c = r.json()["card"]["certain"]
    assert c["extra_cost"] == 150_000
    assert c["organic"]["profit_per_order"] == 54_250 and c["organic"]["margin_pct"] == 29.3
    assert c["break_even_extra_orders"] == 3 and c["qualifying_orders"] == 30
    assert c["discount_pct_of_qualifying"] == 7.5
    five = r.json()["card"]["five_numbers"]
    assert five["margin"]["pct_before"] == 30.8 and five["margin"]["pct_after"] == 29.3
    assert five["extra_revenue_per_extra_spend"]["status"] == "needs_volume"
    assert r.json()["card"]["floor"]["ok"] is True


# ------------------------------------------------------------------------------- Ops


@pytest.fixture
async def ops(session, shop, monkeypatch):
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


async def test_ops_sees_drafts_publishes_and_the_audit_row_is_written(session, shop, ops):
    seeded, _, ids = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    listing = (await ops.get(base)).json()
    assert len(listing["cards"]) == 4 and {c["status"] for c in listing["cards"]} == {"draft"}
    one = await ops.post(f"{base}/publish", json={"card_ids": [str(ids[0])]})
    assert one.status_code == 200 and one.json()["sent"] == [str(ids[0])]
    assert (await session.get(ShopProposal, ids[0])).status == "sent"
    rest = await ops.post(f"{base}/publish", json={})
    assert len(rest.json()["sent"]) == 3
    detail = await ops.get(f"{base}/{ids[0]}")
    assert detail.status_code == 200 and detail.json()["status"] == "sent"
    actions = [r.action for r in (await session.scalars(select(OpsAuditLog))).all()]
    assert actions.count("reco_publish") == 2
    wd = await ops.post(f"{base}/{ids[1]}/withdraw")
    assert wd.status_code == 200 and (await session.get(ShopProposal, ids[1])).status == "withdrawn"


async def test_ops_generate_ranks_and_persists_drafts(session, shop, ops):
    seeded, _, _ = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    r = await ops.post(f"{base}/generate", json={"as_of": AS_OF.isoformat(), "top_n": 5})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["generated"] >= 1 and body["persisted"] == len(body["card_ids"])
    assert body["ranking"]["mode"] in ("gap_share_p25", "dgmv_month_p25")
    assert set(body["ranking"]["filters_first"]) >= {
        "below_operating_floor",
        "over_spend_cap",
        "negative_profit_p50",
    }
    dry = await ops.post(f"{base}/generate", json={"as_of": AS_OF.isoformat(), "persist": False})
    assert dry.json()["persisted"] == 0


async def test_ops_generate_with_a_mega_window(session, shop, ops):
    seeded, _, _ = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    r = await ops.post(
        f"{base}/generate",
        json={
            "as_of": AS_OF.isoformat(),
            "mega": {
                "start": "2026-11-11T00:00:00",
                "end": "2026-11-12T00:00:00",
                "budget_cap_per_day": "300000",
            },
        },
    )
    assert r.status_code == 201, r.text
    mega = r.json()["mega"]
    assert mega is None or mega["window"]["days"] == 1


async def test_ops_whatif_does_not_record_and_viewers_cannot_write(session, shop, monkeypatch):
    seeded, _, ids = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        w = await client.post(f"{base}/{ids[0]}/whatif", json={"inputs": {"discount_pct": 17}})
        assert w.status_code == 200 and w.json()["card"]["inputs"]["discount_pct"] == 17
        assert await _events(session, seeded.shop_id, ids[0], "whatif_adjusted") == []
        for path in ("generate", "publish", "rerun-stale", "learning/run", "learning/backfill"):
            r = await client.post(f"{base}/{path}", json={})
            assert r.status_code == 403, path
        assert (await client.get(f"{base}/learning")).status_code == 200
    app.dependency_overrides.clear()


async def test_ops_marks_done_and_the_execution_is_recorded_by_staff(
    session, shop, ops, monkeypatch
):
    seeded, _, ids = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    await ops.post(f"{base}/publish", json={})
    await session.execute(
        ShopProposal.__table__.update().where(ShopProposal.id == ids[2]).values(status="approved")
    )
    await session.commit()
    r = await ops.post(f"{base}/{ids[2]}/executed", json={})
    assert r.status_code == 201, r.text
    (ex,) = await _events(session, seeded.shop_id, ids[2], "executed")
    assert ex.payload["executor_role"] == "juli_operator"


# ------------------------------------------------------------------ simulation import


def _priors_doc(item="1001", med=0.9, weight=0.0):
    return {
        "format": "juli-sim/priors/v1",
        "run_id": "ory-priors-test",
        "platform": "shopee",
        "shop_alias": "alias",
        "gate": {
            "product_discount": {
                "weight": weight,
                "status": "fail",
                "reason": "not_beating_plain_prior",
            }
        },
        "versions": {"model_version": "shopee-port-v1.0", "priors_version": "p"},
        "rows": [
            {
                "product_id": item,
                "change_kind": "product_discount",
                "variant": "price_-15_banner",
                "segment": "all",
                "metric": "ctor",
                "med": med,
                "lo90": med - 0.1,
                "hi90": med + 0.1,
                "kg_value": 0.02,
                "eligible": True,
            },
        ],
    }


async def test_the_audited_sim_import_stores_the_run_and_a_zero_gate_changes_no_range(
    session, shop, ops
):
    seeded, env, ids = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    before = build_card(env, _cands()[0], now=NOW)["predicted"]["lift"]["lift"]
    r = await ops.post(f"{base}/sim-priors", json={"document": _priors_doc()})
    assert r.status_code == 201, r.text
    assert r.json()["gate_decisions"]["product_discount"] == {
        "weight": 0.0,
        "status": "fail",
        "override": False,
    }
    assert (await ops.get(f"{base}/sim-priors")).json()["active"]["run_id"] == "ory-priors-test"
    audit = [
        a
        for a in (await session.scalars(select(OpsAuditLog))).all()
        if a.action == "reco_sim_import"
    ]
    assert len(audit) == 1 and "1001" not in json.dumps(audit[0].after)
    env2 = await load_env(session, seeded.shop_id, as_of=AS_OF)
    assert env2.sim is not None and env2.sim.gate_weight("product_discount") == 0.0
    after = build_card(env2, _cands()[0], now=NOW)
    assert (
        after["predicted"]["lift"]["lift"] == before
    )  # weight 0: ranges equal the no-simulation path
    assert (
        after["predicted"]["sim"]["row_found"] is True
        and after["predicted"]["sim"]["applied"] is False
    )


async def test_an_override_gate_moves_the_range_and_is_recorded(session, shop, ops):
    seeded, env, _ = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    before = build_card(env, _cands()[0], now=NOW)["predicted"]["lift"]
    r = await ops.post(
        f"{base}/sim-priors",
        json={"document": _priors_doc(), "gate_overrides": {"product_discount": 1.0}},
    )
    assert r.json()["gate_decisions"]["product_discount"]["override"] is True
    env2 = await load_env(session, seeded.shop_id, as_of=AS_OF)
    after = build_card(env2, _cands()[0], now=NOW)["predicted"]
    assert after["sim"]["applied"] is True and after["lift"]["lift"]["p50"] == pytest.approx(
        0.9, abs=0.01
    )
    assert after["lift"]["lift"] != before["lift"]
    # a newer run supersedes the older one
    await ops.post(f"{base}/sim-priors", json={"document": {**_priors_doc(), "run_id": "second"}})
    assert (await ops.get(f"{base}/sim-priors")).json()["active"]["run_id"] == "second"


async def test_an_invalid_sim_file_is_a_422_that_quotes_nothing(session, shop, ops):
    seeded, _, _ = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    r = await ops.post(f"{base}/sim-priors", json={"document": {**_priors_doc(), "format": "x"}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "sim_import_invalid"
    assert (await ops.get(f"{base}/sim-priors")).json() == {"active": None}


# ----------------------------------------------------------------------- learning routes


async def test_the_learning_routes_run_and_report_without_client_values(session, shop, ops):
    seeded, _, _ = shop
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    run = (await ops.post(f"{base}/learning/run")).json()
    assert run["cards_considered"] == 0 and run["calibration_rows"] == 0
    bf = (await ops.post(f"{base}/learning/backfill")).json()
    assert isinstance(bf, dict)
    overview = (await ops.get(f"{base}/learning")).json()
    assert overview["calibration"] == [] and overview["sim"] is None and "acceptance" in overview


def test_money_helpers_are_decimals_at_the_boundary():
    assert D("1") + D("2") == 3


# ---------------------------------------------------------------------------- mega_sale


async def test_a_mega_sale_is_edited_approved_and_executed_as_one_card(session, shop, seller):
    from juli_backend.services.shopee_recommendations.mega import MegaWindow, build_mega_card

    seeded, env, _ = shop
    kids = [
        Candidate("product_discount", ("1001",), {"discount_pct": 15}),
        Candidate(
            "min_spend_voucher",
            ("1002",),
            {"value": 3000, "min_spend": 50_000, "quantity": 1000, "days": 1},
        ),
        Candidate("ads_budget", (), {"daily_budget": 36_000}, campaign_key="cgroup1"),
    ]
    window = MegaWindow(datetime(2026, 11, 11), datetime(2026, 11, 12))
    card = build_mega_card(
        env, kids, window, now=NOW, budget_cap_per_day=D(300_000), child_ids=["a", "b", "c"]
    )
    card["rank"] = {"position": 9, "score": 0.0, "detail": {}, "mode": "x", "explore": False}
    cid = await store.save_card(session, seeded.shop_id, card, cycle="mega", position=9, now=NOW)
    await _publish(session, seeded, [cid])
    meta = await store.card_meta(session, seeded.shop_id, cid)
    assert meta["locked_items"] == ["1001", "1002"] and meta["lock_until"] == window.end.isoformat()
    # the product lock holds until the window ends (the card is only sent)
    assert set(await store.locked_products(session, seeded.shop_id, NOW)) >= {"1001", "1002"}
    assert "1002" not in await store.locked_products(
        session, seeded.shop_id, datetime(2026, 11, 13)
    )
    detail = (await seller.get(f"{DEMO}/{cid}")).json()["card"]
    assert [c["child_id"] for c in detail["children"]] == ["a", "b", "c"]
    # children are editable before approval: a smaller discount, one child out, a new cap
    r = await seller.post(
        f"{DEMO}/{cid}/whatif",
        json={
            "inputs": {
                "children": {"a": {"discount_pct": 12}},
                "remove": ["c"],
                "budget_cap_per_day": 150_000,
            }
        },
    )
    assert r.status_code == 200, r.text
    new = r.json()["card"]
    assert [c["child_id"] for c in new["children"]] == ["a", "b"]
    assert (
        new["children"][0]["inputs"] == {"discount_pct": 12}
        and new["inputs"]["budget_cap_per_day"] == 150000
    )
    assert new["certain"]["total_discount"] < detail["certain"]["total_discount"]
    ok = await seller.post(f"{DEMO}/{cid}/approve", json={"inputs": {"remove": ["c"]}})
    assert ok.status_code == 200, ok.text
    done = await seller.post(f"{DEMO}/{cid}/executed", json={"voucher_id": "9100"})
    assert done.status_code == 201
    events = await _events(session, seeded.shop_id, cid, "executed")
    kinds = sorted(e.payload["change"]["change_kind"] for e in events)
    assert kinds == ["price", "voucher"]  # the removed ads child is not executed
    assert all(e.payload["bundle"] is True for e in events)
    voucher = next(e for e in events if e.payload["change"]["change_kind"] == "voucher")
    assert voucher.payload["change"]["target"] == {"voucher_id": "9100"}


# ---------------------------------------------- Quyết định UI fields (step 9c)


async def test_the_approved_sheet_is_stored_at_approval_and_returned_in_the_detail(
    session, shop, seller
):
    seeded, _, ids = shop
    await _publish(session, seeded)
    plain = await seller.post(f"{DEMO}/{ids[0]}/approve", json={})
    assert plain.status_code == 200
    detail = (await seller.get(f"{DEMO}/{ids[0]}")).json()
    frozen = await store.card_payload(session, seeded.shop_id, ids[0])
    assert detail["approved_with"]["inputs"] == {"discount_pct": 15}
    assert detail["approved_with"]["execution_sheet"] == frozen["execution_sheet"]
    # adjusted inputs: the stored sheet is the one for THOSE inputs, and "Đã làm" follows it
    moved = await seller.post(f"{DEMO}/{ids[3]}/approve", json={"inputs": {"tier2_pct": 3}})
    assert moved.status_code == 200, moved.text
    detail2 = (await seller.get(f"{DEMO}/{ids[3]}")).json()
    assert detail2["approved_with"]["inputs"]["tier2_pct"] == 3
    steps = detail2["approved_with"]["execution_sheet"]["steps"]
    assert (
        steps
        != (await store.card_payload(session, seeded.shop_id, ids[3]))["execution_sheet"]["steps"]
    )
    done = await seller.post(f"{DEMO}/{ids[3]}/executed", json={})
    assert done.status_code == 201


async def test_the_seller_list_carries_explore_and_the_read_back_state(session, shop, seller):
    seeded, _, ids = shop
    await store.set_meta(session, seeded.shop_id, ids[0], {})
    frozen = await session.scalar(
        select(CardEvent).where(CardEvent.card_id == ids[1], CardEvent.event_type == "proposed")
    )
    frozen.payload = {**frozen.payload, "rank": {**frozen.payload["rank"], "explore": True}}
    await session.commit()
    await _publish(session, seeded)
    await seller.post(f"{DEMO}/{ids[0]}/approve", json={})
    listing = {c["id"]: c for c in (await seller.get(DEMO)).json()["cards"]}
    assert listing[str(ids[1])]["rank"]["explore"] is True
    assert listing[str(ids[0])]["rank"]["explore"] is False
    assert all(c["verification"]["state"] is None for c in listing.values())  # nothing done yet
    await seller.post(f"{DEMO}/{ids[0]}/executed", json={})
    now_list = {c["id"]: c for c in (await seller.get(DEMO)).json()["cards"]}
    assert now_list[str(ids[0])]["verification"]["state"] == "pending"
    # the Connector's read-back writes the verdict; the list follows
    pending = await verification.pending_changes(session, seeded.shop_id, NOW + timedelta(hours=1))
    change = pending[0]
    verdict = verification.Verdict(
        "verified", {"current_price": 1}, change.executed_at + timedelta(hours=2)
    )
    await verification.record_verdict(session, change, verdict, now=NOW)
    await session.commit()
    final = {c["id"]: c for c in (await seller.get(DEMO)).json()["cards"]}
    assert final[str(ids[0])]["verification"]["state"] == "verified"
    detail = (await seller.get(f"{DEMO}/{ids[0]}")).json()
    row = next(j for j in detail["journey"] if j["event"] == "verified")
    assert row["payload"]["observed"] == {"current_price": 1} and row["payload"]["observed_at"]
    assert detail["verification"]["state"] == "verified"
