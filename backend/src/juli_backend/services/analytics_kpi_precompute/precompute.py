"""Shop-scoped Analytics KPI precompute orchestrator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsKpiEnvelope
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo
from juli_backend.services.analytics_kpi_precompute.gmv import build_gmv_tiktok_kpi

ANALYTICS_KIND = "analytics"
ENVELOPE_VERSION = 1


def _base_envelope_payload(
    *,
    shop_id: uuid.UUID,
    computed_at: datetime,
    currency: str = "VND",
) -> dict[str, Any]:
    return {
        "envelope_version": ENVELOPE_VERSION,
        "kind": ANALYTICS_KIND,
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": currency,
        "kpis": {},
        "meta": {"source_partitions": ["A-36"], "notes": []},
    }


async def precompute_shop_analytics_kpis(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    computed_at: datetime | None = None,
) -> AnalyticsKpiEnvelope:
    """Read warm interval rows, merge GMV KPI into analytics envelope, upsert SoT."""
    when = computed_at or datetime.now(tz=UTC)
    repo = AnalyticsKpiEnvelopesRepo(session)
    existing = await repo.get_by_kind(shop_id, ANALYTICS_KIND)

    gmv_kpi = await build_gmv_tiktok_kpi(session, shop_id)

    if existing is not None:
        base = dict(existing.payload)
    else:
        base = _base_envelope_payload(shop_id=shop_id, computed_at=when)

    base["computed_at"] = when.isoformat()
    merged_kpis = {**base.get("kpis", {}), "gmv_tiktok": gmv_kpi}
    payload = {**base, "kpis": merged_kpis}

    return await repo.upsert(
        shop_id=shop_id,
        kind=ANALYTICS_KIND,
        envelope_version=ENVELOPE_VERSION,
        payload=payload,
        computed_at=when,
    )
