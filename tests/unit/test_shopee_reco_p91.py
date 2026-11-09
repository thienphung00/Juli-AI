"""P91 wave 1 (D-1, D-2, D-4, D-5): the per-product queue, versions inside a card, the 100-character
title, card codes. Pure functions first, then SQLite flows on the synthetic reco shop."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.shop_proposals import ShopProposal, ShopProposalApproval
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import (
    codes,
    config,
    product_queue,
    service,
    store,
    versions,
)
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.kinds import KINDS
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.product_queue import QueueCard, assign
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client

NOW = datetime(2026, 10, 8, 3, 0)
REPO = Path(__file__).resolve().parents[2]
MIG = REPO / "backend/src/juli_backend/database/migrations/versions/116_shopee_reco_codes.py"


# ============================================================================ queue (pure)


def _q(id_, product="p1", status="sent", score=1.0, **kw):
    return QueueCard(id_, product, status, score, **kw)


def test_the_queue_numbers_open_cards_of_a_product_best_score_first():
    got = assign([_q("a", score=1), _q("b", score=3), _q("c", score=2), _q("z", "p2", score=0)])
    assert got == {"a": 3, "b": 1, "c": 2, "z": 1}


@pytest.mark.parametrize(
    "status", ["rejected", "withdrawn", "superseded", "executed", "measured", "planned"]
)
def test_a_closed_executed_or_planned_card_gives_its_place_up_at_once(status):
    got = assign([_q("first", status=status, score=9), _q("next", score=1)])
    assert got == {"first": None, "next": 1}


def test_an_expired_card_closes_and_a_planned_card_returns_when_it_leaves_the_plan():
    assert assign([_q("a", expired=True, score=9), _q("b", score=1)]) == {"a": None, "b": 1}
    planned = assign([_q("a", status="planned", score=9), _q("b", score=1)])
    assert planned == {"a": None, "b": 1}
    back = assign([_q("a", status="sent", score=9, queue=None), _q("b", score=1, queue=1)])
    assert back == {"a": 1, "b": 2}


def test_a_card_the_seller_approved_goes_ahead_and_a_card_without_product_has_no_place():
    got = assign([_q("a", score=9), _q("b", status="approved", score=1), _q("s", None, score=5)])
    assert got == {"a": 2, "b": 1, "s": None}


def test_renumbering_is_stable_and_idempotent():
    cards = [_q("a", score=1, queue=2), _q("b", score=1, queue=1), _q("c", score=1)]
    once = assign(cards)
    assert once == {"b": 1, "a": 2, "c": 3}
    again = assign([_q(k, queue=v, score=1) for k, v in once.items()])
    assert again == once


def test_the_measurement_window_ends_the_day_after_start_plus_plan_days():
    t = datetime(2026, 10, 1, 10, 0)
    kw = {"executed_at": t, "verified_at": None, "plan_days": 14, "has_final_reading": False}
    assert not product_queue.window_over(now=datetime(2026, 10, 15, 23, 0), **kw)
    assert product_queue.window_over(now=datetime(2026, 10, 16, 0, 0), **kw)
    assert product_queue.window_over(now=t, **{**kw, "has_final_reading": True})
    late = {**kw, "verified_at": datetime(2026, 10, 3, 9, 0)}
    assert not product_queue.window_over(now=datetime(2026, 10, 16, 0, 0), **late)


# ========================================================================= versions (pure)


BASE_INPUTS = {
    "ads_budget": {"daily_budget": 40_000},
    "ads_roas_target": {"roas_target": 4.0},
    "product_discount": {"discount_pct": 10},
    "price": {"new_price_pct": 100},
    "min_spend_voucher": {"value": 10_000, "max_value": 10_000, "min_spend": 100_000},
    "review_voucher": {"value": 5_000, "min_spend": 50_000},
    "voucher_cap": {"value": 10_000, "quantity": 100},
    "flash_sale": {"discount_pct": 20, "units": 40},
    "program_registration": {"discount_pct": 15, "units": 40},
    "bundle_deal": {"tier2_pct": 5, "tier3_pct": 10},
    "add_on": {"addon_discount_pct": 20},
    "gift": {"min_spend": 100_000},
    "variation_set": {"set_size": 3},
    "affiliate_commission": {"commission_pct": 6},
    "affiliate_target_campaign": {"commission_pct": 8},
    "affiliate_sample": {"qty": 2, "commission_pct": 8},
    "affiliate_invite": {"commission_pct": 8},
}


@pytest.mark.parametrize("kind", sorted(BASE_INPUTS))
def test_each_family_has_alternatives_inside_its_sliders_and_different_from_the_default(kind):
    inputs = BASE_INPUTS[kind]
    alts = versions.alternative_inputs(kind, inputs, {"daily_budget": 30_000})
    assert 1 <= len(alts) <= config.MAX_VERSIONS - 1
    sliders = {s.key: s for s in KINDS[kind].sliders}
    seen = [dict(inputs)]
    for alt in alts:
        assert alt not in seen
        seen.append(alt)
        for k, v in alt.items():
            assert sliders[k].minimum <= v <= sliders[k].maximum, (kind, k, v)


def test_every_kind_with_a_rule_has_sliders_and_the_ads_budget_is_relative_to_today():
    assert set(versions.ALTERNATIVES) <= set(KINDS)
    assert set(BASE_INPUTS) == set(versions.ALTERNATIVES)
    alts = versions.alternative_inputs(
        "ads_budget", {"daily_budget": 36_000}, {"daily_budget": 30_000}
    )
    # -20 % / +20 % / +50 % of today's 30.000, on the slider's 10.000 step (half up)
    assert [a["daily_budget"] for a in alts] == [20_000, 40_000, 50_000]


def test_kinds_with_no_knob_keep_one_version():
    for kind in ("cover_image", "price_display", "ads_pause", "mega_sale"):
        assert versions.alternative_inputs(kind, {}) == []


def test_a_voucher_scales_its_value_and_its_min_spend_together():
    alts = versions.alternative_inputs("min_spend_voucher", BASE_INPUTS["min_spend_voucher"])
    assert alts[0] == {"value": 7_000, "max_value": 7_000, "min_spend": 70_000}


# ================================================================================== titles


def test_the_title_limit_is_100_and_the_visible_limit_never_exceeds_it():
    assert config.MAX_TITLE_CHARS == 100
    assert config.TITLE_VISIBLE_CHARS <= config.MAX_TITLE_CHARS


def test_cut_title_cuts_at_a_word_boundary_and_never_above_the_limit():
    text = " ".join(f"từ{n:02d}" for n in range(1, 60))
    out = lst.cut_title(text)
    assert len(out) <= 100 and text.startswith(out) and not out.endswith(" ")
    assert text[len(out)] == " "  # cut between words
    assert lst.cut_title("ngắn gọn") == "ngắn gọn"
    assert len(lst.cut_title("x" * 250)) == 100  # one word longer than the limit: cut hard


def test_a_title_input_above_100_characters_is_refused_with_422():
    card = {"change_kind": "title"}
    service.check_title_input(card, {"title": "a" * 100})
    for bad in ("a" * 101, "   "):
        with pytest.raises(ProposalError) as err:
            service.check_title_input(card, {"title": bad})
        assert err.value.status == 422
    service.check_title_input({"change_kind": "ads_budget"}, {"title": "a" * 500})  # not a title


# =================================================================================== codes


def test_code_format_parse_and_version_codes():
    assert codes.format_code(datetime(2026, 11, 4), 7) == "JC-2611-0007"
    assert codes.format_code(datetime(2027, 1, 2), 12345) == "JC-2701-12345"
    assert codes.version_code("JC-2611-0007", 3) == "JC-2611-0007-V3"
    assert codes.parse_code("jc-2611-0007") == ("JC-2611-0007", None)
    assert codes.parse_code("JC-2611-0007-V2") == ("JC-2611-0007", 2)
    for bad in ("JC-2611-7", "XX-2611-0007", "JC-2611-0007-V0", "JC-2611-0007-V12", ""):
        assert codes.parse_code(bad) is None
    with pytest.raises(ValueError):
        codes.version_code("JC-2611-0007", 5)
    with pytest.raises(ValueError):
        codes.format_code(NOW, 0)


def test_migration_116_is_additive_reversible_and_takes_the_tail():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIG])
    assert [f.render() for f in result.findings] == [] and result.accepted
    src = MIG.read_text("utf-8")
    assert 'revision: str = "116_shopee_reco_codes"' in src
    assert 'down_revision: str | None = "115_shopee_recommendations"' in src
    tail = REPO / "backend/src/juli_backend/database/migrations/deferred/101_write_mode_backfill.py"
    assert 'down_revision: str | None = "123_shopee_metrics_tables"' in tail.read_text("utf-8")


# ============================================================================ flows (SQLite)


def _ranked(card, n, score):
    card["rank"] = {"position": n, "score": score, "detail": {}, "mode": "x", "explore": False}
    return card


async def _save(session, sid, env, cand, n, score, *, queue=None):
    card = build_card(env, cand, now=NOW)
    assert card is not None, cand.kind
    card["versions"] = versions.build_versions(env, cand, card, now=NOW)
    _ranked(card, n, score)
    return await store.save_card(
        session, sid, card, cycle="2026-10", position=n, now=NOW, product_queue=queue
    )


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    return seeded, env


async def _three_on_one_product(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cands = [
        Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor"),
        Candidate(
            "min_spend_voucher",
            ("1001",),
            {"value": 3000, "min_spend": 90_000, "quantity": 50, "days": 14},
            wiring_key="aov",
        ),
        Candidate("bundle_deal", ("1001",), {"tier2_pct": 4, "tier3_pct": 6}, wiring_key="aov"),
    ]
    ids = [await _save(session, sid, env, c, n, 3.0 - n) for n, c in enumerate(cands, 1)]
    await session.commit()
    await product_queue.requeue_products(session, sid, ["1001"], NOW)
    await session.commit()
    return ids


async def _queue(session, ids):
    rows = (await session.scalars(select(ShopProposal).where(ShopProposal.id.in_(ids)))).all()
    by = {p.id: p.product_queue for p in rows}
    return [by[i] for i in ids]


async def test_generation_keeps_every_card_numbers_each_product_and_gives_codes(session, shop):
    seeded, _ = shop
    sid = seeded.shop_id
    report = await reco.generate_cards(session, sid, now=NOW, as_of=AS_OF)
    await session.commit()
    assert report.persisted == len(report.rank.ordered) > 0
    assert "duplicate_product" not in report.rank.counts
    rows = await store.list_cards(session, sid)
    by_product: dict[str, list[int]] = {}
    got = []
    for p, card in rows:
        assert codes.parse_code(p.code or "") == (p.code, None)
        assert card["code"] == p.code
        got.append(p.code)
        if p.item_id:
            by_product.setdefault(p.item_id, []).append(p.product_queue)
        vs = card["versions"]
        assert [v["version"] for v in vs] == list(range(1, len(vs) + 1))
        assert [v["code"] for v in vs] == [f"{p.code}-V{v['version']}" for v in vs]
        assert vs[0]["ranked"] and not any(v["ranked"] for v in vs[1:])
    assert len(got) == len(set(got))  # unique
    assert any(len(v) > 1 for v in by_product.values())  # a product holds several cards
    for places in by_product.values():
        assert sorted(places) == list(range(1, len(places) + 1))
    assert any(len(card["versions"]) >= 2 for _, card in rows)
    # re-running changes nothing
    assert await reco.requeue(session, sid, now=NOW) == 0


async def test_the_default_list_shows_the_queue_head_and_a_filter_shows_every_card(session, shop):
    seeded, _ = shop
    ids = await _three_on_one_product(session, shop)
    sid = seeded.shop_id
    await service.publish(session, sid, None, now=NOW)
    top = await service.list_cards(session, sid, audience="seller")
    assert [c["id"] for c in top["cards"]] == [str(ids[0])]
    assert top["cards"][0]["product_queue"] == 1 and top["counts"]["queued_behind"] == 2
    every = await service.list_cards(session, sid, audience="seller", product_id="1001")
    assert [c["product_queue"] for c in every["cards"]] == [1, 2, 3]
    assert every["cards"][1]["code"] and len(every["cards"][1]["versions"]) >= 1
    alls = await service.list_cards(session, sid, audience="seller", queue="all")
    assert len(alls["cards"]) == 3
    with pytest.raises(ProposalError):
        await service.list_cards(session, sid, audience="seller", queue="x")


async def test_dismissing_the_head_moves_the_next_card_up(session, shop):
    seeded, _ = shop
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, seeded.shop_id, None, now=NOW)
    assert await _queue(session, ids) == [1, 2, 3]
    await service.decide(
        session,
        seeded.shop_id,
        ids[0],
        decision="dismiss",
        user_id=seeded.user.id,
        now=NOW,
        reason_code="already_done",
    )
    assert await _queue(session, ids) == [None, 1, 2]


async def test_withdrawing_expiring_and_executing_the_head_each_move_the_next_up(session, shop):
    seeded, _ = shop
    sid = seeded.shop_id
    ids = await _three_on_one_product(session, shop)
    await service.withdraw(session, sid, ids[0], now=NOW)  # draft -> withdrawn
    assert await _queue(session, ids) == [None, 1, 2]
    await service.publish(session, sid, [ids[1], ids[2]], now=NOW)
    assert await service.expire_old(session, sid, now=NOW + timedelta(days=8)) == 2
    assert await _queue(session, ids) == [None, None, None]  # both expired


async def test_executing_closes_the_card_for_the_queue_at_once_and_marks_the_product(session, shop):
    seeded, _ = shop
    sid = seeded.shop_id
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, sid, None, now=NOW)
    await service.decide(session, sid, ids[0], decision="approve", user_id=seeded.user.id, now=NOW)
    assert await _queue(session, ids) == [1, 2, 3]
    await service.mark_executed(
        session, sid, ids[0], now=NOW + timedelta(hours=2), user_id=seeded.user.id
    )
    assert await _queue(session, ids) == [None, 1, 2]
    lst_ = await service.list_cards(
        session, sid, audience="ops", product_id="1001", now=NOW + timedelta(days=1)
    )
    open_cards = [c for c in lst_["cards"] if c["status"] in ("sent",)]
    measuring = open_cards[0]["product_measuring"]
    assert measuring["until"] and measuring["change_set"]  # the card's change set (D-7)
    # once the planned window is over the product is no longer measured
    done = await service.list_cards(
        session, sid, audience="ops", product_id="1001", now=NOW + timedelta(days=60)
    )
    assert all(c["product_measuring"] is None for c in done["cards"])


async def test_the_other_filters_still_drop_and_refs_point_at_the_queue_head(session, shop):
    seeded, _ = shop
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, seeded.shop_id, None, now=NOW)
    # make the lowest-queue card the best "answer" otherwise: queue 1 still wins the ref
    index = await reco.refs.load_index(session, seeded.shop_id, audience="seller")
    assert index.for_product("1001")["id"] == str(ids[0])
    assert index.for_product("1001")["product_queue"] == 1
    assert [r["product_queue"] for r in index.all_for_product("1001")] == [1, 2, 3]


async def test_a_version_is_a_full_evaluation_and_a_bad_one_is_kept_marked_not_ranked(
    session, shop
):
    seeded, env = shop
    cand = Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor")
    card = build_card(env, cand, now=NOW)
    vs = versions.build_versions(env, cand, card, now=NOW)
    assert 2 <= len(vs) <= 4 and vs[0]["ranked"] and vs[0]["label"] == versions.DEFAULT_LABEL
    ok = [v for v in vs if v["status"] == "ok"]
    for v in ok:
        assert set(versions.EVAL_FIELDS) <= set(v)
        assert v["five_numbers"] is not None or card["five_numbers"] is None
    assert [v["inputs"]["discount_pct"] for v in vs[:1]] == [15]
    assert len({v["inputs"]["discount_pct"] for v in vs}) == len(vs)
    for v in vs[1:]:
        assert not v["ranked"]
        if v["status"] != "ok":
            assert v["status"] in ("floor_breach", "refused")


async def test_whatif_on_a_version_changes_only_that_version(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cand = Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor")
    cid = await _save(session, sid, env, cand, 1, 1.0)
    await session.commit()
    frozen = (await store.card_payload(session, sid, cid))["versions"]
    assert len(frozen) >= 2
    out = await service.recompute(
        session, sid, cid, {"discount_pct": 5}, now=NOW, version=2, record=True
    )
    assert out["version"] == 2 and out["inputs"]["discount_pct"] == 5
    after = out["versions"]
    assert after[1]["inputs"]["discount_pct"] == 5
    assert after[0] == frozen[0] and after[2:] == frozen[2:]
    ev = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid, CardEvent.event_type == "whatif_adjusted"
            )
        )
    ).all()
    assert ev[0].payload["version"] == 2 and ev[0].payload["code"]
    with pytest.raises(ProposalError) as err:
        await service.recompute(session, sid, cid, {}, now=NOW, version=9)
    assert err.value.status == 422
    # version None is version 1, as before
    base = await service.recompute(session, sid, cid, {"discount_pct": 12}, now=NOW, record=False)
    assert base["version"] == 1 and base["versions"][0]["inputs"]["discount_pct"] == 12


async def test_a_title_whatif_above_100_characters_is_422(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cand = Candidate(
        "title",
        ("1001",),
        {"title": "Túi rác sinh học"},
        extra={"current_title": "Túi rác", "core": ["túi rác sinh học"]},
    )
    card = build_card(env, cand, now=NOW)
    if card is None:
        pytest.skip("no listing for the synthetic shop")
    cid = await store.save_card(session, sid, card, cycle="c", position=1, now=NOW)
    with pytest.raises(ProposalError) as err:
        await service.recompute(session, sid, cid, {"title": "x" * 101}, now=NOW)
    assert err.value.status == 422


async def test_approving_a_chosen_version_records_it_everywhere(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cand = Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor")
    cid = await _save(session, sid, env, cand, 1, 1.0)
    await session.commit()
    payload = await store.card_payload(session, sid, cid)
    good = [v for v in payload["versions"] if v["status"] == "ok" and v["version"] > 1]
    assert good
    n = good[0]["version"]
    await service.publish(session, sid, [cid], now=NOW)
    out = await service.decide(
        session, sid, cid, decision="approve", user_id=seeded.user.id, now=NOW, chosen_version=n
    )
    assert out["chosen_version"] == n and out["code"]
    (acc,) = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == cid, CardEvent.event_type == "accepted")
        )
    ).all()
    assert acc.payload["chosen_version"] == n
    assert acc.payload["chosen_version_code"] == f"{out['code']}-V{n}"
    assert acc.payload["final"]["inputs"] == good[0]["inputs"]
    approval = await session.scalar(
        select(ShopProposalApproval).where(ShopProposalApproval.proposal_id == cid)
    )
    assert approval.proposal_snapshot["chosen_version"] == n
    done = await service.mark_executed(
        session, sid, cid, now=NOW + timedelta(hours=1), user_id=seeded.user.id
    )
    assert done["code"] == out["code"]
    ex = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == cid, CardEvent.event_type == "executed")
        )
    ).all()
    assert ex and all(e.payload["chosen_version"] == n and e.payload["code"] for e in ex)
    detail = await service.card_by_code(session, sid, f"{out['code']}-V{n}")
    assert detail["chosen_version"] == n and detail["selected_version"]["version"] == n
    assert detail["inputs"]["chosen"] == good[0]["inputs"]
    assert detail["inputs"]["approved"] == good[0]["inputs"]
    assert detail["change"]["before"] and detail["change"]["after"]
    assert [h["event"] for h in detail["status_history"]][:3] == [
        "proposed",
        "accepted",
        "executed",
    ]
    assert "state" in detail["verification"]


async def test_an_unavailable_or_unknown_version_cannot_be_approved(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cand = Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor")
    cid = await _save(session, sid, env, cand, 1, 1.0)
    await service.publish(session, sid, [cid], now=NOW)
    with pytest.raises(ProposalError) as err:
        await service.decide(
            session,
            sid,
            cid,
            decision="approve",
            user_id=seeded.user.id,
            now=NOW,
            chosen_version=4
            if len((await store.card_payload(session, sid, cid))["versions"]) < 4
            else 9,
        )
    assert err.value.status == 422
    p = await session.get(ShopProposal, cid)
    assert p.status == "sent"


async def test_codes_are_sequential_per_shop_and_backfill_codes_old_cards_in_order(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    ids = await _three_on_one_product(session, shop)
    rows = [await session.get(ShopProposal, i) for i in ids]
    assert [r.code for r in rows] == ["JC-2610-0001", "JC-2610-0002", "JC-2610-0003"]
    for n, r in enumerate(rows):  # make them look like pre-116 cards
        r.code = None
        r.created_at = NOW - timedelta(days=40 - n)
    await session.flush()
    assert await codes.backfill_codes(session, sid, NOW) == 3
    assert await codes.backfill_codes(session, sid, NOW) == 0
    assert [r.code for r in rows] == ["JC-2608-0004", "JC-2608-0005", "JC-2608-0006"]
    # the next card goes on
    cand = Candidate("product_discount", ("1002",), {"discount_pct": 10}, wiring_key="ctor")
    new = await _save(session, sid, env, cand, 9, 0.1)
    assert (await session.get(ShopProposal, new)).code == "JC-2610-0007"


async def test_a_replacement_card_carries_the_old_code(session, shop):
    seeded, env = shop
    sid = seeded.shop_id
    cand = Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor")
    old = await _save(session, sid, env, cand, 1, 1.0)
    card = build_card(env, cand, now=NOW)
    new = await store.save_card(session, sid, card, cycle="c", position=1, now=NOW, supersedes=old)
    payload = await store.card_payload(session, sid, new)
    assert payload["supersedes_code"] == (await session.get(ShopProposal, old)).code
    assert payload["code"] != payload["supersedes_code"]


async def test_the_seller_view_keeps_internals_out_of_every_version(session, shop):
    seeded, env = shop
    cand = Candidate("product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor")
    card = build_card(env, cand, now=NOW)
    card["versions"] = versions.build_versions(env, cand, card, now=NOW)
    out = service.seller_view(card)
    assert "rank_inputs" not in out
    for v in out["versions"]:
        assert "rank_inputs" not in v
        if "predicted" in v:
            assert "sim" not in v["predicted"] and "model_version" not in v["predicted"]


def test_a_card_made_before_p91_reads_as_one_version():
    old = {"inputs": {"x": 1}, "floor": {"ok": True}, "change": {}, "code": "JC-2610-0001"}
    (v,) = versions.versions_of(old)
    assert v["version"] == 1 and v["code"] == "JC-2610-0001-V1" and v["ranked"]
    assert uuid.UUID(str(uuid.uuid4()))


# ================================================================================== routes


async def test_demo_and_ops_routes_carry_queue_versions_codes_and_chosen_version(
    session, shop, monkeypatch
):
    seeded, env = shop
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, seeded.shop_id, None, now=NOW)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    demo = "/v1/demo/shopee/recommendations"
    async with client_for(app) as client:
        top = (await client.get(demo)).json()
        assert [c["id"] for c in top["cards"]] == [str(ids[0])]
        allp = (await client.get(demo, params={"product_id": "1001"})).json()
        assert [c["product_queue"] for c in allp["cards"]] == [1, 2, 3]
        assert (await client.get(demo, params={"queue": "nope"})).status_code == 422
        detail = (await client.get(f"{demo}/{ids[0]}")).json()
        assert detail["code"] and detail["card"]["code"] == detail["code"]
        assert all("rank_inputs" not in v for v in detail["card"]["versions"])
        wi = await client.post(
            f"{demo}/{ids[0]}/whatif", json={"inputs": {"discount_pct": 5}, "version": 2}
        )
        assert wi.status_code == 200 and wi.json()["card"]["version"] == 2
        bad = await client.post(f"{demo}/{ids[0]}/whatif", json={"inputs": {}, "version": 9})
        assert bad.status_code == 422
        await session.refresh(seeded.shop)
        await session.refresh(seeded.user)
        ok = await client.post(f"{demo}/{ids[0]}/approve", json={"chosen_version": 1})
        assert ok.status_code == 200 and ok.json()["chosen_version"] == 1
    app.dependency_overrides.clear()
    ops_app = await _ops_client(session, monkeypatch, "operator")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/recommendations"
    async with client_for(ops_app) as ops:
        code = ok.json()["code"]
        got = (await ops.get(f"{base}/code/{code}")).json()
        assert got["code"] == code and got["chosen_version"] == 1 and got["versions"]
        assert (await ops.get(f"{base}/code/{code}-V2")).json()["selected_version"]["version"] == 2
        assert (await ops.get(f"{base}/code/JC-2610-9999")).status_code == 404
        assert (await ops.get(f"{base}/code/garbage")).status_code == 404
        assert (await ops.post(f"{base}/requeue")).json() == {"changed": 0}
        assert (await ops.post(f"{base}/backfill-codes")).json() == {"coded": 0}
        every = (await ops.get(base, params={"queue": "all"})).json()
        assert len(every["cards"]) == 3
    ops_app.dependency_overrides.clear()


def test_breaches_cover_floor_and_spend_cap_and_mark_the_version():
    ok = {"floor": {"ok": True, "breaches": []}, "rank_inputs": {}}
    assert versions.breaches_of(ok) == [] and versions.version_of(ok, 2, "x")["status"] == "ok"
    spend = {**ok, "rank_inputs": {"spend_after": 120.0, "spend_cap": 100.0}}
    v = versions.version_of(spend, 2, "x")
    assert v["status"] == versions.STATUS_SPEND and not v["ranked"]
    assert versions.breaches_of(spend)[0]["type"] == "spend_cap"
    floor = {"floor": {"ok": False, "breaches": [{"sku": "S"}]}, "rank_inputs": {}}
    assert versions.version_of(floor, 1, "x")["status"] == versions.STATUS_FLOOR
    assert not versions.version_of(floor, 1, "x")["ranked"]


# ============================================================ "Gỡ thẻ" (Ops withdraw, reasons)


async def test_withdraw_keeps_the_reason_and_the_next_card_moves_up(session, shop):
    seeded, _ = shop
    sid = seeded.shop_id
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, sid, None, now=NOW)
    await service.withdraw(session, sid, ids[0], now=NOW, reason_code="duplicate", note="trùng V2")
    await session.commit()
    p = await session.get(ShopProposal, ids[0])
    assert p.status == "withdrawn"
    assert await _queue(session, ids) == [None, 1, 2]
    meta = await store.card_meta(session, sid, ids[0])
    assert (
        meta["withdrawn"]["reason_code"] == "duplicate" and meta["withdrawn"]["note"] == "trùng V2"
    )
    with pytest.raises(ProposalError) as bad:
        await service.withdraw(session, sid, ids[1], now=NOW, reason_code="nope")
    assert bad.value.status == 422


async def test_withdraw_takes_a_planned_card_out_of_its_draft_plan(session, shop):
    from juli_backend.services.shopee_recommendations import manual, plans

    seeded, _ = shop
    sid = seeded.shop_id
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, sid, None, now=NOW)
    actor = manual.Actor("seller", seeded.user.id)
    await plans.add_card(session, sid, ids[0], actor=actor, now=NOW)
    await session.commit()
    assert (await session.get(ShopProposal, ids[0])).status == "planned"
    await service.withdraw(session, sid, ids[0], now=NOW, reason_code="done_outside")
    await session.commit()
    p = await session.get(ShopProposal, ids[0])
    assert p.status == "withdrawn" and p.lever_plan_id is None
    plan = await plans.draft_of(session, sid)
    assert plan is not None and await plans._rows(session, sid, plan.id) == []
    assert await _queue(session, ids) == [None, 1, 2]


async def test_the_seller_can_still_dismiss_a_card_sent_back_for_a_change(session, shop):
    seeded, _ = shop
    sid = seeded.shop_id
    ids = await _three_on_one_product(session, shop)
    await service.publish(session, sid, None, now=NOW)
    await service.decide(
        session, sid, ids[0], decision="request_change", user_id=seeded.user.id, now=NOW,
        note="đổi giá",
    )  # fmt: skip
    assert (await session.get(ShopProposal, ids[0])).status == "changes_requested"
    await service.decide(
        session, sid, ids[0], decision="dismiss", user_id=seeded.user.id, now=NOW,
        reason_code="later",
    )  # fmt: skip
    assert (await session.get(ShopProposal, ids[0])).status == "rejected"
    assert await _queue(session, ids) == [None, 1, 2]
