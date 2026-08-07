"""Gold KPI envelope serving helpers — contract + persistence orchestration (#606)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    GoldKpiEnvelope,
    Order,
    Shop,
)
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
    Computes ctor as GMV-weighted click_order_rate from product-grain analytics.
    Computes live_hours from shop-grain analytics.
    Emits a date-bucketed series for gmv_tiktok (#633).
    """
    computed_at = computed_at or datetime.now(tz=UTC)

    # Fetch shop for identity information
    shop_stmt = select(Shop).where(Shop.id == shop_id)
    shop_result = await session.execute(shop_stmt)
    shop = shop_result.scalars().first()

    # Fetch all orders for the shop
    stmt = select(Order).where(Order.shop_id == shop_id)
    result = await session.execute(stmt)
    orders = result.scalars().all()

    # Compute metrics
    gmv_value: float | None = None
    aov_value: float | None = None
    cancellation_value: float | None = None
    gmv_series: list[dict[str, Any]] = []

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

        # Build date-bucketed series for gmv_tiktok (#633)
        if non_cancelled_orders:
            # Bucket non-cancelled orders by date (using tiktok_created_at or update_time)
            daily_gmv: dict[date, Decimal] = defaultdict(Decimal)
            for order in non_cancelled_orders:
                # Use tiktok_created_at if available, otherwise update_time
                order_date = None
                if order.tiktok_created_at:
                    order_date = order.tiktok_created_at.date()
                elif order.update_time:
                    order_date = order.update_time.date()

                if order_date and order.total_amount:
                    daily_gmv[order_date] += order.total_amount

            # Sort by date and build series
            sorted_dates = sorted(daily_gmv.keys())
            gmv_series = [{"t": d.isoformat(), "v": float(daily_gmv[d])} for d in sorted_dates]

    # Build the kpis map with proper typing
    kpis: dict[str, dict[str, Any]] = {}

    # GMV: Gross Merchandise Value
    gmv_kpi: dict[str, Any] = {
        "availability": "available" if gmv_value is not None else "unavailable",
        "label": "GMV (TikTok)",
    }
    if gmv_value is not None:
        gmv_kpi["value"] = gmv_value
    # Always emit series, even if empty (for consistency with legacy contract)
    gmv_kpi["series"] = gmv_series
    kpis["gmv_tiktok"] = gmv_kpi

    # AOV: Average Order Value
    aov_kpi: dict[str, Any] = {
        "availability": "available" if aov_value is not None else "unavailable",
        "label": "AOV",
    }
    if aov_value is not None:
        aov_kpi["value"] = aov_value
    kpis["aov"] = aov_kpi

    # CTOR: Click-to-Order Rate (GMV-weighted from product-grain analytics)
    ctor_value: float | None = None
    stmt_ctor = select(AnalyticsPerformanceInterval).where(
        (AnalyticsPerformanceInterval.shop_id == shop_id)
        & (AnalyticsPerformanceInterval.grain == "product")
    )
    result_ctor = await session.execute(stmt_ctor)
    product_intervals = result_ctor.scalars().all()

    if product_intervals:
        # Calculate GMV-weighted average of click_order_rate
        total_gmv = Decimal("0")
        weighted_sum = Decimal("0")

        for interval in product_intervals:
            if interval.gmv is not None and interval.click_order_rate is not None:
                total_gmv += interval.gmv
                weighted_sum += interval.gmv * interval.click_order_rate

        if total_gmv > 0:
            ctor_value = float(weighted_sum / total_gmv)

    ctor_kpi: dict[str, Any] = {
        "availability": "available" if ctor_value is not None else "unavailable",
        "label": "CTOR (click→đơn)",
    }
    if ctor_value is not None:
        ctor_kpi["value"] = ctor_value
    kpis["ctor"] = ctor_kpi

    # Live Hours (from shop-grain analytics)
    # Note: live_hours is unbounded across all history; gmv_tiktok is bounded by
    # the #744 page cap on silver orders. This difference is accepted per review.
    live_hours_value: float | None = None
    stmt_live = select(AnalyticsPerformanceInterval).where(
        (AnalyticsPerformanceInterval.shop_id == shop_id)
        & (AnalyticsPerformanceInterval.grain == "shop")
    )
    result_live = await session.execute(stmt_live)
    shop_intervals = result_live.scalars().all()

    if shop_intervals:
        # Sum live_hours from all shop-grain rows
        total_live_hours = Decimal("0")

        for interval in shop_intervals:
            if interval.live_hours is not None:
                total_live_hours += interval.live_hours

        # Report sum as-is, even if zero (legitimate measurement when rows exist).
        # Only unavailable when no rows exist (missing data, per ADR-044).
        live_hours_value = float(total_live_hours)

    live_hours_kpi: dict[str, Any] = {
        "availability": "available" if live_hours_value is not None else "unavailable",
        "label": "LIVE hours",
    }
    if live_hours_value is not None:
        live_hours_kpi["value"] = live_hours_value
    kpis["live_hours"] = live_hours_kpi

    # Cancellation Rate
    cancellation_kpi: dict[str, Any] = {
        "availability": "available" if cancellation_value is not None else "unavailable",
        "label": "Cancellation rate",
    }
    if cancellation_value is not None:
        cancellation_kpi["value"] = cancellation_value
    kpis["cancellation_rate"] = cancellation_kpi

    # Build identity block for masking (preserves PII for local processing,
    # masked before public response via mask_public_analytics_envelope)
    identity: dict[str, Any] = {}
    if shop:
        identity["shop_display_name"] = shop.shop_name or f"Shop {shop.id}"

    return {
        "envelope_version": ENVELOPE_VERSION,
        "kind": "analytics",
        "shop_id": str(shop_id),
        "computed_at": computed_at.isoformat(),
        "currency": currency,
        "identity": identity,
        "kpis": kpis,
        "meta": {
            "source_partitions": ["silver.orders", "analytics_performance_intervals"],
            "notes": ["A1 five-KPI precompute (#630)"],
        },
    }


async def write_demo_main_kpis_envelope(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> GoldKpiEnvelope:
    """Compute and persist the five Demo Main KPIs gold envelope (#630).

    Sole gold.kpi_envelopes writer entrypoint for this payload — keeps the
    upsert inside this module per the medallion one-writer ownership gate
    (agent-runtime/scripts/ci/medallion_one_writer.py).

    On successful upsert, refreshes the Redis cache (#631) to keep Demo reads fast.
    Cache refresh fails gracefully (logged) and does not block the write.
    """
    computed_at = datetime.now(tz=UTC)
    payload = await compute_demo_main_kpis_payload(session, shop_id, computed_at=computed_at)
    repo = GoldKpiEnvelopesRepo(session)
    envelope = await repo.upsert(
        shop_id=shop_id,
        envelope_version=ENVELOPE_VERSION,
        payload=payload,
        computed_at=computed_at,
    )

    # Refresh Redis cache after successful Postgres upsert (fail-open, non-blocking)
    from juli_backend.services.gold_kpi_cache import (
        get_shared_redis_client,
        refresh_gold_kpi_envelope_cache,
    )

    redis_client = get_shared_redis_client()
    await refresh_gold_kpi_envelope_cache(shop_id, envelope, redis_client=redis_client)

    return envelope
