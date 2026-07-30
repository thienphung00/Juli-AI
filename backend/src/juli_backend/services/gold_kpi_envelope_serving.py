"""Gold KPI envelope serving helpers — contract + persistence orchestration (#606)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import GoldKpiEnvelope
from juli_backend.repositories.repos import GoldKpiEnvelopesRepo
from juli_backend.services.gold_kpi_envelope_contract import (
    ENVELOPE_VERSION,
    build_honest_unavailable_shell_payload,
)


async def seed_unavailable_shell(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> GoldKpiEnvelope:
    """Seed honest-unavailable ADR-044 shell when no gold row exists."""
    repo = GoldKpiEnvelopesRepo(session)
    existing = await repo.get(shop_id)
    if existing is not None:
        return existing

    when = datetime.now(tz=UTC)
    payload = build_honest_unavailable_shell_payload(shop_id=shop_id, computed_at=when)
    return await repo.upsert(
        shop_id=shop_id,
        envelope_version=ENVELOPE_VERSION,
        payload=payload,
        computed_at=when,
    )
