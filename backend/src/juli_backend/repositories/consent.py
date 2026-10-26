"""Per-shop data-use consent grants (ADR-116 §2, D76).

A grant is recorded once and never edited; a withdrawal sets ``revoked_at`` on
the open grant. The service layer (``services.consent``) decides whether a use
is allowed; this repository only records grants and finds the open one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from juli_backend.database.exceptions import NotFound
from juli_backend.models.consent import DataUseConsent
from juli_backend.repositories._base import ShopScopedRepo


class DataUseConsentsRepo(ShopScopedRepo[DataUseConsent]):
    _model = DataUseConsent

    async def find_open(self, shop_id: uuid.UUID, scope: str) -> DataUseConsent | None:
        """The shop's open (not revoked) grant of ``scope``, or ``None``."""
        return await self._one_or_none(
            self._scoped(
                shop_id,
                DataUseConsent.scope == scope,
                DataUseConsent.revoked_at.is_(None),
            )
        )

    async def record_grant(
        self,
        shop_id: uuid.UUID,
        *,
        scope: str,
        method: str,
        terms_version: str,
        evidence_ref: str,
        evidence_sha256: str | None,
        granted_by: str,
        granted_at: datetime,
    ) -> DataUseConsent:
        """Persist a grant the service layer has already validated."""
        return await self._add(
            DataUseConsent(
                shop_id=shop_id,
                scope=scope,
                method=method,
                terms_version=terms_version,
                evidence_ref=evidence_ref,
                evidence_sha256=evidence_sha256,
                granted_by=granted_by,
                granted_at=granted_at,
            )
        )

    async def mark_revoked(
        self, shop_id: uuid.UUID, scope: str, revoked_at: datetime
    ) -> DataUseConsent:
        """Set ``revoked_at`` on the open grant of ``scope``; raises when there is none."""
        grant = await self.find_open(shop_id, scope)
        if grant is None:
            raise NotFound(f"DataUseConsent open grant of {scope} not found")
        grant.revoked_at = revoked_at
        await self._session.flush()
        return grant
