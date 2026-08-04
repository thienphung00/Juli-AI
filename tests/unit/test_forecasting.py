"""Tests for intelligence/forecasting module — Issue #35 + Issue #721.

Test mapping (from issue #35):
  AC1 → test_forecast_accuracy_within_mape_bound
  AC2 → test_low_stock_risks_ranked_by_urgency
  AC3 → test_velocity_change_detection
  AC4 → test_fallback_to_moving_average

Test mapping (from issue #721 — RA-1: Inventory reorder advisory):
  AC1 → test_reorder_quantity_computed_from_sales_pace_lead_time
  AC2 → test_reorder_quantity_fallback_zero_velocity
  AC3 → test_reorder_quantity_low_stock_priorities_ranking
  AC4 → test_reorder_quantity_editable_before_approval
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.forecasting.forecaster import (
    ForecastResult,
    LowStockRisk,
    VelocityChange,
    compute_reorder_quantity,
    get_forecast,
    get_low_stock_risks,
    get_velocity_changes,
)
from juli_backend.models.models import InventoryItem, Order, Shop, User


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
    now = datetime.now(UTC)
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
    base = datetime.now(UTC) - timedelta(days=days)
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
        await _seed_constant_daily_orders(session, shop_id, days=45, orders_per_day=10)
        await session.flush()

        result = await get_forecast(session, shop_id, "sku_forecast_1")

        assert isinstance(result, ForecastResult)
        assert result.method == "linear_regression"
        assert result.horizon_mape is not None
        assert result.horizon_mape <= 0.20
        assert result.daily_velocity == pytest.approx(10.0, rel=0.2)
        assert result.depletion_date is not None

        days_left = (result.depletion_date - datetime.now(UTC)).days
        assert days_left == pytest.approx(7, abs=2)


# ===================================================================
# AC2 — low stock risks ranked by urgency
# ===================================================================


class TestLowStockRisksRankedByUrgency:
    """AC2: get_low_stock_risks returns at-risk SKUs sorted by urgency."""

    @pytest.mark.asyncio
    async def test_low_stock_risks_ranked_by_urgency(self, session: AsyncSession):
        shop_id = await _seed_shop(session)
        now = datetime.now(UTC)
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
        await _seed_constant_daily_orders(session, shop_id, days=20, orders_per_day=10)
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
        now = datetime.now(UTC)
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
        await _seed_constant_daily_orders(session, shop_id, days=12, orders_per_day=5)
        await session.flush()

        result = await get_forecast(session, shop_id, "sku_forecast_1")

        assert result.method == "moving_average"
        assert result.daily_velocity == pytest.approx(5.0, rel=0.01)


# ===================================================================
# AC1 — Issue #721: reorder quantity computation with sales pace
# ===================================================================


class TestReorderQuantityComputedFromSalesPace:
    """AC1: compute_reorder_quantity returns quantity = velocity * (lead_time + safety_stock)."""

    def test_reorder_quantity_known_inputs(self):
        """Test with known sales pace, lead time, and safety stock."""
        risk = LowStockRisk(
            sku_id="sku_test",
            tiktok_product_id="prod_test",
            quantity=10,
            daily_velocity=5.0,
            days_until_stockout=2.0,
            urgency_score=0.5,
        )
        lead_time_days = 3
        safety_stock_days = 2

        quantity = compute_reorder_quantity(
            risk,
            lead_time_days=lead_time_days,
            safety_stock_days=safety_stock_days,
        )

        # quantity = 5.0 * (3 + 2) = 25 units
        assert quantity == pytest.approx(25.0, rel=0.01)

    def test_reorder_quantity_low_velocity_no_floor(self):
        """Test that low-velocity items do NOT get floored to 10.0; formula applies."""
        risk = LowStockRisk(
            sku_id="low_velocity",
            tiktok_product_id="prod_low",
            quantity=50,
            daily_velocity=1.0,
            days_until_stockout=50.0,
            urgency_score=0.02,
        )
        lead_time_days = 3
        safety_stock_days = 2

        quantity = compute_reorder_quantity(
            risk,
            lead_time_days=lead_time_days,
            safety_stock_days=safety_stock_days,
        )

        # quantity = 1.0 * (3 + 2) = 5.0 units (not 10.0 fallback)
        assert quantity == pytest.approx(5.0, rel=0.01)

    def test_reorder_quantity_scales_with_velocity(self):
        """Test that reorder quantity scales linearly with sales velocity."""
        lead_time = 3
        safety_stock = 2

        risk_slow = LowStockRisk(
            sku_id="slow",
            tiktok_product_id="prod",
            quantity=10,
            daily_velocity=2.0,
            days_until_stockout=5.0,
            urgency_score=0.2,
        )
        risk_fast = LowStockRisk(
            sku_id="fast",
            tiktok_product_id="prod",
            quantity=10,
            daily_velocity=10.0,
            days_until_stockout=1.0,
            urgency_score=1.0,
        )

        qty_slow = compute_reorder_quantity(
            risk_slow, lead_time_days=lead_time, safety_stock_days=safety_stock
        )
        qty_fast = compute_reorder_quantity(
            risk_fast, lead_time_days=lead_time, safety_stock_days=safety_stock
        )

        # qty_slow = 2.0 * 5 = 10; qty_fast = 10.0 * 5 = 50
        assert qty_slow == pytest.approx(10.0, rel=0.01)
        assert qty_fast == pytest.approx(50.0, rel=0.01)
        assert qty_fast > qty_slow

    def test_reorder_quantity_rounds_up(self):
        """Test that fractional results are rounded up to whole units."""
        # velocity = 0.5, lead_time = 2, safety_stock = 3 → 0.5 * 5 = 2.5 → rounds to 3
        risk = LowStockRisk(
            sku_id="fractional",
            tiktok_product_id="prod",
            quantity=50,
            daily_velocity=0.5,
            days_until_stockout=100.0,
            urgency_score=0.01,
        )
        quantity = compute_reorder_quantity(risk, lead_time_days=2, safety_stock_days=3)
        assert quantity == pytest.approx(3.0, rel=0.01)  # 0.5 * 5 = 2.5, rounded up to 3

    def test_reorder_quantity_very_low_velocity_floor(self):
        """Test that very-low-velocity items still get at least 1 unit (not 10.0 floor)."""
        # velocity = 0.1, lead_time = 2, safety_stock = 3 → 0.1 * 5 = 0.5 → rounds to 1
        risk = LowStockRisk(
            sku_id="very_low",
            tiktok_product_id="prod",
            quantity=100,
            daily_velocity=0.1,
            days_until_stockout=1000.0,
            urgency_score=0.001,
        )
        quantity = compute_reorder_quantity(risk, lead_time_days=2, safety_stock_days=3)
        # Should be 0.1 * 5 = 0.5, rounded up to 1, NOT 10.0
        assert quantity == pytest.approx(1.0, rel=0.01)


# ===================================================================
# AC2 — Issue #721: fallback for zero/near-zero sales history
# ===================================================================


class TestReorderQuantityFallbackZeroVelocity:
    """AC2: zero/near-zero sales history produces reasonable fallback, not error."""

    def test_reorder_quantity_zero_velocity_fallback(self):
        """Test that zero velocity returns a reasonable minimum quantity."""
        risk = LowStockRisk(
            sku_id="new_product",
            tiktok_product_id="prod_new",
            quantity=0,
            daily_velocity=0.0,
            days_until_stockout=0.0,
            urgency_score=100.0,  # high urgency despite zero velocity
        )

        quantity = compute_reorder_quantity(risk, lead_time_days=3, safety_stock_days=2)

        # Should return a positive fallback quantity, not 0 or error
        assert quantity > 0
        assert isinstance(quantity, (int, float))

    def test_reorder_quantity_near_zero_velocity(self):
        """Test handling of very low velocity (near-zero) — should be 1, not 10."""
        risk = LowStockRisk(
            sku_id="slow_mover",
            tiktok_product_id="prod_slow",
            quantity=100,
            daily_velocity=0.1,
            days_until_stockout=1000.0,
            urgency_score=0.01,
        )

        quantity = compute_reorder_quantity(risk, lead_time_days=3, safety_stock_days=2)

        # quantity = 0.1 * (3 + 2) = 0.5, should round up to 1, NOT 10.0
        assert quantity == pytest.approx(1.0, rel=0.01)


# ===================================================================
# AC3 — Issue #721: low-stock priorities (urgency-based selection)
# ===================================================================


class TestReorderQuantityLowStockPrioritiesRanking:
    """AC3: Item ordering via urgency_score prioritizes closest to stockout."""

    @pytest.mark.asyncio
    async def test_urgency_score_ranks_by_days_until_stockout(self, session: AsyncSession):
        """get_low_stock_risks returns items ordered by urgency (days_until_stockout)."""
        shop_id = await _seed_shop(session)
        now = datetime.now(UTC)

        # Create two items:
        # - critical: 2 units, fast velocity → runs out very soon
        # - warning: 30 units, slower velocity → runs out later
        session.add_all(
            [
                InventoryItem(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    tiktok_product_id="prod_critical",
                    tiktok_sku_id="sku_critical",
                    quantity=2,  # very low stock
                    velocity="high",
                    update_time=now,
                    created_at=now,
                ),
                InventoryItem(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    tiktok_product_id="prod_warning",
                    tiktok_sku_id="sku_warning",
                    quantity=30,  # moderate stock
                    velocity="medium",
                    update_time=now,
                    created_at=now,
                ),
            ]
        )
        await _seed_constant_daily_orders(session, shop_id, days=20, orders_per_day=10)
        await session.flush()

        risks = await get_low_stock_risks(session, shop_id, window_days=7)

        # Should have at least the critical item in results
        assert len(risks) >= 1
        # First item should be the critical one (highest urgency)
        assert risks[0].sku_id == "sku_critical"
        assert risks[0].days_until_stockout < (
            risks[1].days_until_stockout if len(risks) > 1 else float("inf")
        )
        # Urgency score should rank critical higher
        assert risks[0].urgency_score > (risks[1].urgency_score if len(risks) > 1 else 0)


# ===================================================================
# AC4 — Issue #721: suggested quantity is freely editable
# ===================================================================
# AC4 (editable before approval) is a UI-layer property tested in the demo slice,
# not a backend property. No code-level test required here.
