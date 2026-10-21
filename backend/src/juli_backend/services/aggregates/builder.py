"""Build feature aggregates from production-synced Postgres tables only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop
from juli_backend.repositories.repos import (
    InventoryRepo,
    OrderItemsRepo,
    OrdersRepo,
    ProductsRepo,
    ReturnsRepo,
    TikTokSyncStateRepo,
)
from juli_backend.services.aggregates.computed_kpis import ROLLING_WINDOW_DAYS, compute_all_kpis
from juli_backend.services.aggregates.health_source import resolve_health_snapshot
from juli_backend.services.aggregates.shop_profile import classify_shop_profile
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    ShopLifecycleContext,
    ShopProfileSignals,
)

SYNCED_DATA_SOURCES = frozenset(
    {
        "orders",
        "products",
        "returns",
        "order_items",
        "inventory_items",
        "analytics_performance_intervals",
        "tiktok_sync_state",
    }
)


#: The only interval columns ``compute_analytics_kpis`` reads (D72.3).
_ANALYTICS_KPI_COLUMNS = (
    AnalyticsPerformanceInterval.grain,
    AnalyticsPerformanceInterval.start_date,
    AnalyticsPerformanceInterval.gmv,
    AnalyticsPerformanceInterval.conversion_rate,
    AnalyticsPerformanceInterval.ctr,
    AnalyticsPerformanceInterval.impressions,
)


async def _rolling_window_intervals(
    session: AsyncSession, shop_id: uuid.UUID, anchor: datetime, limit: int
) -> list[AnalyticsPerformanceInterval]:
    """The shop's interval rows inside the KPI rolling window, KPI columns only (D72.3).

    ``compute_analytics_kpis`` ignores every row outside
    ``[anchor - ROLLING_WINDOW_DAYS, anchor]`` (by ``start_date``), so reading the
    shop's newest ``limit`` rows of every grain and column -- the whole table for a
    shop with history -- only to drop most of them in Python was pure egress.
    """
    first = (anchor - timedelta(days=ROLLING_WINDOW_DAYS)).date()
    stmt = (
        select(AnalyticsPerformanceInterval)
        .options(load_only(*_ANALYTICS_KPI_COLUMNS))
        .where(
            AnalyticsPerformanceInterval.shop_id == shop_id,
            AnalyticsPerformanceInterval.start_date >= first,
            AnalyticsPerformanceInterval.start_date <= anchor.date(),
        )
        .order_by(AnalyticsPerformanceInterval.start_date.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _shop_age_days(created_at: datetime | None) -> int:
    if created_at is None:
        return 0
    anchor = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - anchor
    return max(delta.days, 0)


def _promotion_activity_partition_present(sync_state: dict) -> bool:
    """True when A-25 promotion activity watermark exists in persisted sync state."""
    return sync_state.get("promotion_activity_last_sync_at") is not None


async def build_feature_aggregates(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    lifecycle: ShopLifecycleContext | None = None,
    list_limit: int = 10_000,
    computed_at: datetime | None = None,
) -> FeatureAggregateSnapshot:
    """Roll up KPIs from synced commerce + analytics Postgres tables; rules-only profile."""
    lifecycle = lifecycle or ShopLifecycleContext()
    anchor = computed_at or datetime.now(UTC)

    shop = await session.get(Shop, shop_id)
    if shop is None:
        raise NotFound(f"Shop {shop_id} not found")

    orders = await OrdersRepo(session).list(shop_id, limit=list_limit)
    products = await ProductsRepo(session).list(shop_id, limit=list_limit)
    returns = await ReturnsRepo(session).list(shop_id, limit=list_limit)
    order_items = await OrderItemsRepo(session).list(shop_id, limit=list_limit)
    inventory_items = await InventoryRepo(session).list(shop_id, limit=list_limit)
    # compute_all_kpis reads a naive anchor as UTC; so does the window.
    kpi_anchor = anchor if anchor.tzinfo else anchor.replace(tzinfo=UTC)
    analytics_intervals = await _rolling_window_intervals(session, shop_id, kpi_anchor, list_limit)
    sync_state = await TikTokSyncStateRepo(session).load(shop_id)
    promotion_activity_present = _promotion_activity_partition_present(sync_state)

    order_count = len(orders)
    product_count = len(products)
    return_count = len(returns)

    total_order_value = sum((o.total_amount for o in orders), Decimal("0"))
    total_product_revenue = sum((p.revenue for p in products), Decimal("0"))
    total_units_sold = sum((p.units_sold for p in products), 0)

    return_rate_proxy: float | None = None
    if order_count > 0:
        return_rate_proxy = float(Decimal(return_count) / Decimal(order_count))

    computed_kpis = compute_all_kpis(
        shop_id=shop_id,
        orders=orders,
        order_items=order_items,
        products=products,
        inventory_items=inventory_items,
        returns=returns,
        anchor=anchor,
        analytics_intervals=analytics_intervals,
        promotion_activity_partition_present=promotion_activity_present,
    )

    ad_revenue_total = Decimal("0")
    if promotion_activity_present and computed_kpis.analytics_revenue_denominator is not None:
        ad_revenue_total = computed_kpis.analytics_revenue_denominator

    profile_signals = ShopProfileSignals(
        probation_status=lifecycle.probation_status,
        shop_age_days=_shop_age_days(shop.created_at),
        product_gmv_total=total_product_revenue,
        product_units_sold_total=total_units_sold,
        ad_revenue_total=ad_revenue_total,
    )
    shop_profile = classify_shop_profile(profile_signals)

    health = resolve_health_snapshot(
        health_data_source=lifecycle.health_data_source,
        api_sps_score=lifecycle.api_sps_score,
        api_vp_score=lifecycle.api_vp_score,
        api_ahr_score=lifecycle.api_ahr_score,
        order_count=order_count,
        return_count=return_count,
        product_count=product_count,
    )

    return FeatureAggregateSnapshot(
        shop_id=shop_id,
        shop_profile=shop_profile,
        health_data_source=health.health_data_source,
        sps_score=health.sps_score,
        vp_score=health.vp_score,
        ahr_score=health.ahr_score,
        order_count=order_count,
        product_count=product_count,
        return_count=return_count,
        total_order_value=total_order_value,
        total_product_revenue=total_product_revenue,
        total_units_sold=total_units_sold,
        return_rate_proxy=return_rate_proxy,
        data_sources=sorted(SYNCED_DATA_SOURCES),
        computed_kpis=computed_kpis,
        proxy_signals=health.proxy_signals,
    )
