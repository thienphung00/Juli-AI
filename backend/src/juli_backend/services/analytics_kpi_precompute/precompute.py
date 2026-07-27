"""Shop-scoped Analytics KPI precompute orchestrator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsKpiEnvelope, AnalyticsPerformanceInterval
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo
from juli_backend.services.analytics_kpi_precompute.gmv import build_gmv_tiktok_kpi
from juli_backend.services.analytics_kpi_precompute.product_live import (
    KpiEnvelopeEntry,
    build_live_performance_kpi,
    build_product_funnel_kpi,
)

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
        "meta": {"source_partitions": [], "notes": []},
    }


def _kpi_entry_to_dict(entry: KpiEnvelopeEntry) -> dict[str, Any]:
    result: dict[str, Any] = {
        "availability": entry.availability,
        "label": entry.label,
    }
    if entry.availability == "available":
        result["series"] = entry.series
    return result


def _source_partitions_for_kpis(
    *,
    gmv_kpi: dict[str, Any],
    product_funnel_kpi: dict[str, Any],
    live_performance_kpi: dict[str, Any],
) -> list[str]:
    partitions: list[str] = []
    if gmv_kpi.get("availability") == "available":
        partitions.append("A-36")
    if product_funnel_kpi.get("availability") == "available":
        partitions.append("A-34")
    if live_performance_kpi.get("availability") == "available":
        partitions.extend(["A-28", "A-29"])
    return partitions


async def _load_shop_intervals(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> list[AnalyticsPerformanceInterval]:
    stmt = (
        select(AnalyticsPerformanceInterval)
        .where(AnalyticsPerformanceInterval.shop_id == shop_id)
        .order_by(AnalyticsPerformanceInterval.start_date)
    )
    return list((await session.execute(stmt)).scalars().all())


async def precompute_shop_analytics_kpis(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    computed_at: datetime | None = None,
) -> AnalyticsKpiEnvelope:
    """Read warm interval rows, merge KPI slices into analytics envelope, upsert SoT."""
    when = computed_at or datetime.now(tz=UTC)
    repo = AnalyticsKpiEnvelopesRepo(session)
    existing = await repo.get_by_kind(shop_id, ANALYTICS_KIND)

    intervals = await _load_shop_intervals(session, shop_id)
    gmv_kpi = await build_gmv_tiktok_kpi(session, shop_id)
    product_funnel_kpi = _kpi_entry_to_dict(build_product_funnel_kpi(intervals))
    live_performance_kpi = _kpi_entry_to_dict(build_live_performance_kpi(intervals))

    if existing is not None:
        base = dict(existing.payload)
    else:
        base = _base_envelope_payload(shop_id=shop_id, computed_at=when)

    base["computed_at"] = when.isoformat()
    merged_kpis = {
        **base.get("kpis", {}),
        "gmv_tiktok": gmv_kpi,
        "product_funnel": product_funnel_kpi,
        "live_performance": live_performance_kpi,
    }
    meta = dict(base.get("meta", {}))
    meta["source_partitions"] = _source_partitions_for_kpis(
        gmv_kpi=gmv_kpi,
        product_funnel_kpi=product_funnel_kpi,
        live_performance_kpi=live_performance_kpi,
    )
    payload = {**base, "kpis": merged_kpis, "meta": meta}

    return await repo.upsert(
        shop_id=shop_id,
        kind=ANALYTICS_KIND,
        envelope_version=ENVELOPE_VERSION,
        payload=payload,
        computed_at=when,
    )
