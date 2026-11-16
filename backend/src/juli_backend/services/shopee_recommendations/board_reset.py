"""The owner's "reset the Thực hiện board" (owner decision 2026-11-16).

The shop's owner synchronises the board with work done outside Juli: every OPEN card of the shop
leaves the board as ``withdrawn`` with ``reason_code = "reset"``. Open = draft, sent,
changes_requested, approved, planned, and executed cards whose Đo lường window has not closed
(their change set still measuring and no final reading yet). Measured / closed cards, rejected,
superseded and already withdrawn cards stay as they are.

- History is kept: no card event is deleted; the reset is on the card (``withdrawn`` meta).
- A reset executed card leaves its running change set (``change_sets.drop_card``) and its
  observations are filtered out of the shop's calibration (``measure.run_learning``), so it never
  feeds the shop's learning nor the pooled store built from it.
- AuthZ here, not only in the route: the shop's owner or an owner of its business; never a
  reviewer session and never the sample shop (:func:`require_owner`).

Nothing commits (the route does).
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import EVENT_IMPACT_FINAL, CardEvent
from juli_backend.models.models import Shop
from juli_backend.models.shop_proposals import STATUS_EXECUTED, STATUS_PLANNED
from juli_backend.services import businesses
from juli_backend.services.shop_proposals.cycle import REASON_RESET, ProposalError
from juli_backend.services.shopee_recommendations import service, store

ERROR_OWNER_ONLY = "board_owner_only"
ERROR_REVIEWER = "board_reviewer_refused"
SAMPLE_KIND = "sample"
#: statuses a reset takes off the board (an executed one only while its window is open)
RESET_STATUSES: tuple[str, ...] = (*service.OPEN_STATUSES, STATUS_PLANNED, STATUS_EXECUTED)


async def require_owner(
    session: AsyncSession, shop: Shop, user_id: uuid.UUID, *, reviewer: bool
) -> None:
    """403 unless ``user_id`` owns the shop (or its business); always 403 for a reviewer session
    and for the reviewer's sample shop."""
    if reviewer or shop.kind == SAMPLE_KIND:
        raise ProposalError(ERROR_REVIEWER, 403, "not available in the reviewer session")
    if not await businesses.owns_shop(session, shop, user_id):
        raise ProposalError(ERROR_OWNER_ONLY, 403, "only the shop's owner may do this")


async def _final_read(session: AsyncSession, shop_id: uuid.UUID, ids: list[uuid.UUID]) -> set[str]:
    if not ids:
        return set()
    rows = await session.scalars(
        select(CardEvent.card_id).where(
            CardEvent.shop_id == shop_id,
            CardEvent.event_type == EVENT_IMPACT_FINAL,
            CardEvent.card_id.in_(ids),
        )
    )
    return {str(c) for c in rows}


async def open_cards(session: AsyncSession, shop_id: uuid.UUID) -> list[Any]:
    """The proposals a reset takes off the board (see the module docstring)."""
    rows = [p for p, _ in await store.list_cards(session, shop_id, statuses=list(RESET_STATUSES))]
    executed = [p.id for p in rows if p.status == STATUS_EXECUTED]
    states = await service.measurement_states(session, shop_id, executed)
    finals = await _final_read(session, shop_id, executed)
    out = []
    for p in rows:
        if p.status == STATUS_EXECUTED:
            state = states.get(str(p.id))
            if (state is not None and state["window_closed"]) or str(p.id) in finals:
                continue
        out.append(p)
    return out


async def reset_board(
    session: AsyncSession,
    shop: Shop,
    *,
    user_id: uuid.UUID,
    reviewer: bool,
    now: datetime,
    note: str | None = None,
) -> dict[str, Any]:
    """Withdraw every open card of ``shop`` with reason ``reset``. Idempotent: a second reset
    finds nothing open. Returns ``{withdrawn, by_status, card_ids, codes}``."""
    await require_owner(session, shop, user_id, reviewer=reviewer)
    now = now.replace(tzinfo=None)
    cards = await open_cards(session, shop.id)
    by_status: Counter[str] = Counter()
    ids: list[str] = []
    codes: list[str] = []
    for p in cards:
        by_status[p.status] += 1
        await service.withdraw(
            session,
            shop.id,
            p.id,
            now=now,
            reason_code=REASON_RESET,
            note=note,
            by=f"user:{user_id}",
        )
        ids.append(str(p.id))
        if p.code:
            codes.append(p.code)
    await service.requeue(session, shop.id, now=now)
    return {
        "withdrawn": len(ids),
        "by_status": dict(by_status),
        "card_ids": ids,
        "codes": codes,
        "reason_code": REASON_RESET,
        "at": now.isoformat(),
    }


__all__ = [
    "ERROR_OWNER_ONLY",
    "ERROR_REVIEWER",
    "RESET_STATUSES",
    "open_cards",
    "require_owner",
    "reset_board",
]
