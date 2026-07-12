"""Pure computed KPI formulas over synced Postgres commerce entities (#374).

Formulas live here; ``signals.py`` applies thresholds and visual_layer one-liners only.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from juli_backend.models.models import InventoryItem, Order, OrderItem, Product, Return
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


def compute_all_kpis(
    *,
    shop_id: uuid.UUID,
    orders: list[Order],
    order_items: list[OrderItem],
    products: list[Product],
    inventory_items: list[InventoryItem],
    returns: list[Return],
    anchor: datetime | None = None,
) -> ComputedKpiMetrics:
    """Roll up multi-endpoint KPI metrics for one shop grain."""
    del shop_id  # shop grain enforced by caller repos
    anchor = anchor or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)

    orders_30d = [
        order
        for order in orders
        if _in_rolling_window(_order_reference_time(order), anchor=anchor)
    ]
    order_items_30d = [
        item
        for item in order_items
        if _in_rolling_window(item.created_at, anchor=anchor)
    ]
    returns_30d = [
        item for item in returns if _in_rolling_window(item.created_at, anchor=anchor)
    ]

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
    )
