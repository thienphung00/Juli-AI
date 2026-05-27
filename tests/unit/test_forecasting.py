"""Tests for intelligence/forecasting module — Issue #35.

Test mapping (from issue):
  AC1 → test_forecast_accuracy_within_mape_bound
  AC2 → test_low_stock_risks_ranked_by_urgency
  AC3 → test_velocity_change_detection
  AC4 → test_fallback_to_moving_average
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import InventoryItem, Order, Shop, User
from src.intelligence.forecasting.forecaster import (
    ForecastResult,
    LowStockRisk,
    VelocityChange,
    get_forecast,
    get_low_stock_risks,
    get_velocity_changes,
)


def _make_user(user_id: uuid.UUID) -> User:
    return User(id=user_id, phone="+84900000002")


def _make_shop(shop_id: uuid.UUID, user_id: uuid.UUID) -> Shop:
    return Shop(id=shop_id, user_id=user_id, shop_name="Forecast Shop")


def _make_inventory(
    shop_id: uuid.UUID,
    *,
    sku_id: str = "sku_forecast_1",
    quantity: int = 70,
) -> InventoryItem:
    now = datetime.now(timezone.utc)
    return InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id="prod_001",
        tiktok_sku_id=sku_id,
        quantity=quantity,
        velocity="medium",
        update_time=now,
        created_at=now,
    )


def _make_order(
    shop_id: uuid.UUID,
    *,
    tiktok_order_id: str,
    created_at: datetime,
) -> Order:
    return Order(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_order_id=tiktok_order_id,
        status="COMPLETED",
        total_amount=Decimal("100.00"),
        currency="VND",
        update_time=created_at,
        created_at=created_at,
    )


async def _seed_shop(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    sid = uuid.uuid4()
    session.add(_make_user(uid))
    session.add(_make_shop(sid, uid))
    await session.flush()
    return sid


async def _seed_constant_daily_orders(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    days: int,
    orders_per_day: int,
) -> None:
    """One SKU shop: each completed order counts as one attributed unit."""
    base = datetime.now(timezone.utc) - timedelta(days=days)
    orders = []
    for day_offset in range(days):
        day_start = base + timedelta(days=day_offset)
        for i in range(orders_per_day):
            orders.append(
                _make_order(
                    shop_id,
                    tiktok_order_id=f"ord_{day_offset}_{i}",
                    created_at=day_start + timedelta(hours=12),
                )
            )
    session.add_all(orders)
    await session.flush()


# ===================================================================
# AC1 — forecast accuracy within MAPE bound on 7-day horizon
# ===================================================================


class TestForecastAccuracyWithinMapeBound:
    """AC1: get_forecast returns depletion estimate with ≤20% MAPE on 7-day horizon."""

    @pytest.mark.asyncio
    async def test_forecast_accuracy_within_mape_bound(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        session.add(_make_inventory(shop_id, quantity=70))
        await _seed_constant_daily_orders(
            session, shop_id, days=45, orders_per_day=10
        )
        await session.flush()

        result = await get_forecast(session, shop_id, "sku_forecast_1")

        assert isinstance(result, ForecastResult)
        assert result.method == "linear_regression"
        assert result.horizon_mape is not None
        assert result.horizon_mape <= 0.20
        assert result.daily_velocity == pytest.approx(10.0, rel=0.2)
        assert result.depletion_date is not None

        days_left = (result.depletion_date - datetime.now(timezone.utc)).days
        assert days_left == pytest.approx(7, abs=2)


# ===================================================================
# AC2 — low stock risks ranked by urgency
# ===================================================================


class TestLowStockRisksRankedByUrgency:
    """AC2: get_low_stock_risks returns at-risk SKUs sorted by urgency."""

    @pytest.mark.asyncio
    async def test_low_stock_risks_ranked_by_urgency(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        now = datetime.now(timezone.utc)
        session.add_all(
            [
                InventoryItem(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    tiktok_product_id="p1",
                    tiktok_sku_id="sku_critical",
                    quantity=5,
                    velocity="high",
                    update_time=now,
                    created_at=now,
                ),
                InventoryItem(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    tiktok_product_id="p2",
                    tiktok_sku_id="sku_warning",
                    quantity=30,
                    velocity="medium",
                    update_time=now,
                    created_at=now,
                ),
            ]
        )
        await _seed_constant_daily_orders(
            session, shop_id, days=20, orders_per_day=10
        )
        await session.flush()

        risks = await get_low_stock_risks(session, shop_id, window_days=7)

        assert len(risks) >= 2
        assert all(isinstance(r, LowStockRisk) for r in risks)
        assert risks[0].urgency_score >= risks[1].urgency_score
        assert risks[0].sku_id == "sku_critical"
        assert risks[0].days_until_stockout < risks[1].days_until_stockout


# ===================================================================
# AC3 — velocity change detection
# ===================================================================


class TestVelocityChangeDetection:
    """AC3: get_velocity_changes detects acceleration and deceleration."""

    @pytest.mark.asyncio
    async def test_velocity_change_detection(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        session.add(_make_inventory(shop_id))
        now = datetime.now(timezone.utc)
        base = now - timedelta(days=20)
        orders = []

        for day_offset in range(20):
            day_start = base + timedelta(days=day_offset)
            count = 2 if day_offset < 10 else 8
            for i in range(count):
                orders.append(
                    _make_order(
                        shop_id,
                        tiktok_order_id=f"vel_{day_offset}_{i}",
                        created_at=day_start + timedelta(hours=1),
                    )
                )
        session.add_all(orders)
        await session.flush()

        changes = await get_velocity_changes(session, shop_id)

        assert len(changes) >= 1
        accel = [c for c in changes if c.sku_id == "sku_forecast_1"]
        assert len(accel) == 1
        assert isinstance(accel[0], VelocityChange)
        assert accel[0].direction == "accelerating"
        assert accel[0].recent_velocity > accel[0].prior_velocity


# ===================================================================
# AC4 — moving average fallback when <30 days history
# ===================================================================


class TestFallbackToMovingAverage:
    """AC4: uses simple moving average when fewer than 30 days of history."""

    @pytest.mark.asyncio
    async def test_fallback_to_moving_average(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        session.add(_make_inventory(shop_id, quantity=50))
        await _seed_constant_daily_orders(
            session, shop_id, days=12, orders_per_day=5
        )
        await session.flush()

        result = await get_forecast(session, shop_id, "sku_forecast_1")

        assert result.method == "moving_average"
        assert result.daily_velocity == pytest.approx(5.0, rel=0.01)
