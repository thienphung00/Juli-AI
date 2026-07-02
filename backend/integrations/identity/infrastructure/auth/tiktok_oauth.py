"""TikTok OAuth service: authorization flow, shop provisioning, token refresh.

Orchestrates TikTokAuth (integrations/tiktok) with the persistence layer (data)
to provide a complete OAuth lifecycle for connecting TikTok Shops.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.identity.infrastructure.auth.exceptions import Unauthorized
from backend.database.models import Shop, TikTokCredential
from backend.database.repos import ShopsRepo, TikTokCredentialRepo
from backend.integrations.catalog.domain.integrations.tiktok.auth import TikTokAuth

logger = logging.getLogger(__name__)

REFRESH_BUFFER = timedelta(minutes=30)


def _utc_now() -> datetime:
    """Naive UTC timestamp (compatible with SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TikTokOAuthService:
    """Manages TikTok OAuth lifecycle: initiate, callback, token refresh."""

    def __init__(
        self,
        tiktok_auth: TikTokAuth,
        session: AsyncSession,
        redirect_uri: str,
        app_secret: str,
    ) -> None:
        self._tiktok_auth = tiktok_auth
        self._session = session
        self._redirect_uri = redirect_uri
        self._app_secret = app_secret

    async def initiate_oauth(self, user_id: uuid.UUID) -> str:
        """Generate TikTok authorization URL with signed state parameter."""
        state = self._build_state(user_id)
        url = self._tiktok_auth.generate_auth_url(self._redirect_uri, state)
        logger.info("tiktok_oauth_initiated", extra={"user_id": str(user_id)})
        return url

    async def handle_callback(self, code: str, state: str) -> Shop:
        """Exchange auth code for tokens, provision shop + credential.

        Verifies the HMAC-signed state, exchanges the authorization code via
        TikTokAuth, then creates (or reconnects) a Shop with its credential.
        """
        user_id = self._verify_state(state)

        token_data = await asyncio.to_thread(
            self._tiktok_auth.exchange_code, code
        )

        tiktok_shop_id = token_data.get("open_id")
        seller_name = token_data.get("seller_name", "TikTok Shop")

        shops_repo = ShopsRepo(self._session)
        cred_repo = TikTokCredentialRepo(self._session)

        existing = (
            await shops_repo.get_by_tiktok_id(tiktok_shop_id)
            if tiktok_shop_id
            else None
        )

        if existing and existing.user_id == user_id:
            shop = existing
        elif existing:
            logger.warning(
                "tiktok_shop_already_claimed",
                extra={
                    "tiktok_shop_id": tiktok_shop_id,
                    "user_id": str(user_id),
                },
            )
            raise Unauthorized(
                "This TikTok shop is already connected to another account"
            )
        else:
            shop = await shops_repo.create(
                user_id=user_id,
                shop_name=seller_name,
                tiktok_shop_id=tiktok_shop_id,
            )

        expires_at = _utc_now() + timedelta(
            seconds=token_data.get("access_token_expire_in", 0)
        )

        await cred_repo.create(
            shop_id=shop.id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            token_expires_at=expires_at,
            scopes=token_data.get("scopes"),
        )

        logger.info(
            "tiktok_oauth_completed",
            extra={"user_id": str(user_id), "shop_id": str(shop.id)},
        )
        return shop

    async def refresh_tokens(self, shop_id: uuid.UUID) -> TikTokCredential:
        """Proactively refresh tokens if within REFRESH_BUFFER of expiry."""
        cred_repo = TikTokCredentialRepo(self._session)
        credential = await cred_repo.get_by_shop(shop_id)

        now = _utc_now()
        if credential.token_expires_at > now + REFRESH_BUFFER:
            return credential

        token_data = await asyncio.to_thread(
            self._tiktok_auth.refresh_access_token, credential.refresh_token
        )

        new_expires_at = _utc_now() + timedelta(
            seconds=token_data.get("access_token_expire_in", 0)
        )

        updated = await cred_repo.update_tokens(
            credential_id=credential.id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            token_expires_at=new_expires_at,
        )

        logger.info("tiktok_token_refreshed", extra={"shop_id": str(shop_id)})
        return updated

    def _build_state(self, user_id: uuid.UUID) -> str:
        """Build an HMAC-signed state parameter encoding user_id + nonce."""
        payload = json.dumps(
            {"user_id": str(user_id), "nonce": secrets.token_urlsafe(16)}
        )
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        signature = hmac.new(
            self._app_secret.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        return f"{encoded}.{signature}"

    def _verify_state(self, state: str) -> uuid.UUID:
        """Verify HMAC signature and extract user_id from state parameter."""
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
