"""Persist TikTok Business Advertiser OAuth tokens after callback exchange."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo, UsersRepo
from juli_backend.services.tiktok.token_expiry import access_token_expires_at

BUSINESS_ADVERTISER_CAPABILITY = "business_advertiser"
BUSINESS_PLACEHOLDER_PHONE = "+849000000002"
BUSINESS_PLACEHOLDER_SHOP_NAME = "TikTok Business"


def _primary_advertiser_id(token_data: dict) -> str | None:
    advertiser_ids = token_data.get("advertiser_ids")
    if isinstance(advertiser_ids, list) and advertiser_ids:
        first = advertiser_ids[0]
        if first is not None and str(first).strip():
            return str(first)
    return None


def _scopes_to_str(scopes: object) -> str | None:
    if scopes is None:
        return None
    if isinstance(scopes, list):
        return ",".join(str(scope) for scope in scopes)
    return str(scopes)


async def _resolve_shop_id(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    shops = await ShopsRepo(session).list(user_id)
    if shops:
        return shops[0].id

    shop = await ShopsRepo(session).create(
        user_id,
        BUSINESS_PLACEHOLDER_SHOP_NAME,
    )
    return shop.id


async def persist_advertiser_oauth_tokens(
    session: AsyncSession,
    token_data: dict,
    *,
    user_id: uuid.UUID,
) -> None:
    """Upsert Business advertiser credentials for the Juli user from OAuth state."""
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    advertiser_id = _primary_advertiser_id(token_data)
    if not access_token or not refresh_token or not advertiser_id:
        return

    await UsersRepo(session).get_or_create(user_id, BUSINESS_PLACEHOLDER_PHONE)
    shop_id = await _resolve_shop_id(session, user_id)

    expires_at = access_token_expires_at(token_data.get("access_token_expire_in"))
    cred_repo = TikTokCredentialRepo(session)
    try:
        existing = await cred_repo.get_by_merchant(
            advertiser_id,
            BUSINESS_ADVERTISER_CAPABILITY,
        )
        await cred_repo.update_tokens(
            credential_id=existing.id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
        )
    except NotFound:
        await cred_repo.create(
            shop_id=shop_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
            scopes=_scopes_to_str(token_data.get("scope")),
            merchant_authorization_id=advertiser_id,
            capability=BUSINESS_ADVERTISER_CAPABILITY,
        )
