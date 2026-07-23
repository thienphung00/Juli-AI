"""TikTok Business account-holder OAuth redirect callback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.database import get_session
from juli_backend.integrations.tiktok.business_account_holder_auth import (
    TikTokBusinessAccountHolderAuth,
)
from juli_backend.integrations.tiktok.exceptions import AuthenticationError
from juli_backend.services.tiktok.business_account_holder_store import (
    account_holder_merchant_id,
    persist_account_holder_tokens,
)

router = APIRouter(
    prefix="/auth/tiktok/business/account-holder",
    tags=["auth"],
)

logger = logging.getLogger(__name__)


class TikTokBusinessAccountHolderCallbackResult(BaseModel):
    """Infrastructure-only account-holder callback response (no persisted tokens)."""

    status: str
    message: str
    subject_id_present: bool | None = None
    access_token_expires_in: int | None = None


def get_business_account_holder_auth() -> TikTokBusinessAccountHolderAuth:
    try:
        app_id = require_env("TIKTOK_BUSINESS_APP_ID")
        app_secret = require_env("TIKTOK_BUSINESS_APP_SECRET")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok Business OAuth is not configured",
        ) from exc

    base_url = os.environ.get(
        "TIKTOK_BUSINESS_API_BASE_URL", "https://business-api.tiktok.com"
    ).strip()
    if not base_url:
        base_url = "https://business-api.tiktok.com"

    return TikTokBusinessAccountHolderAuth(
        app_id=app_id,
        app_secret=app_secret,
        base_url=base_url,
    )


def _verify_state(state: str, app_secret: str) -> uuid.UUID:
    parts = state.split(".", 1)
    if len(parts) != 2:
        raise Unauthorized("Invalid OAuth state")

    encoded, signature = parts
    expected = hmac.new(
        app_secret.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise Unauthorized("Invalid OAuth state signature")

    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        return uuid.UUID(payload["user_id"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        raise Unauthorized(f"Malformed OAuth state: {exc}")


@router.get("/callback", response_model=TikTokBusinessAccountHolderCallbackResult)
async def tiktok_business_account_holder_callback(
    auth_code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    auth_client: TikTokBusinessAccountHolderAuth = Depends(
        get_business_account_holder_auth
    ),
    session: AsyncSession = Depends(get_session),
) -> TikTokBusinessAccountHolderCallbackResult:
    """Accept TikTok Business account-holder redirect and exchange ``auth_code``."""
    if not auth_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required query parameter: auth_code",
        )
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required query parameter: state",
        )

    try:
        app_secret = require_env("TIKTOK_BUSINESS_APP_SECRET")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok Business OAuth is not configured",
        ) from exc

    try:
        user_id = _verify_state(state, app_secret)
    except Unauthorized as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    logger.info(
        "tiktok_business_account_holder_code_received",
        extra={"user_id": str(user_id), "auth_code_len": len(auth_code)},
    )

    try:
        token_data = await asyncio.to_thread(
            auth_client.exchange_auth_code, auth_code
        )
    except AuthenticationError as exc:
        logger.warning(
            "tiktok_business_account_holder_token_exchange_failed",
            extra={
                "user_id": str(user_id),
                "tiktok_error_code": exc.code,
                "request_id": exc.request_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TikTok token exchange failed",
        ) from None

    await persist_account_holder_tokens(session, token_data, user_id=user_id)
    await session.commit()

    expires_in = token_data.get("expires_in") or token_data.get(
        "access_token_expire_in"
    )
    subject_id = account_holder_merchant_id(token_data)

    logger.info(
        "tiktok_business_account_holder_token_exchange_completed",
        extra={
            "user_id": str(user_id),
            "subject_id_present": bool(subject_id),
            "access_token_expires_in": expires_in,
        },
    )

    return TikTokBusinessAccountHolderCallbackResult(
        status="ok",
        message="Account-holder OAuth callback accepted; token exchange completed",
        subject_id_present=bool(subject_id),
        access_token_expires_in=expires_in,
    )
