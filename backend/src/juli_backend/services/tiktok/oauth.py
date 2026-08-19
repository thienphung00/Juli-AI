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
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import (
    AuthenticationError,
    TikTokAuth,
)
from juli_backend.repositories.repos import UsersRepo
from juli_backend.services.tiktok.credential_binding import make_binding_verifier
from juli_backend.services.tiktok.schemas import TikTokOAuthCallbackResult

APP_REVIEW_USER_PHONE = "+849000000001"

logger = logging.getLogger(__name__)

DEFAULT_TIKTOK_BASE_URL = "https://open-api.tiktokglobalshop.com"
DEFAULT_TIKTOK_AUTH_BASE_URL = "https://auth.tiktok-shops.com"


class TikTokOAuthNotConfiguredError(RuntimeError):
    """Raised when required TikTok OAuth environment variables are missing."""


class TikTokOAuthTokenExchangeFailed(Exception):
    """Raised when TikTok rejects an authorization code exchange."""


def build_tiktok_oauth_service() -> TikTokOAuthInfrastructureService:
    """Construct the OAuth callback service from runtime environment."""
    try:
        app_secret = require_env("TIKTOK_APP_SECRET")
        app_key = require_env("TIKTOK_APP_KEY")
    except RuntimeError as exc:
        raise TikTokOAuthNotConfiguredError("TikTok OAuth is not configured") from exc

    base_url = os.environ.get("TIKTOK_BASE_URL", DEFAULT_TIKTOK_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_TIKTOK_BASE_URL

    auth_base_url = os.environ.get("TIKTOK_AUTH_BASE_URL", DEFAULT_TIKTOK_AUTH_BASE_URL).strip()
    if not auth_base_url:
        auth_base_url = DEFAULT_TIKTOK_AUTH_BASE_URL

    tiktok_auth = TikTokAuth(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        auth_base_url=auth_base_url,
    )
    return TikTokOAuthInfrastructureService(app_secret=app_secret, tiktok_auth=tiktok_auth)


def _app_review_user_id() -> uuid.UUID:
    raw = os.environ.get(
        "TIKTOK_APP_REVIEW_USER_ID",
        "00000000-0000-4000-8000-000000000001",
    )
    return uuid.UUID(raw)


def build_partner_oauth_facade(
    session: AsyncSession,
    infra: TikTokOAuthInfrastructureService,
) -> TikTokOAuthService:
    """Construct the Auth-owned Partner OAuth facade sharing infra TikTokAuth."""
    redirect_uri = os.environ.get(
        "TIKTOK_REDIRECT_URI",
        "https://api.app-juli.com/v1/auth/tiktok/callback",
    ).strip()
    return TikTokOAuthService(
        tiktok_auth=infra.tiktok_auth,
        session=session,
        redirect_uri=redirect_uri,
        app_secret=infra.app_secret,
        binding_verifier=make_binding_verifier(
            app_key=infra.tiktok_auth.app_key, app_secret=infra.app_secret
        ),
    )


async def complete_tiktok_oauth_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str | None = None,
    app_key: str | None = None,
    locale: str | None = None,
    shop_region: str | None = None,
    oauth_service: TikTokOAuthInfrastructureService | None = None,
) -> TikTokOAuthCallbackResult:
    """Exchange the authorization code and persist tokens via the OAuth facade."""
    service = oauth_service or build_tiktok_oauth_service()
    if state:
        user_id = service.verify_state(state)
        try:
            token_data = await service.exchange_code(code, user_id=user_id)
        except AuthenticationError as exc:
            raise TikTokOAuthTokenExchangeFailed from exc
        facade = build_partner_oauth_facade(session, service)
        shop = await facade.provision_shop_and_credentials(token_data, user_id=user_id)
        await session.commit()
        return TikTokOAuthCallbackResult(
            status="ok",
            message="OAuth callback accepted; shop provisioned via Auth facade",
            open_id_present=bool(shop.tiktok_shop_id),
            access_token_expires_in=token_data.get("access_token_expire_in"),
        )

    try:
        result, token_data, callback_user_id = await service.handle_callback(
            code,
            state,
            app_key=app_key,
            locale=locale,
            shop_region=shop_region,
        )
    except AuthenticationError as exc:
        raise TikTokOAuthTokenExchangeFailed from exc

    owner_id = callback_user_id or _app_review_user_id()
    await UsersRepo(session).get_or_create(owner_id, APP_REVIEW_USER_PHONE)
    facade = build_partner_oauth_facade(session, service)
    await facade.provision_shop_and_credentials(token_data, user_id=owner_id)
    await session.commit()
    return result


class TikTokOAuthInfrastructureService:
    """Validates OAuth callback parameters and exchanges authorization codes."""

    def __init__(self, *, app_secret: str, tiktok_auth: TikTokAuth) -> None:
        self._app_secret = app_secret
        self._tiktok_auth = tiktok_auth

    @property
    def tiktok_auth(self) -> TikTokAuth:
        return self._tiktok_auth

    @property
    def app_secret(self) -> str:
        return self._app_secret

    def verify_state(self, state: str) -> uuid.UUID:
        """Verify HMAC-signed state and return the embedded user id."""
        parts = state.split(".", 1)
        if len(parts) != 2:
            raise Unauthorized("Invalid OAuth state")

        encoded, signature = parts
        expected = hmac.new(self._app_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()

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
