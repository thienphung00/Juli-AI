"""Gold KPI envelope serving helpers — contract + persistence orchestration (#606)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import GoldKpiEnvelope, Order
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


async def compute_demo_main_kpis_payload(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    computed_at: datetime | None = None,
    currency: str = "VND",
) -> dict[str, Any]:
    """Build gold envelope payload with computed five Demo Main KPIs (#630, ADR-049).

    Computes gmv_tiktok, aov, cancellation_rate from silver orders.
    Marks ctor, live_hours as unavailable (analytics domain not synced yet).
    """
    computed_at = computed_at or datetime.now(tz=UTC)

    # Fetch all orders for the shop
    stmt = select(Order).where(Order.shop_id == shop_id)
    result = await session.execute(stmt)
    orders = result.scalars().all()

    # Compute metrics
    gmv_value: float | None = None
    aov_value: float | None = None
    cancellation_value: float | None = None

    if orders:
        # Separate cancelled and non-cancelled orders
        cancelled_statuses = ("CANCELLED", "CANCELED")
        non_cancelled_orders = [
            o for o in orders if not (o.status and o.status.upper() in cancelled_statuses)
        ]
        cancelled_count = len(orders) - len(non_cancelled_orders)
        total_count = len(orders)

        # GMV: sum of non-cancelled orders
        if non_cancelled_orders:
            total_gmv = sum(
                order.total_amount for order in non_cancelled_orders if order.total_amount
            )
            gmv_value = float(total_gmv) if total_gmv else None

        # Cancellation rate: cancelled / total
        cancellation_value = cancelled_count / total_count if total_count > 0 else None

        # AOV: GMV / number of non-cancelled orders
        if non_cancelled_orders and gmv_value:
            aov_value = gmv_value / len(non_cancelled_orders) if gmv_value else None

    # Build the kpis map with proper typing
    kpis: dict[str, dict[str, Any]] = {}

    # GMV: Gross Merchandise Value
    gmv_kpi: dict[str, Any] = {
        "availability": "available" if gmv_value is not None else "unavailable",
        "label": "GMV (TikTok)",
    }
    if gmv_value is not None:
        gmv_kpi["value"] = gmv_value
    kpis["gmv_tiktok"] = gmv_kpi

    # AOV: Average Order Value
    aov_kpi: dict[str, Any] = {
        "availability": "available" if aov_value is not None else "unavailable",
        "label": "AOV",
    }
    if aov_value is not None:
        aov_kpi["value"] = aov_value
    kpis["aov"] = aov_kpi

    # CTOR: Click-to-Order Rate (unavailable - analytics domain)
    kpis["ctor"] = {
        "availability": "unavailable",
        "label": "CTOR (click→đơn)",
    }

    # Live Hours (unavailable - analytics domain)
    kpis["live_hours"] = {
        "availability": "unavailable",
        "label": "LIVE hours",
    }

    # Cancellation Rate
    cancellation_kpi: dict[str, Any] = {
        "availability": "available" if cancellation_value is not None else "unavailable",
        "label": "Cancellation rate",
    }
    if cancellation_value is not None:
        cancellation_kpi["value"] = cancellation_value
    kpis["cancellation_rate"] = cancellation_kpi

    return {
        "envelope_version": ENVELOPE_VERSION,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": currency,
        "kpis": kpis,
        "meta": {
            "source_partitions": ["silver.orders"],
            "notes": ["A1 five-KPI precompute (#630)"],
        },
    }
