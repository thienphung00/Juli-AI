"""Build feature aggregates from production-synced Postgres tables only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import Shop
from juli_backend.repositories.repos import (
    InventoryRepo,
    OrderItemsRepo,
    OrdersRepo,
    ProductsRepo,
    ReturnsRepo,
)
from juli_backend.services.aggregates.computed_kpis import compute_all_kpis
from juli_backend.services.aggregates.health_source import resolve_health_snapshot
from juli_backend.services.aggregates.shop_profile import classify_shop_profile
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    ShopLifecycleContext,
    ShopProfileSignals,
)

SYNCED_DATA_SOURCES = frozenset(
    {"orders", "products", "returns", "order_items", "inventory_items"}
)


def _shop_age_days(created_at: datetime | None) -> int:
    if created_at is None:
        return 0
    anchor = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - anchor
    return max(delta.days, 0)


async def build_feature_aggregates(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    lifecycle: ShopLifecycleContext | None = None,
    list_limit: int = 10_000,
    computed_at: datetime | None = None,
) -> FeatureAggregateSnapshot:
    """Roll up KPIs from synced commerce tables; rules-only profile and health."""
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

    order_count = len(orders)
    product_count = len(products)
    return_count = len(returns)

    total_order_value = sum((o.total_amount for o in orders), Decimal("0"))
    total_product_revenue = sum((p.revenue for p in products), Decimal("0"))
    total_units_sold = sum((p.units_sold for p in products), 0)

    return_rate_proxy: float | None = None
    if order_count > 0:
        return_rate_proxy = float(Decimal(return_count) / Decimal(order_count))

    profile_signals = ShopProfileSignals(
        probation_status=lifecycle.probation_status,
        shop_age_days=_shop_age_days(shop.created_at),
        product_gmv_total=total_product_revenue,
        product_units_sold_total=total_units_sold,
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

    computed_kpis = compute_all_kpis(
        shop_id=shop_id,
        orders=orders,
        order_items=order_items,
        products=products,
        inventory_items=inventory_items,
        returns=returns,
        anchor=anchor,
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
