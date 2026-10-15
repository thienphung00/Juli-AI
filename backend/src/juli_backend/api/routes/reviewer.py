"""Partner reviewer routes (fast track P32-A, D42; contract p32-reviewer-access.md §4, §6).

- ``GET /v1/reviewer/me`` -- who is signed in: a reviewer gets its platform,
  expiry and the (aliased) reference shop, or ``shop: null`` when no shop is
  pinned (the UI then shows the sample shop); anyone else ``{"reviewer": false}``.
- ``POST /v1/reviewer/decisions/{id}/simulate`` -- the simulated Duyệt / Thực
  thi. Reads the card exactly as ``GET /v1/demo/decisions/{id}`` does, writes
  ONLY the audit row: no run, no card change, no queue, no TikTok client.

Both responses pass through the reviewer mask (``api/reviewer.py``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.reviewer import enter_reviewer_shop, reviewer_context
from juli_backend.api.routes.demo_decisions import DemoDecisionItem
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import shop_rules
from juli_backend.services.demo_decisions import (
    DecisionNotFound,
    get_surfaced_decision,
    load_card_contexts,
    mask_decision_payload,
)
from juli_backend.services.ops import audit
from juli_backend.services.reviewer import simulation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviewer", tags=["reviewer"])


@router.get("/me")
async def reviewer_me(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    context = reviewer_context(request)
    if context is None:
        return {"reviewer": False}
    shop_body: dict[str, str] | None = None
    if context.shop_id is not None:
        shop = await enter_reviewer_shop(session, context, None)
        shop_body = {"id": str(shop.id), "name": shop.shop_name}
    return {
        "reviewer": True,
        "platform": context.platform,
        "expires_at": context.account.expires_at.isoformat() + "Z",
        # None: no pinned shop (D42 amendment) -- the UI shows the sample shop.
        "shop": shop_body,
    }


class SimulateRequest(BaseModel):
    step: Literal["approve", "execute"]


@router.post("/decisions/{action_card_id}/simulate")
async def simulate_decision(
    action_card_id: uuid.UUID,
    body: SimulateRequest,
    request: Request,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    context = reviewer_context(request)
    if context is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer only")
    try:
        card = await get_surfaced_decision(session, shop.id, action_card_id)
    except DecisionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found"
        ) from None
    allowed_levers = await shop_rules.auto_levers(session, shop.id)
    contexts = await load_card_contexts(session, shop.id, [card])
    item = DemoDecisionItem(
        **mask_decision_payload(
            card, allowed_levers=allowed_levers, card_context=contexts.get(card.id)
        )
    ).model_dump(mode="json")
    result = simulation.simulate(item, body.step)
    action = (
        audit.ACTION_REVIEWER_SIMULATED_APPROVE
        if body.step == "approve"
        else audit.ACTION_REVIEWER_SIMULATED_EXECUTE
    )
    # The read above ran in the shop's tenant scope; the audit row is the only write.
    await audit.record(
        session,
        context.account.actor,
        action,
        shop_id=shop.id,
        after={
            "platform": context.platform,
            "action_card_id": str(action_card_id),
            "lever": result["change"]["lever"]["code"],
            "request": result["change"]["request"],
        },
    )
    await session.commit()
    logger.info(
        "reviewer_simulated",
        extra={"platform": context.platform, "step": body.step, "card": str(action_card_id)},
    )
    return result
