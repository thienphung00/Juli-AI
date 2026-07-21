"""Pure computed KPI formulas over synced Postgres commerce entities (#374).

Formulas live here; ``signals.py`` applies thresholds and visual_layer one-liners only.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    InventoryItem,
    Order,
    OrderItem,
    Product,
    Return,
)
from juli_backend.services.aggregates.thresholds import ORDER_DISPATCH_SLA_HOURS

ROLLING_WINDOW_DAYS = 30

_CANCELLED_STATUSES = frozenset({"CANCELLED", "CANCELED"})


@dataclass(frozen=True)
class ComputedKpiMetrics:
    """Typed computed KPI fields embedded in FeatureAggregateSnapshot."""

    total_units_sold_30d: int
    avg_on_hand_inventory: float | None
    sku_count_with_inventory: int
    stockout_sku_count: int
    orders_with_ship_time_30d: int
    orders_fulfilled_without_seller_fault_30d: int
    orders_at_sla_risk_count: int
    seller_fault_order_count_30d: int
    order_items_count_30d: int
    top_category_name: str | None
    unique_buyers_30d: int
    repeat_buyers_30d: int
    return_rate_30d: float | None
    inventory_turnover: float | None
    dsi_days: float | None
    stockout_rate: float | None
    fulfillment_accuracy_rate: float | None
    seller_fault_cancellation_rate: float | None
    conversion_rate_by_category: float | None
    repeat_purchase_rate: float | None
    after_sales_handling_time_hours: float | None
    csat_proxy_score: float | None
    shop_traffic_conversion_rate: float | None
    analytics_shop_gmv_30d: Decimal | None
    analytics_product_gmv_30d: Decimal | None
    analytics_sku_gmv_30d: Decimal | None
    analytics_weighted_product_ctr: float | None
    promotion_activity_partition_present: bool
    analytics_revenue_denominator: Decimal | None
    analytics_spend_denominator: Decimal | None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _in_rolling_window(
    value: datetime | None,
    *,
    anchor: datetime,
    days: int = ROLLING_WINDOW_DAYS,
) -> bool:
    if value is None:
        return False
    window_start = anchor - timedelta(days=days)
    stamped = _ensure_utc(value)
    return window_start <= stamped <= anchor


def _order_reference_time(order: Order) -> datetime | None:
    return order.payment_time or order.tiktok_created_at or order.created_at


def _is_seller_fault_cancel(order: Order) -> bool:
    return bool(order.is_seller_fault) and order.status.upper() in _CANCELLED_STATUSES


def compute_inventory_turnover(
    total_units_sold_30d: int,
    avg_on_hand_inventory: float | None,
) -> float | None:
    if avg_on_hand_inventory is None or avg_on_hand_inventory <= 0:
        return None
    if total_units_sold_30d <= 0:
        return None
    return total_units_sold_30d / avg_on_hand_inventory


def compute_dsi_days(
    avg_on_hand_inventory: float | None,
    units_sold_30d: int,
) -> float | None:
    if avg_on_hand_inventory is None:
        return None
    if units_sold_30d <= 0:
        return None
    daily_rate = units_sold_30d / ROLLING_WINDOW_DAYS
    if daily_rate <= 0:
        return None
    return avg_on_hand_inventory / daily_rate


def compute_stockout_rate(
    inventory_items: list[InventoryItem],
) -> tuple[float | None, int, int]:
    if not inventory_items:
        return None, 0, 0
    stockout_count = sum(1 for item in inventory_items if item.quantity == 0)
    return stockout_count / len(inventory_items), len(inventory_items), stockout_count


def compute_fulfillment_accuracy_rate(
    orders_with_ship_time: int,
    fulfilled_without_seller_fault: int,
) -> float | None:
    if orders_with_ship_time <= 0:
        return None
    return fulfilled_without_seller_fault / orders_with_ship_time


def compute_orders_at_sla_risk(
    orders: list[Order],
    *,
    anchor: datetime,
    sla_hours: int = ORDER_DISPATCH_SLA_HOURS,
) -> int:
    at_risk = 0
    for order in orders:
        if order.ship_time is not None:
            continue
        payment_time = _order_reference_time(order)
        if payment_time is None:
            continue
        if not _in_rolling_window(payment_time, anchor=anchor):
            continue
        deadline = _ensure_utc(payment_time) + timedelta(hours=sla_hours)
        if anchor >= deadline:
            at_risk += 1
    return at_risk


def compute_seller_fault_cancellation_rate(
    order_count_30d: int,
    seller_fault_count_30d: int,
) -> float | None:
    if order_count_30d <= 0:
        return None
    return seller_fault_count_30d / order_count_30d


def compute_conversion_rate_by_category(
    order_items: list[OrderItem],
    products: list[Product],
) -> tuple[str | None, float | None]:
    if not order_items:
        return None, None

    category_by_product = {
        product.tiktok_product_id: (product.category or "unknown")
        for product in products
        if product.tiktok_product_id
    }
    counts: dict[str, int] = {}
    for item in order_items:
        category = "unknown"
        if item.tiktok_product_id:
            category = category_by_product.get(item.tiktok_product_id, "unknown")
        counts[category] = counts.get(category, 0) + item.quantity

    if not counts:
        return None, None

    top_category, top_count = max(counts.items(), key=lambda pair: pair[1])
    total_items = sum(counts.values())
    if total_items <= 0:
        return top_category, None
    return top_category, top_count / total_items


def compute_repeat_purchase_rate(
    unique_buyers: int,
    repeat_buyers: int,
) -> float | None:
    if unique_buyers <= 0:
        return None
    return repeat_buyers / unique_buyers


def compute_after_sales_handling_time_hours(
    returns: list[Return],
) -> float | None:
    durations: list[float] = []
    for item in returns:
        created = _ensure_utc(item.created_at)
        updated = _ensure_utc(item.update_time)
        hours = (updated - created).total_seconds() / 3600
        if hours >= 0:
            durations.append(hours)
    if not durations:
        return None
    return float(statistics.median(durations))


def compute_csat_proxy(return_rate_30d: float | None, order_count_30d: int) -> float | None:
    if order_count_30d <= 0 or return_rate_30d is None:
        return None
    return max(0.0, min(100.0, 100.0 * (1.0 - return_rate_30d)))


def _analytics_in_rolling_window(
    start_date: date,
    *,
    anchor: datetime,
    days: int = ROLLING_WINDOW_DAYS,
) -> bool:
    window_start = (anchor - timedelta(days=days)).date()
    anchor_date = anchor.date()
    return window_start <= start_date <= anchor_date


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _sum_gmv_by_grain(
    intervals: list[AnalyticsPerformanceInterval],
    *,
    grain: str,
    anchor: datetime,
) -> Decimal | None:
    """Sum GMV for one analytics grain within the rolling window; None when no rows."""
    total = Decimal("0")
    found = False
    for row in intervals:
        if row.grain != grain:
            continue
        if not _analytics_in_rolling_window(row.start_date, anchor=anchor):
            continue
        if row.gmv is None:
            continue
        total += row.gmv
        found = True
    return total if found else None


def compute_shop_traffic_conversion_rate(
    intervals: list[AnalyticsPerformanceInterval],
    *,
    anchor: datetime,
) -> float | None:
    """A-36 shop performance: latest shop-grain ``conversion_rate`` (``avg_conversation_rate``).

    Returns None when no shop partition row exists in the rolling window — never 0.0.
    """
    candidates: list[tuple[date, Decimal]] = []
    for row in intervals:
        if row.grain != "shop":
            continue
        if row.conversion_rate is None:
            continue
        if not _analytics_in_rolling_window(row.start_date, anchor=anchor):
            continue
        candidates.append((row.start_date, row.conversion_rate))
    if not candidates:
        return None
    _, latest_rate = max(candidates, key=lambda pair: pair[0])
    return _decimal_to_float(latest_rate)


def compute_analytics_weighted_product_ctr(
    intervals: list[AnalyticsPerformanceInterval],
    *,
    anchor: datetime,
) -> float | None:
    """A-34 product performance: simple mean of product-grain ``ctr`` values in window.

    Weighted by impressions when all rows carry ``impressions``; otherwise unweighted mean.
    Returns None when no product partition rows with CTR exist.
    """
    weighted: list[tuple[float, float]] = []
    simple: list[float] = []
    for row in intervals:
        if row.grain != "product":
            continue
        if row.ctr is None:
            continue
        if not _analytics_in_rolling_window(row.start_date, anchor=anchor):
            continue
        ctr_value = _decimal_to_float(row.ctr)
        if ctr_value is None:
            continue
        if row.impressions is not None and row.impressions > 0:
            weighted.append((ctr_value, float(row.impressions)))
        else:
            simple.append(ctr_value)
    if weighted:
        total_weight = sum(weight for _, weight in weighted)
        if total_weight <= 0:
            return None
        return sum(rate * weight for rate, weight in weighted) / total_weight
    if simple:
        return float(statistics.mean(simple))
    return None


def compute_promotion_efficiency_denominators(
    *,
    promotion_activity_partition_present: bool,
    analytics_shop_gmv_30d: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """A-25 promotion activity join: revenue denominator from analytics GMV when synced.

    Spend denominator stays None until promotion spend is persisted by ETL — no fabrication.
    """
    if not promotion_activity_partition_present:
        return None, None
    revenue_denominator = analytics_shop_gmv_30d
    spend_denominator: Decimal | None = None
    return revenue_denominator, spend_denominator


class AnalyticsKpiRollup(TypedDict):
    """Typed analytics KPI rollup for feature aggregates (#426)."""

    shop_traffic_conversion_rate: float | None
    analytics_shop_gmv_30d: Decimal | None
    analytics_product_gmv_30d: Decimal | None
    analytics_sku_gmv_30d: Decimal | None
    analytics_weighted_product_ctr: float | None
    promotion_activity_partition_present: bool
    analytics_revenue_denominator: Decimal | None
    analytics_spend_denominator: Decimal | None


def compute_analytics_kpis(
    intervals: list[AnalyticsPerformanceInterval],
    *,
    anchor: datetime,
    promotion_activity_partition_present: bool,
) -> AnalyticsKpiRollup:
    """Roll up analytics ETL outputs (#425) for feature aggregates (#426)."""
    shop_gmv = _sum_gmv_by_grain(intervals, grain="shop", anchor=anchor)
    product_gmv = _sum_gmv_by_grain(intervals, grain="product", anchor=anchor)
    sku_gmv = _sum_gmv_by_grain(intervals, grain="sku", anchor=anchor)
    revenue_denominator, spend_denominator = compute_promotion_efficiency_denominators(
        promotion_activity_partition_present=promotion_activity_partition_present,
        analytics_shop_gmv_30d=shop_gmv,
    )
    return {
        "shop_traffic_conversion_rate": compute_shop_traffic_conversion_rate(
            intervals,
            anchor=anchor,
        ),
        "analytics_shop_gmv_30d": shop_gmv,
        "analytics_product_gmv_30d": product_gmv,
        "analytics_sku_gmv_30d": sku_gmv,
        "analytics_weighted_product_ctr": compute_analytics_weighted_product_ctr(
            intervals,
            anchor=anchor,
        ),
        "promotion_activity_partition_present": promotion_activity_partition_present,
        "analytics_revenue_denominator": revenue_denominator,
        "analytics_spend_denominator": spend_denominator,
    }


def compute_all_kpis(
    *,
    shop_id: uuid.UUID,
    orders: list[Order],
    order_items: list[OrderItem],
    products: list[Product],
    inventory_items: list[InventoryItem],
    returns: list[Return],
    anchor: datetime | None = None,
    analytics_intervals: list[AnalyticsPerformanceInterval] | None = None,
    promotion_activity_partition_present: bool = False,
) -> ComputedKpiMetrics:
    """Roll up multi-endpoint KPI metrics for one shop grain."""
    del shop_id  # shop grain enforced by caller repos
    anchor = anchor or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)

    orders_30d = [
        order for order in orders if _in_rolling_window(_order_reference_time(order), anchor=anchor)
    ]
    order_items_30d = [
        item for item in order_items if _in_rolling_window(item.created_at, anchor=anchor)
    ]
    returns_30d = [item for item in returns if _in_rolling_window(item.created_at, anchor=anchor)]

    total_units_sold_30d = sum(item.quantity for item in order_items_30d)
    avg_on_hand_inventory: float | None = None
    sku_count_with_inventory = len(inventory_items)
    stockout_sku_count = 0
    stockout_rate: float | None = None
    if inventory_items:
        stockout_rate, sku_count_with_inventory, stockout_sku_count = compute_stockout_rate(
            inventory_items
        )
        avg_on_hand_inventory = sum(item.quantity for item in inventory_items) / len(
            inventory_items
        )

    orders_with_ship_time_30d = 0
    orders_fulfilled_without_seller_fault_30d = 0
    seller_fault_order_count_30d = 0
    for order in orders_30d:
        if order.is_seller_fault:
            seller_fault_order_count_30d += 1
        if order.ship_time is not None and _in_rolling_window(order.ship_time, anchor=anchor):
            orders_with_ship_time_30d += 1
            if not _is_seller_fault_cancel(order):
                orders_fulfilled_without_seller_fault_30d += 1

    return_count_30d = len(returns_30d)
    order_count_30d = len(orders_30d)
    return_rate_30d: float | None = None
    if order_count_30d > 0:
        return_rate_30d = return_count_30d / order_count_30d

    buyer_counts: dict[str, int] = {}
    for order in orders_30d:
        if order.buyer_id:
            buyer_counts[order.buyer_id] = buyer_counts.get(order.buyer_id, 0) + 1
    unique_buyers_30d = len(buyer_counts)
    repeat_buyers_30d = sum(1 for count in buyer_counts.values() if count >= 2)

    top_category_name, conversion_rate_by_category = compute_conversion_rate_by_category(
        order_items_30d,
        products,
    )

    analytics_kpis = compute_analytics_kpis(
        analytics_intervals or [],
        anchor=anchor,
        promotion_activity_partition_present=promotion_activity_partition_present,
    )

    return ComputedKpiMetrics(
        total_units_sold_30d=total_units_sold_30d,
        avg_on_hand_inventory=avg_on_hand_inventory,
        sku_count_with_inventory=sku_count_with_inventory,
        stockout_sku_count=stockout_sku_count,
        orders_with_ship_time_30d=orders_with_ship_time_30d,
        orders_fulfilled_without_seller_fault_30d=orders_fulfilled_without_seller_fault_30d,
        orders_at_sla_risk_count=compute_orders_at_sla_risk(orders, anchor=anchor),
        seller_fault_order_count_30d=seller_fault_order_count_30d,
        order_items_count_30d=len(order_items_30d),
        top_category_name=top_category_name,
        unique_buyers_30d=unique_buyers_30d,
        repeat_buyers_30d=repeat_buyers_30d,
        return_rate_30d=return_rate_30d,
        inventory_turnover=compute_inventory_turnover(
            total_units_sold_30d,
            avg_on_hand_inventory,
        ),
        dsi_days=compute_dsi_days(avg_on_hand_inventory, total_units_sold_30d),
        stockout_rate=stockout_rate,
        fulfillment_accuracy_rate=compute_fulfillment_accuracy_rate(
            orders_with_ship_time_30d,
            orders_fulfilled_without_seller_fault_30d,
        ),
        seller_fault_cancellation_rate=compute_seller_fault_cancellation_rate(
            order_count_30d,
            seller_fault_order_count_30d,
        ),
        conversion_rate_by_category=conversion_rate_by_category,
        repeat_purchase_rate=compute_repeat_purchase_rate(
            unique_buyers_30d,
            repeat_buyers_30d,
        ),
        after_sales_handling_time_hours=compute_after_sales_handling_time_hours(returns_30d),
        csat_proxy_score=compute_csat_proxy(return_rate_30d, order_count_30d),
        shop_traffic_conversion_rate=analytics_kpis["shop_traffic_conversion_rate"],
        analytics_shop_gmv_30d=analytics_kpis["analytics_shop_gmv_30d"],
        analytics_product_gmv_30d=analytics_kpis["analytics_product_gmv_30d"],
        analytics_sku_gmv_30d=analytics_kpis["analytics_sku_gmv_30d"],
        analytics_weighted_product_ctr=analytics_kpis["analytics_weighted_product_ctr"],
        promotion_activity_partition_present=analytics_kpis["promotion_activity_partition_present"],
        analytics_revenue_denominator=analytics_kpis["analytics_revenue_denominator"],
        analytics_spend_denominator=analytics_kpis["analytics_spend_denominator"],
    )
