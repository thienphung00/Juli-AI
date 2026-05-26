"""Tests for Issue #37: Orders + Products + Inventory + Revenue API endpoints.

Test mapping from acceptance criteria:
- AC1 → test_orders_endpoint_filters
- AC2 → test_confirm_shipment
- AC3 → test_products_ranked_by_revenue
- AC4 → test_inventory_with_velocity
- AC5 → test_revenue_analytics_trends
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.data.models import InventoryItem, Order, Product, Shop, User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(engine, session):
    from src.api.app import create_app
    from src.data import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+84999888777")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Test Shop",
        tiktok_shop_id="tiktok_shop_001",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop):
    from src.auth import get_current_user
    from src.api.dependencies import get_active_shop

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def seed_orders(session, shop):
    """Seed a variety of orders for filter testing."""
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    orders = []
    for i, status_val in enumerate(
        ["AWAITING_SHIPMENT", "SHIPPED", "COMPLETED", "CANCELLED", "AWAITING_SHIPMENT"]
    ):
        order = Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id=f"tt_order_{i}",
            status=status_val,
            total_amount=Decimal(f"{(i + 1) * 100}.00"),
            currency="VND",
            update_time=now - timedelta(days=i),
            created_at=now - timedelta(days=i),
        )
        orders.append(order)
    session.add_all(orders)
    await session.flush()
    return orders


@pytest_asyncio.fixture
async def seed_products(session, shop):
    """Seed products with revenue and units_sold for ranking tests."""
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    products = []
    for i, (revenue, units) in enumerate(
        [(5000, 50), (10000, 100), (2000, 20), (8000, 80)]
    ):
        p = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=f"tt_prod_{i}",
            name=f"Product {i}",
            status="ACTIVE",
            revenue=Decimal(f"{revenue}"),
            units_sold=units,
            update_time=now - timedelta(days=i),
            created_at=now - timedelta(days=i),
        )
        products.append(p)
    session.add_all(products)
    await session.flush()
    return products


@pytest_asyncio.fixture
async def seed_inventory(session, shop):
    """Seed inventory items with velocity data."""
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    items = []
    for i, (qty, vel) in enumerate(
        [(100, "high"), (50, "medium"), (10, "low"), (0, "out_of_stock")]
    ):
        item = InventoryItem(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=f"tt_prod_{i}",
            tiktok_sku_id=f"sku_{i}",
            quantity=qty,
            velocity=vel,
            update_time=now - timedelta(hours=i),
            created_at=now - timedelta(hours=i),
        )
        items.append(item)
    session.add_all(items)
    await session.flush()
    return items


# ---------------------------------------------------------------------------
# AC1: GET /v1/orders — filtering by status, date range, product; paginated
# ---------------------------------------------------------------------------


class TestOrdersEndpointFilters:
    """AC1: GET /v1/orders supports filtering by status, date range, product."""

    async def test_list_orders_returns_paginated(self, auth_client, seed_orders):
        resp = await auth_client.get("/v1/orders", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) <= 2
        assert "next_cursor" in data

    async def test_filter_by_status(self, auth_client, seed_orders):
        resp = await auth_client.get(
            "/v1/orders", params={"status": "AWAITING_SHIPMENT"}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        assert all(o["status"] == "AWAITING_SHIPMENT" for o in items)

    async def test_filter_by_date_range(self, auth_client, seed_orders):
        now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
        date_from = (now - timedelta(days=2)).isoformat()
        date_to = (now + timedelta(hours=1)).isoformat()
        resp = await auth_client.get(
            "/v1/orders", params={"date_from": date_from, "date_to": date_to}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 3  # orders 0, 1, 2 (within last 2 days)

    async def test_pagination_cursor(self, auth_client, seed_orders):
        resp1 = await auth_client.get("/v1/orders", params={"limit": 3})
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert len(data1["items"]) == 3
        cursor = data1["next_cursor"]
        assert cursor is not None

        resp2 = await auth_client.get(
            "/v1/orders", params={"limit": 3, "after": cursor}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) >= 1
        ids_page1 = {o["id"] for o in data1["items"]}
        ids_page2 = {o["id"] for o in data2["items"]}
        assert ids_page1.isdisjoint(ids_page2)


# ---------------------------------------------------------------------------
# AC2: POST /v1/orders/{id}/confirm-shipment
# ---------------------------------------------------------------------------


class TestConfirmShipment:
    """AC2: POST /v1/orders/{id}/confirm-shipment marks order as shipped."""

    async def test_confirm_shipment_success(self, auth_client, seed_orders):
        awaiting = [o for o in seed_orders if o.status == "AWAITING_SHIPMENT"][0]
        resp = await auth_client.post(f"/v1/orders/{awaiting.id}/confirm-shipment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SHIPPED"
        assert "shipped_at" in data
        assert data["shipped_at"] is not None

    async def test_confirm_shipment_wrong_status(self, auth_client, seed_orders):
        completed = [o for o in seed_orders if o.status == "COMPLETED"][0]
        resp = await auth_client.post(f"/v1/orders/{completed.id}/confirm-shipment")
        assert resp.status_code == 409

    async def test_confirm_shipment_not_found(self, auth_client, seed_orders):
        fake_id = uuid.uuid4()
        resp = await auth_client.post(f"/v1/orders/{fake_id}/confirm-shipment")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC3: GET /v1/products — ranked by revenue with units sold
# ---------------------------------------------------------------------------


class TestProductsRankedByRevenue:
    """AC3: GET /v1/products returns products ranked by revenue with units sold."""

    async def test_products_ranked_by_revenue(self, auth_client, seed_products):
        resp = await auth_client.get("/v1/products")
        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]
        assert len(items) == 4
        revenues = [Decimal(p["revenue"]) for p in items]
        assert revenues == sorted(revenues, reverse=True)

    async def test_products_include_units_sold(self, auth_client, seed_products):
        resp = await auth_client.get("/v1/products")
        assert resp.status_code == 200
        items = resp.json()["items"]
        for p in items:
            assert "units_sold" in p
            assert isinstance(p["units_sold"], int)

    async def test_products_paginated(self, auth_client, seed_products):
        resp = await auth_client.get("/v1/products", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert "next_cursor" in data


# ---------------------------------------------------------------------------
# AC4: GET /v1/inventory — current stock levels with velocity indicator
# ---------------------------------------------------------------------------


class TestInventoryWithVelocity:
    """AC4: GET /v1/inventory returns stock levels with velocity indicator."""

    async def test_inventory_list(self, auth_client, seed_inventory):
        resp = await auth_client.get("/v1/inventory")
        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]
        assert len(items) == 4

    async def test_inventory_has_velocity(self, auth_client, seed_inventory):
        resp = await auth_client.get("/v1/inventory")
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            assert "velocity" in item
            assert item["velocity"] in ("high", "medium", "low", "out_of_stock")

    async def test_inventory_has_quantity(self, auth_client, seed_inventory):
        resp = await auth_client.get("/v1/inventory")
        assert resp.status_code == 200
        items = resp.json()["items"]
        for item in items:
            assert "quantity" in item
            assert "tiktok_sku_id" in item

    async def test_inventory_paginated(self, auth_client, seed_inventory):
        resp = await auth_client.get("/v1/inventory", params={"limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert "next_cursor" in data


# ---------------------------------------------------------------------------
# AC5: GET /v1/analytics/revenue — daily/weekly/monthly GMV with trend
# ---------------------------------------------------------------------------


class TestRevenueAnalyticsTrends:
    """AC5: GET /v1/analytics/revenue returns GMV with trend direction."""

    async def test_revenue_daily(self, auth_client, seed_orders):
        resp = await auth_client.get(
            "/v1/analytics/revenue", params={"period": "daily"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gmv" in data
        assert "trend" in data
        assert data["trend"] in ("up", "down", "flat")
        assert "data_points" in data

    async def test_revenue_weekly(self, auth_client, seed_orders):
        resp = await auth_client.get(
            "/v1/analytics/revenue", params={"period": "weekly"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gmv" in data
        assert "data_points" in data

    async def test_revenue_monthly(self, auth_client, seed_orders):
        resp = await auth_client.get(
            "/v1/analytics/revenue", params={"period": "monthly"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gmv" in data

    async def test_revenue_default_period_is_daily(self, auth_client, seed_orders):
        resp = await auth_client.get("/v1/analytics/revenue")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_gmv" in data
        assert "trend" in data

    async def test_revenue_invalid_period(self, auth_client, seed_orders):
        resp = await auth_client.get(
            "/v1/analytics/revenue", params={"period": "hourly"}
        )
        assert resp.status_code == 422
