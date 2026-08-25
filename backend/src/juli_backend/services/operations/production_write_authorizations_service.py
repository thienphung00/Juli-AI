"""Service layer for production write authorization operations (issue #1335).

Handles verification and orchestration; persistence delegated to repositories.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import ProductionWriteAuthorizationsRepo
from juli_backend.services.tiktok.credential_binding import (
    verify_capability_binding,
)


class ProductionWriteAuthorizationService:
    """Service for issuing and managing production write authorizations."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = ProductionWriteAuthorizationsRepo(session)

    async def issue(
        self,
        shop_id,
        tiktok_product_id: str,
        mutation_kind: str,
        capability: str,
        shop_cipher: str,
        authorized_by: str,
        reason: str | None = None,
        ttl_hours: int = 24,
    ):
        """Issue an authorization after verifying credential binding.

        Verifies the credential for this shop and capability first, then
        delegates persistence to the repository. Raises CredentialBindingError
        if the credential is mis-bound.
        """
        # Verify credential binding FIRST (service layer responsibility)
        await verify_capability_binding(
            self._session, capability=capability, shop_cipher=shop_cipher
        )

        # Calculate expiration time (service orchestration responsibility)
        expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)

        # Delegate persistence to repo (repository layer responsibility)
        return await self._repo.issue(
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
            mutation_kind=mutation_kind,
            capability=capability,
            shop_cipher=shop_cipher,
            authorized_by=authorized_by,
            reason=reason,
            expires_at=expires_at,
        )

    async def lookup(self, shop_id, tiktok_product_id: str, mutation_kind: str):
        """Lookup an unconsumed, unexpired, unrevoked authorization."""
        return await self._repo.lookup(
            shop_id=shop_id,
            tiktok_product_id=tiktok_product_id,
            mutation_kind=mutation_kind,
        )

    async def consume(self, authorization_id, run_id):
        """Atomically consume an authorization."""
        return await self._repo.consume(authorization_id, run_id=run_id)

    async def revoke(self, authorization_id, reason: str | None = None):
        """Revoke an authorization, preserving it for audit."""
        return await self._repo.revoke(authorization_id, reason=reason)
