"""App Review OAuth persistence — delegates to Auth OAuth facade (#562)."""

from __future__ import annotations

import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import TikTokAuth
from juli_backend.repositories.repos import UsersRepo
from juli_backend.services.tiktok.credential_binding import make_binding_verifier

APP_REVIEW_USER_PHONE = "+849000000001"
DEFAULT_TIKTOK_BASE_URL = "https://open-api.tiktokglobalshop.com"
DEFAULT_TIKTOK_AUTH_BASE_URL = "https://auth.tiktok-shops.com"


def app_review_user_id() -> uuid.UUID:
    raw = os.environ.get("TIKTOK_APP_REVIEW_USER_ID", "00000000-0000-4000-8000-000000000001")
    return uuid.UUID(raw)


def _build_oauth_service(session: AsyncSession) -> TikTokOAuthService:
    app_key = os.environ.get("TIKTOK_APP_KEY", "app_review")
    app_secret = os.environ.get("TIKTOK_APP_SECRET", "app_review_secret")
    base_url = (
        os.environ.get("TIKTOK_BASE_URL", DEFAULT_TIKTOK_BASE_URL).strip()
        or DEFAULT_TIKTOK_BASE_URL
    )
    auth_base_url = (
        os.environ.get("TIKTOK_AUTH_BASE_URL", DEFAULT_TIKTOK_AUTH_BASE_URL).strip()
        or DEFAULT_TIKTOK_AUTH_BASE_URL
    )
    redirect_uri = os.environ.get(
        "TIKTOK_REDIRECT_URI", "https://api.app-juli.com/v1/auth/tiktok/callback"
    )
    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url,
            auth_base_url=auth_base_url,
        ),
        session=session,
        redirect_uri=redirect_uri,
        app_secret=app_secret,
        binding_verifier=make_binding_verifier(app_key=app_key, app_secret=app_secret),
    )


async def persist_oauth_tokens(
    session: AsyncSession,
    token_data: dict,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    """Upsert shop + credential rows via the Auth OAuth facade (no direct repo writes)."""
    owner_id = user_id or app_review_user_id()
    await UsersRepo(session).get_or_create(owner_id, APP_REVIEW_USER_PHONE)
    oauth = _build_oauth_service(session)
    await oauth.provision_shop_and_credentials(token_data, user_id=owner_id)
