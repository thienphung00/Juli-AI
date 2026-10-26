"""Partner reviewer routes (fast track P32-A, D42; contract p32-reviewer-access.md §4, §6).

- ``GET /v1/reviewer/me`` -- who is signed in: a reviewer gets its platform,
  expiry and the (aliased) reference shop, or ``shop: null`` when no shop is
  pinned (the UI then shows the sample shop); anyone else ``{"reviewer": false}``.
- ``POST /v1/reviewer/decisions/{id}/simulate`` -- the simulated Duyệt / Thực
  thi. Reads the card exactly as ``GET /v1/demo/decisions/{id}`` does, writes
  ONLY the audit row: no run, no card change, no queue, no TikTok client.

Fast track P64 (D73), the live sandbox mode -- only when ``REVIEWER_SHOP_ID`` pins
Juli's own TikTok Shop sandbox shop (``services/reviewer/sandbox.classify_pin``);
on any other pin each answers 403 ``sandbox_only``:

- ``GET /v1/reviewer/shop`` -- the shop, its TikTok connection and the last
  successful sync ("synced at").
- ``POST /v1/reviewer/shop/sync`` -- "Đồng bộ ngay": enqueues ``poll_shop`` for the
  pinned shop, at most once per 60 s (429 + ``Retry-After`` otherwise).

D73.4 (2026-10-22) retired the synchronous ``…/approve`` / ``…/execute`` pair: on the
sandbox pin the reviewer's Duyệt is the seller's own ``POST /v1/demo/decisions/{id}/approve``
(an agent run, streamed over SSE, confirmed like a seller's -- ``api/reviewer.py``
``SANDBOX_RUN_ENDPOINTS``).

The simulation answers 403 ``sandbox_live`` on a live sandbox pin.

Every response passes through the reviewer mask (``api/reviewer.py``), which is
off for the sandbox shop (D73 Q1/Q2).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.reviewer import (
    deny,
    enter_reviewer_shop,
    require_sandbox_pin,
    reviewer_context,
)
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
from juli_backend.services.reviewer import sandbox, simulation

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
    mode: str | None = None
    writes_enabled = False
    if context.shop_id is not None:
        shop = await enter_reviewer_shop(session, context, None)
        shop_body = {"id": str(shop.id), "name": shop.shop_name}
        if context.pin is not None:
            mode, writes_enabled = context.pin.mode, context.pin.writes_enabled
    return {
        "reviewer": True,
        "platform": context.platform,
        "expires_at": context.account.expires_at.isoformat() + "Z",
        # None: no pinned shop (D42 amendment) -- the UI shows the sample shop.
        "shop": shop_body,
        # P64 (D73): "sandbox" (live, unmasked) | "masked" (P32 read-only) | None (no pin).
        "mode": mode,
        "writes_enabled": writes_enabled,
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
    if context.pin is not None and context.pin.sandbox:
        # P64 (D73 Q5): on the live sandbox the real Duyệt / Thực thi replace the simulation.
        raise deny("sandbox_live")
    item = await _card_item(session, shop, action_card_id)
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


async def _card_item(
    session: AsyncSession, shop: Shop, action_card_id: uuid.UUID
) -> dict[str, Any]:
    """The surfaced card exactly as ``GET /v1/demo/decisions/{id}`` serves it (404 otherwise)."""
    try:
        card = await get_surfaced_decision(session, shop.id, action_card_id)
    except DecisionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found"
        ) from None
    allowed_levers = await shop_rules.auto_levers(session, shop.id)
    contexts = await load_card_contexts(session, shop.id, [card])
    return DemoDecisionItem(
        **mask_decision_payload(
            card, allowed_levers=allowed_levers, card_context=contexts.get(card.id)
        )
    ).model_dump(mode="json")


# -- P64 (D73): the live sandbox -----------------------------------------------------------


def _shop_body(shop: Shop) -> dict[str, Any]:
    """The pinned shop for the connection card (P64, D73.3).

    ``shops.tiktok_shop_id`` holds TikTok's internal cipher / open id, not a code a
    person recognises, so it is never returned. ``tiktok_shop_code`` is TikTok's
    seller-facing shop code (``GET /authorization/202309/shops`` -> ``code``); no
    column caches it yet (a migration is needed), so it is ``None`` and the card
    hides the row.
    """
    return {
        "id": str(shop.id),
        "name": shop.shop_name,
        "tiktok_shop_code": None,
        "platform": getattr(shop, "platform", "tiktok"),
    }


@router.get("/shop")
async def reviewer_shop(
    request: Request,
    x_shop_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """The sandbox shop, its TikTok connection and when it last synced (no token, no merchant)."""
    shop = await require_sandbox_pin(session, reviewer_context(request), x_shop_id)
    info = await sandbox.connection_info(session, shop.id)
    return {
        "shop": _shop_body(shop),
        "mode": sandbox.MODE_SANDBOX,
        "writes_enabled": True,
        "connection": info["connection"],
        "synced_at": info["synced_at"],
        "sync_endpoints": info["endpoints"],
        "sync_interval_seconds": int(sandbox.SYNC_INTERVAL_SECONDS),
    }


def _enqueue_poll_shop(shop_id: uuid.UUID) -> str:
    """Imported lazily so the Celery app is not a route import (like ``agent_runs``)."""
    from juli_backend.workers.tasks import shop_ingestion as shop_ingestion_tasks

    return shop_ingestion_tasks.enqueue_poll_shop(str(shop_id), force_commerce=True)


@router.post("/shop/sync", status_code=status.HTTP_202_ACCEPTED)
async def reviewer_sync_shop(
    request: Request,
    x_shop_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """ "Đồng bộ ngay": one ``poll_shop`` for the pinned sandbox shop, at most once per 60 s."""
    context = reviewer_context(request)
    shop = await require_sandbox_pin(session, context, x_shop_id)
    assert context is not None  # require_sandbox_pin refused a seller session
    wait = sandbox.claim_sync_slot(shop.id)
    if wait > 0:
        retry_after = max(1, int(wait + 0.999))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "sync_rate_limited", "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    try:
        task_id = _enqueue_poll_shop(shop.id)
    except Exception:
        sandbox.release_sync_slot(shop.id)
        logger.error("reviewer_sync_enqueue_failed", extra={"shop_id": str(shop.id)}, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "sync_unavailable"},
        ) from None
    await audit.record(
        session,
        context.account.actor,
        audit.ACTION_REVIEWER_SANDBOX_SYNC,
        shop_id=shop.id,
        after={"platform": context.platform, "task_id": task_id},
    )
    await session.commit()
    info = await sandbox.connection_info(session, shop.id)
    return {
        "queued": True,
        "task_id": task_id,
        "synced_at": info["synced_at"],
        "retry_after_seconds": int(sandbox.SYNC_INTERVAL_SECONDS),
    }
