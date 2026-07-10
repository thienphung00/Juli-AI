"""Persist TikTok OAuth tokens after the App Review callback exchange."""

from __future__ import annotations

import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok.merchant import (
    resolve_merchant_context,
)
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo, UsersRepo
from juli_backend.services.tiktok.token_expiry import access_token_expires_at

APP_REVIEW_USER_PHONE = "+849000000001"


def app_review_user_id() -> uuid.UUID:
    raw = os.environ.get(
        "TIKTOK_APP_REVIEW_USER_ID", "00000000-0000-4000-8000-000000000001"
    )
    return uuid.UUID(raw)


async def persist_oauth_tokens(
    session: AsyncSession,
    token_data: dict,
    *,
    user_id: uuid.UUID | None = None,
) -> None:
    """Upsert shop + credential rows from a successful token exchange."""
    open_id = token_data.get("open_id")
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not open_id or not access_token or not refresh_token:
        return

    owner_id = user_id or app_review_user_id()
    await UsersRepo(session).get_or_create(owner_id, APP_REVIEW_USER_PHONE)

    shops_repo = ShopsRepo(session)
    shop = await shops_repo.get_by_tiktok_id(open_id)
    if shop is None:
        shop = await shops_repo.create(
            owner_id,
            token_data.get("seller_name") or "TikTok Shop",
            open_id,
        )

    expires_at = access_token_expires_at(token_data.get("access_token_expire_in"))
    merchant_authorization_id, capability = resolve_merchant_context(open_id)
    cred_repo = TikTokCredentialRepo(session)
    try:
        existing = await cred_repo.get_by_merchant(
            merchant_authorization_id, capability
        )
        await cred_repo.update_tokens(
            credential_id=existing.id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
        )
    except NotFound:
        await cred_repo.create(
            shop_id=shop.id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
            scopes=_scopes_to_str(token_data.get("granted_scopes")),
            merchant_authorization_id=merchant_authorization_id,
            capability=capability.value,
        )


def _scopes_to_str(scopes: object) -> str | None:
    if scopes is None:
        return None
    if isinstance(scopes, list):
        return ",".join(str(scope) for scope in scopes)
    return str(scopes)
