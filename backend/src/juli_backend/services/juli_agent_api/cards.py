"""Gửi / Bỏ qua on an engine card: send it through the Tự tạo path, or log the dismissal.

Send creates the card exactly as "Tự tạo phương án: Chọn" does --
``shopee_recommendations.manual.create_manual`` with ``origin="agent"`` and a ``seller`` actor --
so it gets its JC code, lands in Đề xuất already sent, and approve / "Đã làm" / measurement run
unchanged. The chosen version is the one whose ``label_vi`` the seller picked; the others are the
card's other versions.

The draft (``agent_card_drafts.card``) is T1's ``AnswerResult.cards[i]``: ``{draft_ref, kind,
item_id, recommended, engine_card}``, the engine card built by the recommendation engine
(``analytics_agent.cards_service``) with its versions and their stored results. Each version
becomes one Tự tạo variant ``{label, change_kind: kind, items: [item_id], inputs}``; the
builder's own validation refuses a kind it cannot save (422 ``juli_card_refused``). The saved
card's numbers are computed by the same engine on the shop's current window, exactly as Tự tạo
saves them (``create_manual`` keeps no number from outside the engine).

Send is idempotent: a draft already sent answers its card code again. Dismissal writes the
draft's status and one log line, nothing else.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.agent_chat import (
    DRAFT_DISMISSED,
    DRAFT_DRAFTED,
    DRAFT_SENT,
    AgentCardDraft,
)
from juli_backend.services.juli_agent_api.chat import ERROR_NOT_FOUND, ChatError

logger = logging.getLogger(__name__)

ORIGIN_AGENT = "agent"
ERROR_DRAFT_DISMISSED = "juli_draft_dismissed"
ERROR_DRAFT_ALREADY_SENT = "juli_draft_already_sent"
ERROR_UNKNOWN_VERSION = "juli_unknown_version"
ERROR_NOT_SENDABLE = "juli_draft_not_sendable"
ERROR_CARD_REFUSED = "juli_card_refused"

#: ``(session, shop_id, variants, chosen, user_id, *, now, cards, draft_ref,
#: acknowledge_breaches) -> create_manual's result``
CardCreator = Callable[..., Awaitable[dict[str, Any]]]


async def create_via_manual(
    session: AsyncSession,
    shop_id: uuid.UUID,
    variants: Sequence[Mapping[str, Any]],
    chosen: int,
    user_id: uuid.UUID,
    *,
    now: datetime,
    cards: Sequence[dict[str, Any]] | None,
    draft_ref: str,
    acknowledge_breaches: bool = False,
) -> dict[str, Any]:
    """The Tự tạo path (``manual.create_manual``), origin ``agent``, a seller's card."""
    from juli_backend.services.shop_proposals import ProposalError
    from juli_backend.services.shopee_recommendations import manual

    try:
        return await manual.create_manual(
            session,
            shop_id,
            variants,
            chosen,
            False,
            manual.Actor("seller", user_id),
            now=now,
            cards=cards,
            acknowledge_breaches=acknowledge_breaches,
            origin=ORIGIN_AGENT,
            card_extra={"agent_draft_ref": draft_ref},
        )
    except manual.BreachNotAcknowledged as exc:
        raise ChatError(
            ERROR_CARD_REFUSED, 422, "the version breaks a shop rule", breaches=exc.breaches
        ) from None
    except ProposalError as exc:
        raise ChatError(ERROR_CARD_REFUSED, exc.status, exc.detail or exc.code) from None


