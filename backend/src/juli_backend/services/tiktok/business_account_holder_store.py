"""Persist TikTok Business account-holder OAuth tokens after callback exchange."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo, UsersRepo
from juli_backend.services.tiktok.token_expiry import access_token_expires_at

ACCOUNT_HOLDER_CAPABILITY = "business_account_holder"
ACCOUNT_HOLDER_SHOP_NAME = "TikTok Business Account Holder"


def account_holder_merchant_id(token_data: dict) -> str | None:
    """Return the stable merchant key for an account-holder credential row."""
    for key in ("creator_id", "open_id", "creator_open_id"):
        value = token_data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


async def persist_account_holder_tokens(
    session: AsyncSession,
    token_data: dict,
    *,
    user_id: uuid.UUID,
) -> None:
    """Upsert encrypted account-holder credentials for a Juli user."""
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    merchant_id = account_holder_merchant_id(token_data)
    if not access_token or not refresh_token or not merchant_id:
        return

    await UsersRepo(session).get_or_create(user_id, f"+849{user_id.int % 10_000_000_000:010d}")

    shops_repo = ShopsRepo(session)
    shop = await _resolve_shop(shops_repo, user_id, merchant_id)

    expires_at = access_token_expires_at(
        token_data.get("expires_in") or token_data.get("access_token_expire_in")
    )
    cred_repo = TikTokCredentialRepo(session)
    scopes = _scopes_to_str(token_data.get("scope") or token_data.get("scopes"))

    try:
        existing = await cred_repo.get_by_merchant(
            merchant_id, ACCOUNT_HOLDER_CAPABILITY
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
            scopes=scopes,
            merchant_authorization_id=merchant_id,
            capability=ACCOUNT_HOLDER_CAPABILITY,
        )


async def _resolve_shop(
    shops_repo: ShopsRepo,
    user_id: uuid.UUID,
    merchant_id: str,
):
    existing = await shops_repo.get_by_tiktok_id(merchant_id)
    if existing is not None and existing.user_id == user_id:
        return existing

    shops = await shops_repo.list(user_id)
    if shops:
        return shops[0]

    return await shops_repo.create(
        user_id,
        ACCOUNT_HOLDER_SHOP_NAME,
        merchant_id,
    )


def _scopes_to_str(scopes: object) -> str | None:
    if scopes is None:
        return None
    if isinstance(scopes, list):
        return ",".join(str(scope) for scope in scopes)
    return str(scopes)
