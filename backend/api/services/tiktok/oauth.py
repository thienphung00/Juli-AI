"""TikTok OAuth callback infrastructure — state validation and token exchange stub.

Business logic (shop provisioning, credential persistence) is intentionally
out of scope; see ``TikTokOAuthService`` in identity/infrastructure/auth.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid

from backend.api.services.tiktok.schemas import TikTokOAuthCallbackResult
from backend.integrations.identity.infrastructure.auth.exceptions import Unauthorized

logger = logging.getLogger(__name__)


class TikTokOAuthInfrastructureService:
    """Validates OAuth callback parameters and stubs token exchange."""

    def __init__(self, *, app_secret: str) -> None:
        self._app_secret = app_secret

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

    async def exchange_code(self, code: str, *, user_id: uuid.UUID) -> dict:
        """Placeholder for TikTok authorization-code → access-token exchange.

        TODO: Call ``TikTokAuth.exchange_code`` and persist credentials via
        ``TikTokOAuthService.handle_callback`` once merchant onboarding ships.
        """
        logger.info(
            "tiktok_oauth_code_received",
            extra={"user_id": str(user_id), "code_len": len(code)},
        )
        return {"status": "pending", "user_id": str(user_id)}

    async def handle_callback(self, code: str, state: str) -> TikTokOAuthCallbackResult:
        """Validate callback parameters, verify state, and stub token exchange."""
        user_id = self.verify_state(state)
        await self.exchange_code(code, user_id=user_id)
        logger.info("tiktok_oauth_callback_accepted", extra={"user_id": str(user_id)})
        return TikTokOAuthCallbackResult(
            status="ok",
            message="OAuth callback accepted; token exchange pending implementation",
        )
