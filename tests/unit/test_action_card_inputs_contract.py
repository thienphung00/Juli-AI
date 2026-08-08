"""P3-A1 Action Card inputs (on-demand reorder advisory) — Issue #721.

AC1 → computed reorder_quantity for the highest-urgency low-stock item
AC2 → zero-velocity item yields 10-unit fallback (not error or null)
AC3 → highest-urgency risk (first after sort) is default subject
AC4 → response marks quantity editable (backend half; UI half separate)
AC5 → empty low-stock state returns well-formed 200 response (not 500/404)
AC6 → endpoint does not write to DB / does not invoke scoring pipeline
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.ai.forecasting import LowStockRisk
from juli_backend.models.models import (
    InventoryItem,
    Order,
    Shop,
    User,
)


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+849305000721")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop_with_inventory(session, authenticated_user):
    """Shop with inventory items for reorder testing."""
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Action Card Inputs Shop 721",
        tiktok_shop_id="tiktok_shop_721",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop_with_inventory):
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop_with_inventory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_ac1_returns_computed_reorder_quantity_for_highest_urgency_item(
    session,
    shop_with_inventory,
    auth_client,
):
    """AC1 + AC3: endpoint returns computed reorder_quantity for highest-urgency risk."""
    now = datetime.now(UTC)
    # Inventory: 12 units of SKU-1, low velocity = will run out soon
    inv_item = InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_with_inventory.id,
        tiktok_sku_id="SKU-1",
        tiktok_product_id="prod-721-1",
        quantity=12,
        update_time=now,
    )
    session.add(inv_item)
    await session.flush()

    # Create completed orders to establish velocity (high velocity = runs out fast)
    for i in range(5):
        order = Order(
            id=uuid.uuid4(),
            shop_id=shop_with_inventory.id,
            tiktok_order_id=f"ord-721-{i}",
            status="COMPLETED",
            total_amount=Decimal("100000"),
            currency="VND",
            created_at=now - timedelta(days=i),
            update_time=now,
        )
        session.add(order)
    await session.flush()

    # Mock get_low_stock_risks to return a high-urgency risk
    # With velocity=5 units/day, 12 units in stock → 2.4 days until stockout
    mock_risks = [
        LowStockRisk(
            sku_id="SKU-1",
            tiktok_product_id="prod-721-1",
            quantity=12,
            daily_velocity=5.0,
            days_until_stockout=2.4,
            urgency_score=41.67,  # 1.0 / 0.024
        )
    ]

    with patch(
        "juli_backend.api.routes.action_cards.get_low_stock_risks",
        new_callable=AsyncMock,
        return_value=mock_risks,
    ):
        # compute_reorder_quantity(velocity=5, lead_time=3, safety_stock=2)
        # = ceil(5 * (3 + 2)) = ceil(25) = 25
        response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["sku_id"] == "SKU-1"
    assert body["data"]["tiktok_product_id"] == "prod-721-1"
    assert body["data"]["current_stock"] == 12
    assert body["data"]["reorder_quantity"] == 25.0
    assert body["data"]["basis"]["daily_velocity"] == 5.0
    assert body["data"]["basis"]["days_until_stockout"] == 2.4


@pytest.mark.asyncio
async def test_ac2_zero_velocity_item_yields_10_unit_fallback(
    session,
    shop_with_inventory,
    auth_client,
):
    """AC2: zero-velocity item returns fallback quantity of 10 (not error/null)."""
    now = datetime.now(UTC)
    inv_item = InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_with_inventory.id,
        tiktok_sku_id="SKU-ZERO",
        tiktok_product_id="prod-zero-velocity",
        quantity=5,
        update_time=now,
    )
    session.add(inv_item)
    await session.flush()

    # Risk with zero velocity (new product, no recent sales)
    mock_risks = [
        LowStockRisk(
            sku_id="SKU-ZERO",
            tiktok_product_id="prod-zero-velocity",
            quantity=5,
            daily_velocity=0.0,
            days_until_stockout=999999.0,  # Effectively infinite for zero-velocity items
            urgency_score=0.0,
        )
    ]

    with patch(
        "juli_backend.api.routes.action_cards.get_low_stock_risks",
        new_callable=AsyncMock,
        return_value=mock_risks,
    ):
        response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["reorder_quantity"] == 10.0  # fallback from compute_reorder_quantity
    assert body["data"]["basis"]["daily_velocity"] == 0.0


@pytest.mark.asyncio
async def test_ac4_response_marks_quantity_editable(
    session,
    shop_with_inventory,
    auth_client,
):
    """AC4: response includes editable: true (backend half of AC4)."""
    now = datetime.now(UTC)
    inv_item = InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_with_inventory.id,
        tiktok_sku_id="SKU-2",
        tiktok_product_id="prod-721-2",
        quantity=8,
        update_time=now,
    )
    session.add(inv_item)
    await session.flush()

    mock_risks = [
        LowStockRisk(
            sku_id="SKU-2",
            tiktok_product_id="prod-721-2",
            quantity=8,
            daily_velocity=2.0,
            days_until_stockout=4.0,
            urgency_score=25.0,
        )
    ]

    with patch(
        "juli_backend.api.routes.action_cards.get_low_stock_risks",
        new_callable=AsyncMock,
        return_value=mock_risks,
    ):
        response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["editable"] is True


@pytest.mark.asyncio
async def test_ac5_empty_low_stock_state_returns_well_formed_response(
    session,
    shop_with_inventory,
    auth_client,
):
    """AC5: empty low-stock state returns 200 with null subject (not 500/404)."""
    # No inventory items, so no risks

    with patch(
        "juli_backend.ai.forecasting.get_low_stock_risks",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["sku_id"] is None
    # No error field for success case
    assert body.get("error") is None


@pytest.mark.asyncio
async def test_ac6_endpoint_does_not_write_to_db(
    session,
    shop_with_inventory,
    auth_client,
):
    """AC6: endpoint does not write to DB (compute-only, no persistence)."""
    now = datetime.now(UTC)
    inv_item = InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_with_inventory.id,
        tiktok_sku_id="SKU-3",
        tiktok_product_id="prod-721-3",
        quantity=10,
        update_time=now,
    )
    session.add(inv_item)
    await session.flush()

    # Record row count before request
    from sqlalchemy import select

    pre_count = len(
        (
            await session.execute(
                select(InventoryItem).where(InventoryItem.shop_id == shop_with_inventory.id)
            )
        )
        .scalars()
        .all()
    )

    mock_risks = [
        LowStockRisk(
            sku_id="SKU-3",
            tiktok_product_id="prod-721-3",
            quantity=10,
            daily_velocity=3.0,
            days_until_stockout=3.33,
            urgency_score=30.0,
        )
    ]

    with patch(
        "juli_backend.api.routes.action_cards.get_low_stock_risks",
        new_callable=AsyncMock,
        return_value=mock_risks,
    ):
        response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

    assert response.status_code == 200

    # Verify no write occurred
    post_count = len(
        (
            await session.execute(
                select(InventoryItem).where(InventoryItem.shop_id == shop_with_inventory.id)
            )
        )
        .scalars()
        .all()
    )
    assert pre_count == post_count


@pytest.mark.asyncio
async def test_ac3_highest_urgency_risk_is_default_subject(
    session,
    shop_with_inventory,
    auth_client,
):
    """AC3: when multiple risks exist, endpoint uses the highest-urgency (first) one."""
    now = datetime.now(UTC)
    # Create two inventory items
    for i, (sku, prod_id, qty, vel) in enumerate(
        [("SKU-A", "prod-a", 20, 5.0), ("SKU-B", "prod-b", 2, 10.0)]
    ):
        inv = InventoryItem(
            id=uuid.uuid4(),
            shop_id=shop_with_inventory.id,
            tiktok_sku_id=sku,
            tiktok_product_id=prod_id,
            quantity=qty,
            update_time=now,
        )
        session.add(inv)
    await session.flush()

    # SKU-B urgency (2/10 = 0.2 days, urgency = 5.0) > SKU-A (20/5 = 4 days, urgency = 0.25)
    # But when sorted, higher urgency comes first
    mock_risks = [
        LowStockRisk(
            sku_id="SKU-B",
            tiktok_product_id="prod-b",
            quantity=2,
            daily_velocity=10.0,
            days_until_stockout=0.2,
            urgency_score=5.0,  # Higher urgency (closer to stockout)
        ),
        LowStockRisk(
            sku_id="SKU-A",
            tiktok_product_id="prod-a",
            quantity=20,
            daily_velocity=5.0,
            days_until_stockout=4.0,
            urgency_score=0.25,  # Lower urgency
        ),
    ]

    with patch(
        "juli_backend.api.routes.action_cards.get_low_stock_risks",
        new_callable=AsyncMock,
        return_value=mock_risks,
    ):
        response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

    assert response.status_code == 200
    body = response.json()
    # Highest urgency (first) should be used
    assert body["data"]["sku_id"] == "SKU-B"
    assert body["data"]["tiktok_product_id"] == "prod-b"


def test_endpoint_does_not_invoke_scoring_pipeline():
    """AC6: the endpoint calls get_low_stock_risks only, not the scoring pipeline."""
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    # After implementation, verify new route file doesn't import scoring
    routes_file = repo_root / "backend/src/juli_backend/api/routes/action_cards.py"
    if routes_file.exists():
        tree = ast.parse(routes_file.read_text(encoding="utf-8"))
        scoring_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "scoring" in node.module:
                    scoring_imports.add(node.module)
        # Only action_cards route file; if inputs are added to the same file,
        # verify no new scoring imports were added (just forecasting)
        # This is a light check — the main assertion is in AC6 (no DB writes)
        assert "services.scoring.pipeline" not in scoring_imports
