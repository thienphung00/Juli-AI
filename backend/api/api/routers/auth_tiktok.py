"""TikTok Shop OAuth redirect URL — public callback from TikTok Partner Center."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.services.tiktok.oauth import TikTokOAuthInfrastructureService
from backend.api.services.tiktok.schemas import TikTokOAuthCallbackResult
from backend.integrations.identity.infrastructure.auth.exceptions import Unauthorized

router = APIRouter(prefix="/auth/tiktok", tags=["auth"])


def get_tiktok_oauth_service() -> TikTokOAuthInfrastructureService:
    app_secret = os.environ.get("TIKTOK_APP_SECRET", "")
    return TikTokOAuthInfrastructureService(app_secret=app_secret)


@router.get("/callback", response_model=TikTokOAuthCallbackResult)
async def tiktok_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    app_key: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    shop_region: str | None = Query(default=None),
    oauth_service: TikTokOAuthInfrastructureService = Depends(get_tiktok_oauth_service),
) -> TikTokOAuthCallbackResult:
    """Accept TikTok OAuth redirect, validate parameters, and verify state when sent."""
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
