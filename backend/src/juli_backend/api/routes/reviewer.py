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
- ``POST /v1/reviewer/decisions/{id}/approve`` -- Duyệt: the change Juli will send,
  audited; nothing written yet.
- ``POST /v1/reviewer/decisions/{id}/execute`` -- Thực thi: the listing edit (title /
  description) and/or cover image, REALLY written to the sandbox shop through
  ``SandboxWriteClientFactory`` only, then read back from TikTok.

The simulation answers 403 ``sandbox_live`` on a live sandbox pin.

Every response passes through the reviewer mask (``api/reviewer.py``), which is
off for the sandbox shop (D73 Q1/Q2).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
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
from juli_backend.integrations.tiktok import TikTokAPIError
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

    return shop_ingestion_tasks.enqueue_poll_shop(str(shop_id))


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


_LIVE_EXECUTORS = ("juli", "juli_with_photo")
#: Base64 of an image up to ~5 MB (the screening re-checks the decoded size).
_MAX_IMAGE_BASE64 = 7_000_000


def _plan(item: dict[str, Any]) -> dict[str, Any]:
    """The change Juli will send for this card (the simulation's ``change``, live labels)."""
    change = simulation.simulate(item, "execute")["change"]
    change.pop("note", None)
    return change


@router.post("/decisions/{action_card_id}/approve")
async def approve_decision(
    action_card_id: uuid.UUID,
    request: Request,
    x_shop_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Duyệt on the sandbox: the planned write, audited. Nothing reaches TikTok yet."""
    context = reviewer_context(request)
    shop = await require_sandbox_pin(session, context, x_shop_id)
    assert context is not None
    item = await _card_item(session, shop, action_card_id)
    change = _plan(item)
    executable = change["executor"] in _LIVE_EXECUTORS
    await audit.record(
        session,
        context.account.actor,
        audit.ACTION_REVIEWER_SANDBOX_APPROVE,
        shop_id=shop.id,
        after={
            "platform": context.platform,
            "action_card_id": str(action_card_id),
            "lever": change["lever"]["code"],
            "request": change["request"],
        },
    )
    await session.commit()
    return {
        "simulated": False,
        "step": "approve",
        "action_card_id": str(action_card_id),
        "steps": [
            {"key": "approve", "label": "Duyệt", "done": True},
            {"key": "execute", "label": "Thực thi", "done": False},
        ],
        "change": change,
        "executable": executable,
        "requires_image": change["executor"] == "juli_with_photo",
    }


class ExecuteRequest(BaseModel):
    """What to write. Omitted text fields fall back to the card's stored proposal."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=10_000)
    #: The cover image (``cover_image`` cards), base64; screened and re-encoded server side.
    image_base64: str | None = Field(default=None, max_length=_MAX_IMAGE_BASE64)


def _proposal(change: dict[str, Any], field: str) -> str | None:
    for item in change.get("fields") or []:
        after = item.get("after")
        # The simulation's "Sau" placeholder is not a proposal (no stored draft yet).
        if item.get("field") == field and after and after != simulation.NOTE_DRAFT_AFTER_APPROVAL:
            return str(after)
    return None


def _unprocessable(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": code})


@router.post("/decisions/{action_card_id}/execute")
async def execute_decision(
    action_card_id: uuid.UUID,
    body: ExecuteRequest,
    request: Request,
    x_shop_id: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Thực thi on the sandbox: the real listing write, then TikTok's read-back."""
    context = reviewer_context(request)
    shop = await require_sandbox_pin(session, context, x_shop_id)
    assert context is not None
    item = await _card_item(session, shop, action_card_id)
    change = _plan(item)
    if change["executor"] not in _LIVE_EXECUTORS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "not_executable_by_juli"}
        )
    product_id = (change.get("product") or {}).get("tiktok_product_id")
    if not product_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "no_product"})
    image_bytes: bytes | None = None
    if body.image_base64:
        try:
            image_bytes = base64.b64decode(body.image_base64, validate=True)
        except (binascii.Error, ValueError):
            raise _unprocessable("image_invalid") from None
    if change["executor"] == "juli_with_photo" and image_bytes is None:
        raise _unprocessable("image_required")
    lever = change["lever"]["code"]
    title = body.title or (_proposal(change, "title") if lever == "title" else None)
    description = body.description or (
        _proposal(change, "description") if lever == "description" else None
    )
    if title is None and description is None and image_bytes is None:
        raise _unprocessable("no_content")
    app_key = os.environ.get("TIKTOK_APP_KEY", "").strip()
    app_secret = os.environ.get("TIKTOK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"code": "tiktok_unconfigured"}
        )
    try:
        resources = await sandbox.load_reviewer_write_resources(
            session, shop_id=shop.id, app_key=app_key, app_secret=app_secret
        )
    except sandbox.ReviewerWriteRefused:
        raise deny("sandbox_only") from None
    try:
        result = await asyncio.to_thread(
            sandbox.write_listing,
            resources,
            tiktok_product_id=str(product_id),
            title=title,
            description=description,
            image_bytes=image_bytes,
        )
    except sandbox.ProductNotOwnedBySandboxSeller:
        logger.warning(
            "reviewer_sandbox_product_not_owned",
            extra={"shop_id": str(shop.id), "card": str(action_card_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "product_not_owned_by_sandbox_seller",
                "tiktok_code": sandbox.TIKTOK_PRODUCT_NOT_OWNED,
            },
        ) from None
    except TikTokAPIError as exc:
        logger.warning(
            "reviewer_sandbox_write_failed",
            extra={"shop_id": str(shop.id), "tiktok_code": exc.code},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "tiktok_error", "tiktok_code": exc.code, "message": exc.message},
        ) from None
    except ValueError as exc:
        # The image failed screening, or the product has no leaf category / main image.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "write_refused", "message": str(exc)},
        ) from None
    await audit.record(
        session,
        context.account.actor,
        audit.ACTION_REVIEWER_SANDBOX_EXECUTE,
        shop_id=shop.id,
        after={
            "platform": context.platform,
            "action_card_id": str(action_card_id),
            "lever": lever,
            "tiktok_product_id": result.tiktok_product_id,
            "operations": result.operations,
            "fields": [f["field"] for f in result.fields],
        },
    )
    await session.commit()
    logger.info(
        "reviewer_sandbox_executed",
        extra={"platform": context.platform, "card": str(action_card_id), "lever": lever},
    )
    return {
        "simulated": False,
        "tiktok_write": True,
        "step": "execute",
        "action_card_id": str(action_card_id),
        "steps": [
            {"key": "approve", "label": "Duyệt", "done": True},
            {"key": "execute", "label": "Thực thi", "done": True},
        ],
        "lever": change["lever"],
        "tiktok_product_id": result.tiktok_product_id,
        "operations": result.operations,
        "read_back": {
            "confirmed_at": result.confirmed_at.isoformat().replace("+00:00", "Z"),
            "fields": result.fields,
            "listing": result.confirmed,
        },
    }
