"""GMV (TikTok) KPI builder from shop-grain analytics intervals."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsPerformanceInterval

GMV_TIKTOK_LABEL = "GMV (TikTok)"


async def build_gmv_tiktok_kpi(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> dict[str, Any]:
    """Return ``kpis.gmv_tiktok`` entry from warm shop-grain interval rows."""
    stmt = (
        select(AnalyticsPerformanceInterval)
        .where(
            AnalyticsPerformanceInterval.shop_id == shop_id,
            AnalyticsPerformanceInterval.grain == "shop",
            AnalyticsPerformanceInterval.gmv.is_not(None),
        )
        .order_by(AnalyticsPerformanceInterval.start_date)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    if not rows:
        return {"availability": "unavailable", "label": GMV_TIKTOK_LABEL}

    series = [
        {"t": row.start_date.isoformat(), "v": float(row.gmv)}
        for row in rows
        if row.gmv is not None
    ]
    return {
        "availability": "available",
        "label": GMV_TIKTOK_LABEL,
        "series": series,
    }
