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


async def test_the_seller_edits_an_agent_card_in_de_xuat_and_approves_their_own_value(session):
    """Owner question 2026-11-20: the agent drafts a discount; the seller finds it too low, sets
    another value in Đề xuất and approves it. An agent card is an ordinary Đề xuất card: the
    what-if recompute and the approve-with-inputs path take the seller's value."""
    from juli_backend.services import shopee_recommendations as reco

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
    card_id = uuid.UUID(out["card_id"])

    # the seller changes the agent's 5 % to 12 % (what-if recomputes the whole card)
    adjusted = await reco.recompute(session, shop_id, card_id, {"discount_pct": 12}, now=NOW)
    await session.commit()
    assert adjusted["origin"] == "agent"
    chosen = (
        next(v for v in adjusted["versions"] if v.get("chosen"))
        if any(v.get("chosen") for v in adjusted["versions"])
        else adjusted["versions"][0]
    )
    assert chosen["inputs"]["discount_pct"] == 12

    # and approves it with that value
    decided = await reco.decide(
        session,
        shop_id,
        card_id,
        decision="approve",
        user_id=user_id,
        now=NOW,
        inputs={"discount_pct": 12},
        acknowledge_breaches=True,
    )
    await session.commit()
    card = await store.card_payload(session, shop_id, card_id)
    assert card["origin"] == "agent"
    assert decided is not None
    # the approval snapshot is what Thực hiện executes: it carries the seller's 12 %
    from juli_backend.models.shop_proposals import ShopProposalApproval

    approval = await session.get(ShopProposalApproval, uuid.UUID(decided["approval_id"]))
    snap = approval.proposal_snapshot
    snap_text = str(snap)
    assert decided["status"] == "approved"
    assert "'discount_pct': 12" in snap_text, snap_text[:600]
    proposal = await session.get(ShopProposal, card_id)
    assert proposal.status != "drafted"
