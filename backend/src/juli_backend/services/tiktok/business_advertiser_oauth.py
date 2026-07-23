"""TikTok Business Advertiser OAuth callback infrastructure."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import uuid

from pydantic import BaseModel

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.integrations.tiktok.business_advertiser_auth import (
    TikTokBusinessAdvertiserAuth,
)
from juli_backend.integrations.tiktok.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


class TikTokBusinessAdvertiserOAuthCallbackResult(BaseModel):
    """Infrastructure-only Business advertiser OAuth callback response."""

    status: str
    message: str
    advertiser_id_present: bool | None = None


class TikTokBusinessAdvertiserOAuthService:
    """Validates Business OAuth callback parameters and exchanges auth codes."""

    def __init__(
        self,
        *,
        app_secret: str,
        business_auth: TikTokBusinessAdvertiserAuth,
    ) -> None:
        self._app_secret = app_secret
        self._business_auth = business_auth

    def verify_state(self, state: str) -> uuid.UUID:
        parts = state.split(".", 1)
        if len(parts) != 2:
            raise Unauthorized("Invalid OAuth state")

        encoded, signature = parts
        expected = hmac.new(
            self._app_secret.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise Unauthorized("Invalid OAuth state signature")

        try:
            payload = json.loads(base64.urlsafe_b64decode(encoded))
            return uuid.UUID(payload["user_id"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise Unauthorized(f"Malformed OAuth state: {exc}") from exc

    async def exchange_code(self, code: str, *, user_id: uuid.UUID) -> dict:
        logger.info(
            "tiktok_business_advertiser_oauth_code_received",
            extra={
                "user_id": str(user_id),
                "code_len": len(code),
            },
        )
        return await asyncio.to_thread(self._business_auth.exchange_code, code)

    async def handle_callback(
        self,
        code: str,
        state: str,
    ) -> tuple[TikTokBusinessAdvertiserOAuthCallbackResult, dict, uuid.UUID]:
        user_id = self.verify_state(state)

        try:
            token_data = await self.exchange_code(code, user_id=user_id)
        except AuthenticationError as exc:
            logger.warning(
                "tiktok_business_advertiser_oauth_token_exchange_failed",
                extra={
                    "user_id": str(user_id),
                    "tiktok_error_code": exc.code,
                    "request_id": exc.request_id,
                },
            )
            raise

        advertiser_ids = token_data.get("advertiser_ids")
        advertiser_id_present = (
            isinstance(advertiser_ids, list) and len(advertiser_ids) > 0
        )

        logger.info(
            "tiktok_business_advertiser_oauth_token_exchange_completed",
            extra={
                "user_id": str(user_id),
                "advertiser_id_present": advertiser_id_present,
            },
        )
        return (
            TikTokBusinessAdvertiserOAuthCallbackResult(
                status="ok",
                message="Business advertiser OAuth callback accepted; token exchange completed",
                advertiser_id_present=advertiser_id_present,
            ),
            token_data,
            user_id,
        )
