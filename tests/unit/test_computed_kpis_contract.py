"""Issue #374 — P2-B3 computed KPI formula contract tests.

One pytest class per KPI formula with golden fixtures and edge cases.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from juli_backend.models.models import InventoryItem, Order, OrderItem, Product, Return
from juli_backend.services.aggregates.computed_kpis import (
    ROLLING_WINDOW_DAYS,
    compute_after_sales_handling_time_hours,
    compute_all_kpis,
    compute_conversion_rate_by_category,
    compute_csat_proxy,
    compute_dsi_days,
    compute_fulfillment_accuracy_rate,
    compute_inventory_turnover,
    compute_orders_at_sla_risk,
    compute_repeat_purchase_rate,
    compute_seller_fault_cancellation_rate,
    compute_stockout_rate,
)
from juli_backend.services.aggregates.thresholds import ORDER_DISPATCH_SLA_HOURS

ANCHOR = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


class TestInventoryTurnover:
    def test_golden_turnover(self):
        assert compute_inventory_turnover(60, 20.0) == pytest.approx(3.0)

    def test_zero_inventory_returns_none(self):
        assert compute_inventory_turnover(60, 0.0) is None
        assert compute_inventory_turnover(60, None) is None

    def test_zero_units_sold_returns_none(self):
        assert compute_inventory_turnover(0, 20.0) is None


class TestDsiDays:
    def test_golden_dsi(self):
        # avg 30 units, sold 60 in 30d => daily 2 => DSI 15 days
        assert compute_dsi_days(30.0, 60) == pytest.approx(15.0)

    def test_zero_units_sold_returns_none(self):
        assert compute_dsi_days(30.0, 0) is None


class TestStockoutRate:
    def test_golden_stockout_rate(self):
        items = [
            _inventory("sku-1", 10),
            _inventory("sku-2", 0),
            _inventory("sku-3", 5),
            _inventory("sku-4", 0),
        ]
        rate, total, stockout = compute_stockout_rate(items)
        assert rate == pytest.approx(0.5)
        assert total == 4
        assert stockout == 2

    def test_empty_inventory_returns_none(self):
        rate, total, stockout = compute_stockout_rate([])
        assert rate is None
        assert total == 0
        assert stockout == 0


class TestFulfillmentAccuracyRate:
    def test_golden_accuracy(self):
        assert compute_fulfillment_accuracy_rate(100, 95) == pytest.approx(0.95)

    def test_no_shipped_orders_returns_none(self):
        assert compute_fulfillment_accuracy_rate(0, 0) is None


class TestOrdersAtSlaRisk:
    def test_counts_unshipped_orders_past_sla(self):
        payment = ANCHOR - timedelta(hours=ORDER_DISPATCH_SLA_HOURS + 1)
        orders = [
            _order(
                "ord-late",
                payment_time=payment,
                ship_time=None,
            ),
            _order(
                "ord-ok",
                payment_time=ANCHOR - timedelta(hours=12),
                ship_time=ANCHOR - timedelta(hours=6),
            ),
        ]
        assert compute_orders_at_sla_risk(orders, anchor=ANCHOR) == 1

    def test_ignores_orders_with_ship_time(self):
        payment = ANCHOR - timedelta(hours=ORDER_DISPATCH_SLA_HOURS + 5)
        orders = [_order("ord-shipped", payment_time=payment, ship_time=payment)]
        assert compute_orders_at_sla_risk(orders, anchor=ANCHOR) == 0


class TestOrderDispatchSlaThresholdConstant:
    def test_order_dispatch_sla_hours_thresholds_constant(self):
        assert ORDER_DISPATCH_SLA_HOURS == 48


class TestSellerFaultCancellationRate:
    def test_golden_rate(self):
        assert compute_seller_fault_cancellation_rate(100, 5) == pytest.approx(0.05)

    def test_zero_orders_returns_none(self):
        assert compute_seller_fault_cancellation_rate(0, 0) is None


class TestConversionRateByCategory:
    def test_golden_top_category_share(self):
        products = [
            _product("prod-a", category="Electronics"),
            _product("prod-b", category="Fashion"),
        ]
        order_items = [
            _order_item("prod-a", quantity=3),
            _order_item("prod-a", quantity=1),
            _order_item("prod-b", quantity=1),
        ]
        category, rate = compute_conversion_rate_by_category(order_items, products)
        assert category == "Electronics"
        assert rate == pytest.approx(0.8)

    def test_empty_items_returns_none(self):
        assert compute_conversion_rate_by_category([], []) == (None, None)


class TestRepeatPurchaseRate:
    def test_golden_repeat_rate(self):
        assert compute_repeat_purchase_rate(10, 3) == pytest.approx(0.3)

    def test_zero_buyers_returns_none(self):
        assert compute_repeat_purchase_rate(0, 0) is None


class TestAfterSalesHandlingTime:
    def test_median_hours(self):
        created = ANCHOR - timedelta(days=2)
        returns = [
            _return(created, created + timedelta(hours=8)),
            _return(created, created + timedelta(hours=20)),
            _return(created, created + timedelta(hours=12)),
        ]
        assert compute_after_sales_handling_time_hours(returns) == pytest.approx(12.0)

    def test_empty_returns_returns_none(self):
        assert compute_after_sales_handling_time_hours([]) is None


class TestCsatProxy:
    def test_golden_csat_proxy(self):
        assert compute_csat_proxy(0.2, 10) == pytest.approx(80.0)

    def test_clamps_to_zero_and_hundred(self):
        assert compute_csat_proxy(1.5, 5) == 0.0
        assert compute_csat_proxy(-0.1, 5) == 100.0

    def test_zero_orders_returns_none(self):
        assert compute_csat_proxy(0.1, 0) is None


class TestComputeAllKpisIntegration:
    def test_multi_endpoint_snapshot_populates_metrics(self):
        shop_id = uuid.uuid4()
        payment_recent = ANCHOR - timedelta(days=5)
        products = [
            _product("prod-a", category="Electronics"),
            _product("prod-b", category="Fashion"),
        ]
        orders = [
            _order(
                "ord-1",
                payment_time=payment_recent,
                ship_time=payment_recent + timedelta(hours=6),
                buyer_id="buyer-1",
            ),
            _order(
                "ord-2",
                payment_time=payment_recent,
                ship_time=payment_recent + timedelta(hours=8),
                buyer_id="buyer-1",
            ),
            _order(
                "ord-3",
                payment_time=payment_recent,
                ship_time=None,
                buyer_id="buyer-2",
                is_seller_fault=True,
                status="CANCELLED",
            ),
            _order(
                "ord-late",
                payment_time=ANCHOR - timedelta(hours=ORDER_DISPATCH_SLA_HOURS + 2),
                ship_time=None,
                buyer_id="buyer-3",
            ),
        ]
        order_items = [
            _order_item("prod-a", quantity=4),
            _order_item("prod-b", quantity=1),
        ]
        inventory_items = [
            _inventory("sku-1", 20),
            _inventory("sku-2", 0),
        ]
        returns = [
            _return(
                payment_recent,
                payment_recent + timedelta(hours=10),
            ),
        ]

        metrics = compute_all_kpis(
            shop_id=shop_id,
            orders=orders,
            order_items=order_items,
            products=products,
            inventory_items=inventory_items,
            returns=returns,
            anchor=ANCHOR,
        )

        assert metrics.inventory_turnover == pytest.approx(5 / 10)
        assert metrics.dsi_days == pytest.approx(10 / (5 / ROLLING_WINDOW_DAYS))
        assert metrics.stockout_rate == pytest.approx(0.5)
        assert metrics.fulfillment_accuracy_rate == pytest.approx(2 / 2)
        assert metrics.orders_at_sla_risk_count == 2
        assert metrics.seller_fault_cancellation_rate == pytest.approx(1 / 4)
        assert metrics.conversion_rate_by_category == pytest.approx(0.8)
        assert metrics.repeat_purchase_rate == pytest.approx(1 / 3)
        assert metrics.after_sales_handling_time_hours == pytest.approx(10.0)
        assert metrics.csat_proxy_score == pytest.approx(75.0)


def _product(product_id: str, *, category: str) -> Product:
    now = ANCHOR
    return Product(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        tiktok_product_id=product_id,
        name=product_id,
        status="ACTIVE",
        category=category,
        revenue=Decimal("100000"),
        units_sold=5,
        update_time=now,
    )


def _order(
    tiktok_order_id: str,
    *,
    payment_time: datetime | None,
    ship_time: datetime | None = None,
    buyer_id: str | None = None,
    is_seller_fault: bool | None = None,
    status: str = "COMPLETED",
) -> Order:
    return Order(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        tiktok_order_id=tiktok_order_id,
        status=status,
        buyer_id=buyer_id,
        total_amount=Decimal("100000"),
        currency="VND",
        payment_time=payment_time,
        ship_time=ship_time,
        is_seller_fault=is_seller_fault,
        update_time=ANCHOR,
        created_at=payment_time or ANCHOR,
    )


def _order_item(product_id: str, *, quantity: int) -> OrderItem:
    return OrderItem(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        tiktok_order_id="ord-x",
        tiktok_product_id=product_id,
        tiktok_sku_id=f"sku-{product_id}",
        quantity=quantity,
        unit_price=Decimal("10000"),
        line_total=Decimal(str(quantity * 10000)),
        update_time=ANCHOR,
        created_at=ANCHOR - timedelta(days=3),
    )


def _inventory(sku_id: str, quantity: int) -> InventoryItem:
    return InventoryItem(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        tiktok_product_id=f"prod-{sku_id}",
        tiktok_sku_id=sku_id,
        quantity=quantity,
        update_time=ANCHOR,
        created_at=ANCHOR,
    )


def _return(created_at: datetime, updated_at: datetime) -> Return:
    return Return(
        id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        tiktok_return_id=f"ret-{uuid.uuid4()}",
        tiktok_order_id="ord-1",
        return_type="refund",
        refund_amount=Decimal("10000"),
        status="COMPLETED",
        created_at=created_at,
        update_time=updated_at,
    )
