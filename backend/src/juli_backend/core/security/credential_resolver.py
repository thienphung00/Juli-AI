"""Resolve TikTok credentials for production sync and sandbox validation."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
)
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import TikTokCredentialRepo


async def resolve_production_read_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return Fujiwa production-read credentials — never falls back to latest."""
    return await TikTokCredentialRepo(session).get_by_merchant(
        PRODUCTION_AUTH_ID,
        TikTokCapability.PRODUCTION_READ,
    )


async def resolve_sandbox_write_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return SANDBOX_VN write-validation credentials."""
    return await TikTokCredentialRepo(session).get_by_merchant(
        SANDBOX_AUTH_ID,
        TikTokCapability.SANDBOX_WRITE,
    )
