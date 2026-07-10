"""Tests for Issue #43: Recommendations API.

Test mapping from acceptance criteria:
- AC3 → test_recommendations_endpoint
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.models.models import (
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
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


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
    """Products/inventory for recommendation engine refresh."""
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
    ]
    session.add_all(orders)

    products = []
    inventory = []
    for i, (revenue, units, qty) in enumerate([(800, 8, 3), (400, 4, 50)]):
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
