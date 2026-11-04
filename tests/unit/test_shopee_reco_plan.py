"""P91 wave 1b: manual-card integration with the queue, origin in events (A), then the draft plan,
the joint aggregate, change sets and the measurement window (D-6, D-7, D-8). SQLite; synthetic."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_recommendations import learning, manual, service, store
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_reco_manual import _combo, _discount

NOW = datetime(2026, 10, 8, 3, 0)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    return seeded, env


def _actor(seeded):
    return manual.Actor("seller", seeded.user.id)


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
