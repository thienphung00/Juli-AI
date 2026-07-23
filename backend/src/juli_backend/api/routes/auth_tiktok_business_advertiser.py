"""TikTok Business Advertiser OAuth redirect URL — public Marketing API callback."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.database import get_session
from juli_backend.integrations.tiktok.business_advertiser_auth import (
    TikTokBusinessAdvertiserAuth,
)
from juli_backend.integrations.tiktok.exceptions import AuthenticationError
from juli_backend.services.tiktok.advertiser_oauth_store import (
    persist_advertiser_oauth_tokens,
)
from juli_backend.services.tiktok.business_advertiser_oauth import (
    TikTokBusinessAdvertiserOAuthCallbackResult,
    TikTokBusinessAdvertiserOAuthService,
)

router = APIRouter(prefix="/auth/tiktok/business", tags=["auth"])

DEFAULT_BUSINESS_API_BASE_URL = "https://business-api.tiktok.com"


def get_business_advertiser_oauth_service() -> TikTokBusinessAdvertiserOAuthService:
    try:
        app_secret = require_env("TIKTOK_BUSINESS_APP_SECRET")
        app_id = require_env("TIKTOK_BUSINESS_APP_ID")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok Business OAuth is not configured",
        ) from exc

    base_url = os.environ.get(
        "TIKTOK_BUSINESS_API_BASE_URL", DEFAULT_BUSINESS_API_BASE_URL
    ).strip()
    if not base_url:
        base_url = DEFAULT_BUSINESS_API_BASE_URL

    business_auth = TikTokBusinessAdvertiserAuth(
        app_id=app_id,
        app_secret=app_secret,
        base_url=base_url,
    )
    return TikTokBusinessAdvertiserOAuthService(
        app_secret=app_secret,
        business_auth=business_auth,
    )


@router.get("/callback", response_model=TikTokBusinessAdvertiserOAuthCallbackResult)
async def tiktok_business_advertiser_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    oauth_service: TikTokBusinessAdvertiserOAuthService = Depends(
        get_business_advertiser_oauth_service
    ),
    session: AsyncSession = Depends(get_session),
) -> TikTokBusinessAdvertiserOAuthCallbackResult:
    """Accept TikTok Business advertiser OAuth redirect and exchange the code."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required query parameter: code",
        )
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required query parameter: state",
        )

    try:
        result, token_data, user_id = await oauth_service.handle_callback(code, state)
        await persist_advertiser_oauth_tokens(session, token_data, user_id=user_id)
        await session.commit()
        return result
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
