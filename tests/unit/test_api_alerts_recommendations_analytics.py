"""Tests for Issue #43: Alerts + recommendations + daily analytics API.

Test mapping from acceptance criteria:
- AC1 → test_alert_history_endpoint
- AC2 → test_alert_config_crud
- AC3 → test_recommendations_endpoint
- AC4 → test_daily_analytics_profit
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.shared.utils.data.models import (
    AlertConfig,
    AlertHistory,
    InventoryItem,
    Order,
    Product,
    Recommendation,
    Shop,
    User,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(engine, session):
    from src.apps.api_gateway.api.app import create_app
    from src.shared.utils.data import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+84999888443")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="API Shop 43",
        tiktok_shop_id="tiktok_shop_043",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop):
    from src.apps.api_gateway.api.dependencies import get_active_shop
    from src.modules.identity.infrastructure.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def seed_alert_history(session, shop):
    config = AlertConfig(
        id=uuid.uuid4(),
        shop_id=shop.id,
        alert_type="low_stock",
        channel="fcm",
        threshold_json=json.dumps({"min_quantity": 5}),
        is_active=True,
    )
    session.add(config)
    await session.flush()

    now = datetime.now(timezone.utc)
    entries = []
    for i in range(3):
        entry = AlertHistory(
            id=uuid.uuid4(),
            shop_id=shop.id,
            alert_config_id=config.id,
            triggered_at=now - timedelta(hours=i),
            payload=json.dumps({"sku_id": f"sku_{i}"}),
            status="delivered",
        )
        entries.append(entry)
    session.add_all(entries)
    await session.flush()
    return config, entries


@pytest_asyncio.fixture
async def seed_recommendations(session, shop):
    now = datetime.now(timezone.utc)
    rec = Recommendation(
        id=uuid.uuid4(),
        shop_id=shop.id,
        recommendation_type="product_push",
        payload=json.dumps(
            {
                "message": "Đẩy sản phẩm A trong live tối nay",
                "cta": "Thêm vào giỏ live",
                "tiktok_product_id": "prod_a",
            }
        ),
        status="active",
        expires_at=now + timedelta(days=1),
    )
    session.add(rec)
    await session.flush()
    return rec


@pytest_asyncio.fixture
async def seed_daily_analytics(session, shop):
    """Orders from yesterday and products/inventory for SKU profit breakdown."""
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    orders = [
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id="ord_y1",
            status="COMPLETED",
            total_amount=Decimal("1000.00"),
            currency="VND",
            update_time=yesterday.replace(hour=10),
            created_at=yesterday.replace(hour=10),
        ),
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id="ord_y2",
            status="COMPLETED",
            total_amount=Decimal("500.00"),
            currency="VND",
            update_time=yesterday.replace(hour=14),
            created_at=yesterday.replace(hour=14),
        ),
    ]
    session.add_all(orders)

    products = []
    inventory = []
    for i, (revenue, units, qty) in enumerate(
        [(800, 8, 3), (400, 4, 50)]
    ):
        pid = f"tt_prod_{i}"
        p = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=pid,
            name=f"Product {i}",
            status="ACTIVE",
            revenue=Decimal(str(revenue)),
            units_sold=units,
            update_time=yesterday,
            created_at=yesterday,
        )
        products.append(p)
        inventory.append(
            InventoryItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id=pid,
                tiktok_sku_id=f"sku_{i}",
                quantity=qty,
                velocity="high" if qty < 10 else "low",
                update_time=yesterday,
                created_at=yesterday,
            )
        )
    session.add_all(products + inventory)
    await session.flush()
    return orders, products, inventory


async def test_alert_history_endpoint(auth_client, seed_alert_history):
    """AC1: GET /v1/alerts/history returns paginated alert history."""
    resp = await auth_client.get("/v1/alerts/history", params={"limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) <= 2
    assert "next_cursor" in data
    item = data["items"][0]
    assert item["alert_type"] == "low_stock"
    assert item["status"] == "delivered"
    assert "triggered_at" in item


async def test_alert_config_crud(auth_client, shop, session):
    """AC2: PUT /v1/alerts/config creates/updates alert rules per shop."""
    body = {
        "rules": [
            {
                "alert_type": "revenue_milestone",
                "channel": "fcm",
                "is_active": True,
                "threshold": {"min_revenue": 1_000_000},
                "cooldown_seconds": 1800,
            }
        ]
    }
    resp = await auth_client.put("/v1/alerts/config", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rules"]) == 1
    assert data["rules"][0]["alert_type"] == "revenue_milestone"
    assert data["rules"][0]["is_active"] is True

    resp2 = await auth_client.put(
        "/v1/alerts/config",
        json={
            "rules": [
                {
                    "alert_type": "revenue_milestone",
                    "channel": "fcm",
                    "is_active": False,
                    "threshold": {"min_revenue": 2_000_000},
                }
            ]
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["rules"][0]["is_active"] is False

    from src.shared.utils.data.repos import AlertConfigsRepo

    repo = AlertConfigsRepo(session)
    stored = await repo.get_by_type(shop.id, "revenue_milestone")
    assert stored is not None
    assert stored.is_active is False


async def test_recommendations_endpoint(
    auth_client, seed_recommendations, seed_daily_analytics
):
    """AC3: GET /v1/recommendations returns recommendations with CTAs."""
    resp = await auth_client.get("/v1/recommendations")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "data" in data
    assert len(data["data"]) >= 1
    item = data["data"][0]
    assert "recommendation_type" in item
    assert "message" in item
    assert "cta" in item
    assert item["cta"]


async def test_daily_analytics_profit(auth_client, seed_daily_analytics):
    """AC4: GET /v1/analytics/daily returns yesterday profit by SKU + prep checklist."""
    expected_date = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

    resp = await auth_client.get("/v1/analytics/daily")
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == expected_date
    assert "total_profit" in data
    assert Decimal(data["total_profit"]) > 0
    assert "sku_breakdown" in data
    assert len(data["sku_breakdown"]) >= 1
    sku = data["sku_breakdown"][0]
    assert "sku_id" in sku
    assert "profit" in sku
    assert "prep_checklist" in data
    assert isinstance(data["prep_checklist"], list)