async def _draft(session: AsyncSession, shop_id: uuid.UUID, draft_ref: str) -> AgentCardDraft:
    # FOR UPDATE: two concurrent sends of one draft queue here; the second reads it "sent" and
    # answers ``already_sent`` (populate_existing: never a stale copy from the identity map)
    row = await session.scalar(
        select(AgentCardDraft)
        .where(AgentCardDraft.shop_id == shop_id, AgentCardDraft.draft_ref == draft_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise ChatError(ERROR_NOT_FOUND, 404, "card not found")
    return row


def _variants(draft: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The Tự tạo variants of an engine card (``AnswerResult.cards[i]``, T1): one per version,
    ``{label, change_kind, items, inputs}`` -- the same shape the builder's "Chọn" saves."""
    card = draft.get("engine_card")
    if not isinstance(card, Mapping):
        raise ChatError(ERROR_NOT_SENDABLE, 422, "this card has no engine card")
    kind = str(draft.get("kind") or card.get("kind") or "")
    versions = [v for v in card.get("versions") or [] if isinstance(v, Mapping)]
    if not kind or not versions:
        raise ChatError(ERROR_NOT_SENDABLE, 422, "this card cannot be sent from Juli")
    item = draft.get("item_id")
    return [
        {
            "label": v.get("label"),
            "change_kind": kind,
            "items": [str(item)] if item else [],
            "inputs": dict(v.get("inputs") or {}),
        }
        for v in versions
    ]


async def send_card(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    draft_ref: str,
    version_label: str | None,
    now: datetime,
    acknowledge_breaches: bool = False,
    create: CardCreator = create_via_manual,
) -> dict[str, Any]:
    """Create the card; returns ``{card_code, card_id, status, already_sent}``. Never commits."""
    draft = await _draft(session, shop_id, draft_ref)
    if draft.status == DRAFT_SENT:
        return {
            "card_code": draft.card_code,
            "card_id": str(draft.proposal_id) if draft.proposal_id else None,
            "status": DRAFT_SENT,
            "already_sent": True,
        }
    if draft.status == DRAFT_DISMISSED:
        raise ChatError(ERROR_DRAFT_DISMISSED, 409, "this card was dismissed")
    variants = _variants(draft.card)
    labels = [v.get("label") for v in variants]
    if version_label is None:
        recommended = draft.card.get("recommended")
        chosen = labels.index(recommended) if recommended in labels else 0
    elif version_label in labels:
        chosen = labels.index(version_label)
    else:
        raise ChatError(ERROR_UNKNOWN_VERSION, 422, "unknown version")
    out = await create(
        session,
        shop_id,
        variants,
        chosen,
        user_id,
        now=now,
        cards=None,
        draft_ref=draft_ref,
        acknowledge_breaches=acknowledge_breaches,
    )
    draft.status = DRAFT_SENT
    draft.card_code = out.get("code")
    draft.proposal_id = uuid.UUID(str(out["id"])) if out.get("id") else None
    draft.version_label = labels[chosen]
    draft.decided_by_user_id = user_id
    draft.decided_at = now
    logger.info(
        "juli_agent_card_sent",
        extra={"shop_id": str(shop_id), "draft_ref": draft_ref, "card_code": draft.card_code},
    )
    return {
        "card_code": draft.card_code,
        "card_id": str(draft.proposal_id) if draft.proposal_id else None,
        "status": out.get("status"),
        "already_sent": False,
    }


async def dismiss_card(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    draft_ref: str,
    now: datetime,
) -> dict[str, Any]:
    """Log "Bỏ qua". A sent card stays sent (409); a second dismissal is a no-op."""
    draft = await _draft(session, shop_id, draft_ref)
    if draft.status == DRAFT_SENT:
        raise ChatError(ERROR_DRAFT_ALREADY_SENT, 409, "this card was already sent")
    if draft.status == DRAFT_DRAFTED:
        draft.status = DRAFT_DISMISSED
        draft.decided_by_user_id = user_id
        draft.decided_at = now
        logger.info(
            "juli_agent_card_dismissed", extra={"shop_id": str(shop_id), "draft_ref": draft_ref}
        )
    return {"status": DRAFT_DISMISSED}


__all__ = [
    "ERROR_CARD_REFUSED",
    "ERROR_DRAFT_ALREADY_SENT",
    "ERROR_DRAFT_DISMISSED",
    "ERROR_NOT_SENDABLE",
    "ERROR_UNKNOWN_VERSION",
    "ORIGIN_AGENT",
    "CardCreator",
    "create_via_manual",
    "dismiss_card",
    "send_card",
]
