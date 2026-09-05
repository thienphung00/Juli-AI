"""Public Demo Analytics read API — unauthenticated masked envelope (#531)."""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope
from juli_backend.services.gold_kpi_cache import (
    get_gold_kpi_envelope,
    get_shared_redis_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

ChartRange = Literal["7d", "30d", "90d"]
_RANGE_DAYS: dict[ChartRange, int] = {"7d": 7, "30d": 30, "90d": 90}


def get_demo_reference_shop_id() -> uuid.UUID:
    """Resolve the server-bound reference shop for public Demo reads."""
    raw = require_env("DEMO_REFERENCE_SHOP_ID")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo reference shop is not configured",
        ) from exc


def get_demo_redis_client() -> Any | None:
    return get_shared_redis_client()


def _parse_computed_at(payload: dict[str, Any]) -> datetime:
    raw = payload.get("computed_at")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw)
    return datetime.now(tz=UTC)


def _apply_chart_range(payload: dict[str, Any], chart_range: ChartRange) -> dict[str, Any]:
    """Trim KPI series to the requested client chart window."""
    result = copy.deepcopy(payload)
    window_days = _RANGE_DAYS[chart_range]
    cutoff = _parse_computed_at(result).date() - timedelta(days=window_days - 1)
    cutoff_str = cutoff.isoformat()

    kpis = result.get("kpis")
    if not isinstance(kpis, dict):
        return result

    for kpi in kpis.values():
        if not isinstance(kpi, dict) or kpi.get("availability") != "available":
            continue
        series = kpi.get("series")
        if not isinstance(series, list):
            continue
        kpi["series"] = [
            point
            for point in series
            if isinstance(point, dict)
            and isinstance(point.get("t"), str)
            and point["t"] >= cutoff_str
        ]
    return result


@router.get("/analytics")
async def get_demo_analytics(
    range: ChartRange | None = Query(None, description="Optional chart window (7d, 30d, 90d)"),
    shop_id: str | None = Query(None, description="Rejected — reference shop is server-bound"),
    session: AsyncSession = Depends(get_session),
    reference_shop_id: uuid.UUID = Depends(get_demo_reference_shop_id),
    redis_client: Any | None = Depends(get_demo_redis_client),
) -> dict[str, Any]:
    """Return masked Gold KPI envelope for the configured reference shop (#633 cutover)."""
    if shop_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shop_id is not accepted on public demo endpoints",
        )

    # SCOPE THE READ. This is a public, unauthenticated route, so nothing
    # upstream sets a tenant GUC — `get_session` sets it only via
    # `get_active_shop` or a task wrapper, and this route depends on
    # `get_demo_reference_shop_id` instead. `gold.kpi_envelopes` is RLS'd on
    # `shop_id = app_current_shop_id()`, so with no context the policy matched
    # nothing and this returned 404 in production from the #1339 cutover
    # onward (#1613).
    #
    # It worked before only because the API connected as the table's OWNER,
    # which Postgres exempts from RLS. That exemption was load-bearing and
    # invisible. Scoping to the shop the route has already resolved is the
    # honest fix: the demo IS one server-bound shop, so saying so restores the
    # read without granting anything. Do NOT "fix" this with a permissive or
    # anon policy on gold.kpi_envelopes — that reopens what the isolation work
    # exists to prove, to serve one masked row.
    async with with_shop_scope(session, reference_shop_id):
        envelope = await get_gold_kpi_envelope(
            session,
            reference_shop_id,
            redis_client=redis_client,
        )
    if envelope is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analytics envelope not available for demo shop",
        )

    payload = envelope.payload
    if range is not None:
        payload = _apply_chart_range(payload, range)

    masked = mask_public_analytics_envelope(payload)
    logger.info(
        "demo_analytics_read",
        extra={
            "reference_shop_id": str(reference_shop_id),
            "cache_client_configured": redis_client is not None,
            "range": range,
        },
    )
    return masked
