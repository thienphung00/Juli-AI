"""TikTok diagnostic route — non-production only, session- and ownership-gated.

Three separate gates now stand in front of this route (#903, ADR-061 decision 2):

1. **Not mounted in production at all.** ``create_app`` skips this router when
   ``is_production()``. The ``ENABLE_TIKTOK_DEBUG`` flag is not consulted there, so an
   operator who leaves the flag set cannot expose it.
2. **Requires an authenticated session that owns the shop.** ``get_active_shop``
   resolves ``X-Shop-Id`` against the shops the caller actually owns.
3. **The flag still applies** within non-production, unchanged.

What this closes: the route previously accepted a client-supplied ``shop_id`` (or
``merchant_authorization_id`` + ``capability``) with no session and no ownership check,
so any unauthenticated caller could enumerate whether an arbitrary shop had stored
credentials and read back its identity — a cross-tenant IDOR. Those parameters are gone;
the route now reports on the caller's own active shop and nothing else.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.config.runtime import require_env
from juli_backend.database import TikTokCredentialRepo, get_session
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import DEFAULT_OPEN_API_BASE_URL
from juli_backend.models.models import Shop
from juli_backend.services.tiktok.verify_connection import (
    TikTokVerifyConnectionService,
    tiktok_debug_enabled,
)

router = APIRouter(prefix="/debug/tiktok", tags=["debug"])


class TikTokVerifyConnectionResponse(BaseModel):
    connected: bool
    shop_id: str | None = None
    shop_name: str | None = None
    market: str | None = None
    error: str | None = None


def _require_debug_enabled() -> None:
    if not tiktok_debug_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def get_verify_connection_service() -> TikTokVerifyConnectionService:
    try:
        app_key = require_env("TIKTOK_APP_KEY")
        app_secret = require_env("TIKTOK_APP_SECRET")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok OAuth is not configured",
        ) from exc

    base_url = os.environ.get("TIKTOK_BASE_URL", DEFAULT_OPEN_API_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_OPEN_API_BASE_URL

    return TikTokVerifyConnectionService(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
    )


@router.get("/verify-connection", response_model=TikTokVerifyConnectionResponse)
async def verify_tiktok_connection(
    _: None = Depends(_require_debug_enabled),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    verify_service: TikTokVerifyConnectionService = Depends(get_verify_connection_service),
) -> TikTokVerifyConnectionResponse:
    """Verify the active shop's stored TikTok token by calling Get Authorized Shops.

    Scoped to ``shop`` from ``get_active_shop`` — there is deliberately no way to name a
    different shop. That is what makes this safe to keep at all.
    """
    try:
        # Non-production only (the router is not mounted otherwise), and it does not
        # bypass the ownership gate above — the caller still had to authenticate and own
        # a shop to reach this line. Kept because #493's HITL round-trip uses it.
        access_token = os.environ.get("TIKTOK_DEBUG_ACCESS_TOKEN", "").strip()
        if not access_token:
            cred_repo = TikTokCredentialRepo(session)
            try:
                credential = await cred_repo.get_by_shop(shop.id)
            except NotFound as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No stored TikTok credentials found",
                ) from exc
            access_token = credential.access_token

        result = await verify_service.verify(access_token)
        return TikTokVerifyConnectionResponse(**result)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Database unavailable for credential lookup — run `alembic upgrade head` on the VPS"
            ),
        ) from exc
