"""Consent grants for tests whose subject is not consent itself (ADR-116 §2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.consent import DataUseConsent
from juli_backend.services.consent import grant_consent

GRANTED_AT = datetime(2026, 10, 26, 3, 0)


async def grant_service_consent(session: AsyncSession, shop_id: uuid.UUID) -> DataUseConsent:
    """An open ``service`` grant for ``shop_id``, as a signed contract would record it."""
    return await grant_consent(
        session,
        shop_id,
        scope="service",
        method="contract_paper",
        terms_version="test-terms-v1",
        evidence_ref="tests/contract.pdf",
        granted_by="test client",
        granted_at=GRANTED_AT,
    )
