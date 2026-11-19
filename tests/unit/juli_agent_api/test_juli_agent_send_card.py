"""Gửi on an engine card goes through the real Tự tạo path (``manual.create_manual``).

On a seeded Shopee shop (synthetic): the card gets a JC code, ``origin = "agent"``, the seller as
its creator, the chosen version first, and lands in Đề xuất already sent -- the same state a
seller's "Tự tạo: Chọn" card is in.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from juli_backend.models.agent_chat import AgentCardDraft, AgentConversation, AgentMessage
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.juli_agent_api import send_card
from juli_backend.services.shopee_recommendations import manual, store
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.juli_agent_api.fakes import draft_card

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 8, 3, 0)


async def _seed_draft(session, shop_id, user_id) -> str:
    conv = AgentConversation(
        id=uuid.uuid4(),
        shop_id=shop_id,
        platform="shopee",
        title="t",
        created_at=NOW,
        updated_at=NOW,
    )
    msg = AgentMessage(
        id=uuid.uuid4(),
        shop_id=shop_id,
        conversation_id=conv.id,
        role="assistant",
        events=[],
        status="done",
        created_at=NOW,
        updated_at=NOW,
    )
    ref = f"d_{uuid.uuid4().hex[:12]}"
    draft = AgentCardDraft(
        id=uuid.uuid4(),
        shop_id=shop_id,
        message_id=msg.id,
        draft_ref=ref,
        card=draft_card(ref),
        status="drafted",
        created_at=NOW,
    )
    session.add_all([conv, msg])
    await session.flush()
    session.add(draft)
    await session.commit()
    return ref


async def test_send_saves_an_agent_card_with_a_jc_code_in_de_xuat(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    shop_id, user_id = seeded.shop_id, seeded.user.id
    ref = await _seed_draft(session, shop_id, user_id)

    out = await send_card(
        session,
        shop_id=shop_id,
        user_id=user_id,
        draft_ref=ref,
        version_label="Giảm 5%",
        now=NOW,
        acknowledge_breaches=True,
    )
    await session.commit()

    assert out["card_code"].startswith("JC-") and out["already_sent"] is False
    proposal = await session.get(ShopProposal, uuid.UUID(out["card_id"]))
    assert proposal.code == out["card_code"]
    # the seller's own card is sent at once: the same status a "Tự tạo: Chọn" card has
    seller_card = await manual.create_manual(
        session,
        shop_id,
        [{"change_kind": "product_discount", "items": ["1001"], "inputs": {"discount_pct": 5}}],
        0,
        False,
        manual.Actor("seller", user_id),
        now=NOW,
        acknowledge_breaches=True,
    )
    assert out["status"] == seller_card["status"] == proposal.status
    card = await store.card_payload(session, shop_id, proposal.id)
    assert card["origin"] == "agent" and card["created_by"] == {
        "type": "seller",
        "id": str(user_id),
    }
    assert card["agent_draft_ref"] == ref
    assert card["versions"][0]["chosen"] and card["versions"][0]["inputs"]["discount_pct"] == 5
    draft = (await session.scalars(select(AgentCardDraft))).one()
    assert (draft.status, draft.card_code) == ("sent", out["card_code"])
