"""Single-use authorizations for production mutations (#1335).

An authorization is issued for one ``(shop, product, mutation_kind)``, expires,
and is consumed exactly once. Revocation keeps the row for audit. The service
layer decides *whether* to issue; this repository only records and enforces
the single-use claim.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import ProductionWriteAuthorization
from juli_backend.repositories._base import ShopScopedRepo, utc_now_naive


class ProductionWriteAuthorizationsRepo(ShopScopedRepo[ProductionWriteAuthorization]):
    _model = ProductionWriteAuthorization

    async def issue(
        self,
        shop_id: uuid.UUID,
        tiktok_product_id: str,
        mutation_kind: str,
        authorized_by: str,
        expires_at: datetime,
        reason: str | None = None,
    ) -> ProductionWriteAuthorization:
        """Persist an authorization the service layer has already verified."""
        return await self._add(
            ProductionWriteAuthorization(
                shop_id=shop_id,
                tiktok_product_id=tiktok_product_id,
                mutation_kind=mutation_kind,
                authorized_by=authorized_by,
                reason=reason,
                expires_at=expires_at,
            )
        )

    async def lookup(
        self, shop_id: uuid.UUID, tiktok_product_id: str, mutation_kind: str
    ) -> ProductionWriteAuthorization | None:
        """The live authorization for this mutation, or ``None``.

        Live means: matches all three scoping fields, not yet expired, not yet
        consumed, not revoked.
        """
        stmt = self._scoped(
            shop_id,
            ProductionWriteAuthorization.tiktok_product_id == tiktok_product_id,
            ProductionWriteAuthorization.mutation_kind == mutation_kind,
            ProductionWriteAuthorization.expires_at > utc_now_naive(),
            ProductionWriteAuthorization.consumed_at.is_(None),
            ProductionWriteAuthorization.revoked_at.is_(None),
        ).limit(1)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def consume(
        self, authorization_id: uuid.UUID, run_id: uuid.UUID
    ) -> ProductionWriteAuthorization:
        """Claim the authorization for ``run_id``; exactly one caller can win.

        ``SELECT ... FOR UPDATE`` serialises concurrent claimants. The loser
        wakes up to a row that is already consumed and gets :class:`NotFound`,
        the same signal as a missing row: from its point of view there is no
        authorization left to use.
        """
        stmt = (
            select(ProductionWriteAuthorization)
            .where(ProductionWriteAuthorization.id == authorization_id)
            .with_for_update()
        )
        authorization = await self._one_or_none(stmt)
        if authorization is None:
            raise NotFound(f"Authorization {authorization_id} not found")
        if authorization.consumed_at is not None:
            raise NotFound(
                f"Authorization {authorization_id} already consumed "
                f"by run {authorization.consumed_by_run_id}"
            )
        authorization.consumed_at = utc_now_naive()
        authorization.consumed_by_run_id = run_id
        await self._session.flush()
        return authorization

    async def revoke(
        self, authorization_id: uuid.UUID, reason: str | None = None
    ) -> ProductionWriteAuthorization:
        """Invalidate for future lookups while keeping the row for audit."""
        authorization = await self._session.get(ProductionWriteAuthorization, authorization_id)
        if authorization is None:
            raise NotFound(f"Authorization {authorization_id} not found")
        authorization.revoked_at = utc_now_naive()
        authorization.revoke_reason = reason
        await self._session.flush()
        return authorization


__all__ = ["ProductionWriteAuthorizationsRepo"]
