"""TikTok Shop OAuth redirect URL — public callback from TikTok Partner Center."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.services.tiktok.oauth import TikTokOAuthInfrastructureService
from backend.api.services.tiktok.schemas import TikTokOAuthCallbackResult
from backend.integrations.catalog.domain.integrations.tiktok.auth import TikTokAuth
from backend.integrations.catalog.domain.integrations.tiktok.exceptions import (
    AuthenticationError,
)
from backend.integrations.identity.infrastructure.auth.exceptions import Unauthorized
from backend.runtime import require_env

router = APIRouter(prefix="/auth/tiktok", tags=["auth"])

DEFAULT_TIKTOK_BASE_URL = "https://open-api.tiktokglobalshop.com"
DEFAULT_TIKTOK_AUTH_BASE_URL = "https://auth.tiktok-shops.com"


def get_tiktok_oauth_service() -> TikTokOAuthInfrastructureService:
    try:
        app_secret = require_env("TIKTOK_APP_SECRET")
        app_key = require_env("TIKTOK_APP_KEY")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok OAuth is not configured",
        ) from exc

    base_url = os.environ.get("TIKTOK_BASE_URL", DEFAULT_TIKTOK_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_TIKTOK_BASE_URL

    auth_base_url = os.environ.get(
        "TIKTOK_AUTH_BASE_URL", DEFAULT_TIKTOK_AUTH_BASE_URL
    ).strip()
    if not auth_base_url:
        auth_base_url = DEFAULT_TIKTOK_AUTH_BASE_URL

    tiktok_auth = TikTokAuth(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        auth_base_url=auth_base_url,
    )
    return TikTokOAuthInfrastructureService(
        app_secret=app_secret, tiktok_auth=tiktok_auth
    )


@router.get("/callback", response_model=TikTokOAuthCallbackResult)
async def tiktok_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    app_key: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    shop_region: str | None = Query(default=None),
    oauth_service: TikTokOAuthInfrastructureService = Depends(get_tiktok_oauth_service),
) -> TikTokOAuthCallbackResult:
    """Accept TikTok OAuth redirect, validate parameters, and exchange the code."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required query parameter: code",
        )

    try:
        return await oauth_service.handle_callback(
            code,
            state,
            app_key=app_key,
            locale=locale,
            shop_region=shop_region,
        )
    except Unauthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TikTok token exchange failed",
        ) from None
