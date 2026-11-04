"""p91 D-3 on real Postgres, as ``juli_app`` under RLS: a manual card (``origin = "manual"``,
``created_by``, versions chosen-first) is saved through the existing ``store.save_card``, is
private to its shop, and goes through approve -> "Đã làm" with the existing service functions.
Synthetic tenants and figures only."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.card_events import CardEvent
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import manual, store
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_reco_db import stub_card
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 4, 3, 0)


def _variants():
    return [
        {"label": "A", "change_kind": "gift", "items": ["5005"], "extra": {}, "inputs": {}},
        {"label": "B", "change_kind": "gift", "items": ["5005"], "extra": {}, "inputs": {}},
    ]


async def test_a_manual_card_is_saved_private_and_runs_approve_then_done(shopee_tenants):
    a, b = shopee_tenants
    cards = [stub_card("5005", "gift", "combo"), stub_card("5005", "gift", "combo")]
    cards[1]["title"] = "Thẻ B"
    actor = manual.Actor("seller", a.user_id)
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            out = await manual.create_manual(
                session, a.shop_id, _variants(), 1, True, actor, now=NOW, cards=cards
            )
            await session.commit()
        cid = out["id"]
        assert out["origin"] == "manual" and out["status"] == "sent" and out["position"] == 1
        assert [v["index"] for v in out["versions"]] == [1, 0]
        async with with_shop_scope(session, a.shop_id):
            payload = await store.card_payload(session, a.shop_id, uuid.UUID(cid))
            assert payload["origin"] == "manual" and payload["title"] == "Thẻ B"
            assert payload["created_by"] == {"type": "seller", "id": str(a.user_id)}
            assert [v["chosen"] for v in payload["versions"]] == [True, False]
            assert (await store.card_meta(session, a.shop_id, uuid.UUID(cid)))["origin"] == "manual"
            rows = [r for r in await store.list_cards(session, a.shop_id) if str(r[0].id) == cid]
            assert len(rows) == 1 and rows[0][0].status == "sent"
        async with with_shop_scope(session, b.shop_id):  # another tenant never sees it
            assert [
                r for r in await store.list_cards(session, b.shop_id) if str(r[0].id) == cid
            ] == []
        async with with_shop_scope(session, a.shop_id):
            card_id = uuid.UUID(cid)
            ok = await reco.decide(
                session, a.shop_id, card_id, decision="approve", user_id=a.user_id, now=NOW
            )
            assert ok["status"] == "approved"
            done = await reco.mark_executed(
                session,
                a.shop_id,
                card_id,
                now=NOW + timedelta(hours=1),
                executed_at=NOW + timedelta(hours=1),
                user_id=a.user_id,
            )
            assert done["events"] == 1
            await session.commit()
        async with with_shop_scope(session, a.shop_id):
            types = [
                e.event_type
                for e in (
                    await session.scalars(
                        select(CardEvent)
                        .where(CardEvent.card_id == card_id)
                        .order_by(CardEvent.occurred_at)
                    )
                ).all()
            ]
            assert types == ["proposed", "accepted", "executed"]
            assert (await session.get(ShopProposal, card_id)).status == "executed"


async def test_a_staff_manual_card_stays_a_draft_until_ops_publishes(shopee_tenants):
    a, _ = shopee_tenants
    staff_id = uuid.uuid4()
    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            out = await manual.create_manual(
                session,
                a.shop_id,
                _variants()[:1],
                0,
                False,
                manual.Actor("staff", staff_id),
                now=NOW,
                cards=[stub_card("5006", "gift", "combo")],
            )
            assert out["status"] == "draft" and out["position"] == manual.DEFAULT_MANUAL_POSITION
            assert out["card"]["primary"] is False
            sent = await reco.publish(session, a.shop_id, [uuid.UUID(out["id"])], now=NOW)
            assert sent == [out["id"]]
            await session.commit()
