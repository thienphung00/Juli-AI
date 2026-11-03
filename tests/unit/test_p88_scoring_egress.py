"""P88 (Supabase egress): the continuous-trigger scoring pass stops reading whole histories.

pg_stat_statements, 2026-11-02/03: 57 calls/day, each reading every ``silver.orders`` row
(~5.8k, every column) and every ``order_items`` row (~2.1k) of the shop -- ``build_feature_
aggregates`` listed them with ``limit=10_000`` and then kept the 30-day window in Python.
Now the window is a WHERE clause, only the KPI columns are loaded, the history-wide count /
sum come from SQL, and the webhook / reconcile trigger scores a shop at most hourly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect

from juli_backend.models.models import Order, OrderItem, Product, Return, Shop, User
from juli_backend.repositories.repos import (
    InventoryRepo,
    OrderItemsRepo,
    OrdersRepo,
    ProductsRepo,
    ReturnsRepo,
)
from juli_backend.services.aggregates import builder as builder_module
from juli_backend.services.aggregates.builder import build_feature_aggregates
from juli_backend.services.aggregates.computed_kpis import compute_all_kpis
from juli_backend.services.cdp_speed import decision_rules_scoring as scoring_mod
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeJob
from juli_backend.services.cdp_speed.targeted_fetch_planner import TargetedFetchPlan

pytestmark = pytest.mark.asyncio

ANCHOR = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
NAIVE = ANCHOR.replace(tzinfo=None)


async def _shop(session, user_id) -> Shop:
    user = User(id=user_id, phone="+84901888088")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="P88 Shop",
        tiktok_shop_id="tiktok_shop_p88",
        created_at=ANCHOR - timedelta(days=400),
    )
    session.add_all([user, shop])
    await session.flush()
    session.add(
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-p88",
            name="Bình nước",
            status="ACTIVE",
            revenue=Decimal("900000"),
            units_sold=30,
            update_time=NAIVE,
        )
    )
    # Days before the anchor: 3 and 12 are inside the 30-day window; 45 / 200 are history.
    for n, days_ago in enumerate((3, 12, 45, 200)):
        at = NAIVE - timedelta(days=days_ago)
        order = Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id=f"ord-p88-{n}",
            status="COMPLETED" if n % 2 == 0 else "CANCELLED",
            buyer_id="buyer-1",
            total_amount=Decimal(100000 * (n + 1)),
            order_value=Decimal(100000 * (n + 1)),
            currency="VND",
            payment_time=at,
            ship_time=at + timedelta(hours=10) if n != 1 else None,
            is_seller_fault=n == 1,
            cancel_reason="x" * 400,
            update_time=at,
            created_at=at,
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                order_id=order.id,
                tiktok_order_id=order.tiktok_order_id,
                tiktok_product_id="prod-p88",
                tiktok_sku_id=f"sku-{n}",
                quantity=n + 1,
                unit_price=Decimal(50000),
                line_total=Decimal(50000 * (n + 1)),
                update_time=at,
                created_at=at,
            )
        )
        session.add(
            Return(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_return_id=f"ret-p88-{n}",
                tiktok_order_id=order.tiktok_order_id,
                order_id=order.id,
                return_type="refund",
                refund_amount=Decimal("1000"),
                status="COMPLETED",
                update_time=at + timedelta(hours=30),
                created_at=at,
            )
        )
    await session.flush()
    return shop


async def test_snapshot_matches_the_whole_history_computation(session, user_id):
    """Same snapshot as the pre-P88 builder (every row listed, window kept in Python)."""
    shop = await _shop(session, user_id)
    orders = await OrdersRepo(session).list(shop.id, limit=10_000)
    returns = await ReturnsRepo(session).list(shop.id, limit=10_000)
    expected = compute_all_kpis(
        shop_id=shop.id,
        orders=orders,
        order_items=await OrderItemsRepo(session).list(shop.id, limit=10_000),
        products=await ProductsRepo(session).list(shop.id, limit=10_000),
        inventory_items=await InventoryRepo(session).list(shop.id, limit=10_000),
        returns=returns,
        anchor=ANCHOR,
        analytics_intervals=[],
    )
    session.expunge_all()

    snapshot = await build_feature_aggregates(session, shop.id, computed_at=ANCHOR)

    assert snapshot.computed_kpis == expected
    assert expected.order_count_30d == 2  # the fixture exercises the window
    assert snapshot.order_count == len(orders) == 4
    assert snapshot.return_count == len(returns) == 4
    assert snapshot.total_order_value == sum((o.total_amount for o in orders), Decimal(0))
    assert snapshot.return_rate_proxy == 1.0


async def test_only_window_rows_and_kpi_columns_are_read(session, user_id):
    shop = await _shop(session, user_id)
    session.expunge_all()

    orders = await builder_module._rolling_window_orders(session, shop.id, ANCHOR, 10_000)
    items = await builder_module._rolling_window_order_items(session, shop.id, ANCHOR, 10_000)
    returns = await builder_module._rolling_window_returns(session, shop.id, ANCHOR, 10_000)

    assert len(orders) == len(items) == len(returns) == 2
    unloaded = inspect(orders[0]).unloaded
    assert {"cancel_reason", "order_value", "update_time", "delivery_time"} <= unloaded
    assert {"tiktok_sku_id", "tiktok_order_id"} <= inspect(items[0]).unloaded


def _job(shop_id: uuid.UUID) -> SharedComputeJob:
    return SharedComputeJob(
        shop_id=shop_id,
        shop_key="tiktok_shop_p88",
        enqueue_reason="webhook",
        fetch_plan=TargetedFetchPlan(catalog_id=None, shop_id="tiktok_shop_p88", resources=()),
        idempotency_key="p88",
    )


@pytest.mark.parametrize(
    ("claimed", "runs"),
    [(True, 1), (False, 0)],
)
async def test_hourly_gate(monkeypatch, claimed, runs):
    calls: list[uuid.UUID] = []

    async def fake_stage(session, job):
        calls.append(job.shop_id)
        return "scored"

    monkeypatch.setattr(scoring_mod, "decision_rules_scoring_stage", fake_stage)
    keys: list[str] = []

    def claim(key: str) -> bool:
        keys.append(key)
        return claimed

    shop_id = uuid.uuid4()
    result = await scoring_mod.hourly_scoring_stage(None, _job(shop_id), claim=claim)

    assert keys == [str(shop_id)]
    assert len(calls) == runs
    assert result == ("scored" if runs else None)


async def test_hourly_gate_fails_open(monkeypatch):
    calls: list[uuid.UUID] = []

    async def fake_stage(session, job):
        calls.append(job.shop_id)

    def broken(key: str) -> bool:
        raise ConnectionError("redis down")

    monkeypatch.setattr(scoring_mod, "decision_rules_scoring_stage", fake_stage)
    await scoring_mod.hourly_scoring_stage(None, _job(uuid.uuid4()), claim=broken)
    assert len(calls) == 1


async def test_gate_window_is_one_hour():
    assert scoring_mod.SCORING_MIN_INTERVAL_SECONDS == 3600
