"""TikTok Shop OAuth redirect URL — public callback from TikTok Partner Center."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.database import get_session
from juli_backend.services.tiktok.oauth import (
    TikTokOAuthInfrastructureService,
    TikTokOAuthNotConfiguredError,
    TikTokOAuthTokenExchangeFailed,
    build_tiktok_oauth_service,
    complete_tiktok_oauth_callback,
)
from juli_backend.services.tiktok.schemas import TikTokOAuthCallbackResult

router = APIRouter(prefix="/auth/tiktok", tags=["auth"])


def get_tiktok_oauth_service() -> TikTokOAuthInfrastructureService:
    try:
        return build_tiktok_oauth_service()
    except TikTokOAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok OAuth is not configured",
        ) from exc


@router.get("/callback", response_model=TikTokOAuthCallbackResult)
async def tiktok_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    app_key: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    shop_region: str | None = Query(default=None),
    oauth_service: TikTokOAuthInfrastructureService = Depends(get_tiktok_oauth_service),
    session: AsyncSession = Depends(get_session),
) -> TikTokOAuthCallbackResult:
    """Accept TikTok OAuth redirect, validate parameters, and exchange the code."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required query parameter: code",
        )

    try:
        return await complete_tiktok_oauth_callback(
            session,
            code=code,
            state=state,
            app_key=app_key,
            locale=locale,
            shop_region=shop_region,
            oauth_service=oauth_service,
        )
    except Unauthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except TikTokOAuthTokenExchangeFailed:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TikTok token exchange failed",
        ) from None
