"""Temporary TikTok debug routes — gated by ENABLE_TIKTOK_DEBUG=1."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.tiktok.verify_connection import (
    TikTokVerifyConnectionService,
    tiktok_debug_enabled,
)
from juli_backend.database import TikTokCredentialRepo, get_session
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok.merchant import (
    TikTokCapability,
)
from juli_backend.integrations.tiktok.auth import (
    DEFAULT_OPEN_API_BASE_URL,
)
from juli_backend.core.config.runtime import require_env

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
    shop_id: uuid.UUID | None = Query(default=None),
    merchant_authorization_id: str | None = Query(default=None),
    capability: TikTokCapability | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    verify_service: TikTokVerifyConnectionService = Depends(get_verify_connection_service),
) -> TikTokVerifyConnectionResponse:
    """Verify a stored TikTok token by calling Get Authorized Shops."""
    try:
        access_token = os.environ.get("TIKTOK_DEBUG_ACCESS_TOKEN", "").strip()
        if not access_token:
            cred_repo = TikTokCredentialRepo(session)
            try:
                if shop_id is not None:
                    credential = await cred_repo.get_by_shop(shop_id)
                elif merchant_authorization_id and capability is not None:
                    credential = await cred_repo.get_by_merchant(
                        merchant_authorization_id, capability
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Provide shop_id or merchant_authorization_id + "
                            "capability for credential lookup"
                        ),
                    )
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
                "Database unavailable for credential lookup — run "
                "`alembic upgrade head` on the VPS"
            ),
        ) from exc
