"""TikTok OAuth callback infrastructure — state validation and token exchange.

Business logic (shop provisioning, credential persistence) is intentionally
out of scope; see ``TikTokOAuthService`` in identity/infrastructure/auth.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import uuid

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
)
from juli_backend.services.tiktok.schemas import TikTokOAuthCallbackResult

logger = logging.getLogger(__name__)


class TikTokOAuthInfrastructureService:
    """Validates OAuth callback parameters and exchanges authorization codes."""

    def __init__(self, *, app_secret: str, tiktok_auth: TikTokAuth) -> None:
        self._app_secret = app_secret
        self._tiktok_auth = tiktok_auth

    def verify_state(self, state: str) -> uuid.UUID:
        """Verify HMAC-signed state and return the embedded user id."""
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
            raise Unauthorized(f"Malformed OAuth state: {exc}")

    async def exchange_code(self, code: str, *, user_id: uuid.UUID | None = None) -> dict:
        """Exchange TikTok authorization code for access + refresh tokens."""
        logger.info(
            "tiktok_oauth_code_received",
            extra={
                "user_id": str(user_id) if user_id else None,
                "code_len": len(code),
            },
        )
        return await asyncio.to_thread(self._tiktok_auth.exchange_code, code)

    async def handle_callback(
        self,
        code: str,
        state: str | None = None,
        *,
        app_key: str | None = None,
        locale: str | None = None,
        shop_region: str | None = None,
    ) -> tuple[TikTokOAuthCallbackResult, dict, uuid.UUID | None]:
        """Validate callback parameters, verify state when present, exchange code."""
        user_id: uuid.UUID | None = None
        if state:
            user_id = self.verify_state(state)
        else:
            logger.warning(
                "tiktok_oauth_callback_missing_state",
                extra={
                    "app_key": app_key,
                    "locale": locale,
                    "shop_region": shop_region,
                },
            )

        try:
            token_data = await self.exchange_code(code, user_id=user_id)
        except AuthenticationError as exc:
            logger.warning(
                "tiktok_oauth_token_exchange_failed",
                extra={
                    "user_id": str(user_id) if user_id else None,
                    "tiktok_error_code": exc.code,
                    "request_id": exc.request_id,
                },
            )
            raise

        open_id = token_data.get("open_id")
        expires_in = token_data.get("access_token_expire_in")

        logger.info(
            "tiktok_oauth_token_exchange_completed",
            extra={
                "user_id": str(user_id) if user_id else None,
                "open_id_present": bool(open_id),
                "access_token_expires_in": expires_in,
            },
        )
        return (
            TikTokOAuthCallbackResult(
                status="ok",
                message="OAuth callback accepted; token exchange completed",
                open_id_present=bool(open_id),
                access_token_expires_in=expires_in,
            ),
            token_data,
            user_id,
        )
