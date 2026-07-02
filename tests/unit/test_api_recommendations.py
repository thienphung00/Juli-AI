"""GET /v1/recommendations — Issue #93 AC5 (extended host_product_match schema)."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import (
    Creator,
    InventoryItem,
    Livestream,
    Order,
    Product,
    Shop,
    User,
)
from backend.database.repos import GraphRepo

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(engine, session):
    from backend.api.api.app import create_app
    from backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+84999888093")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Reco API Shop 93",
        tiktok_shop_id="tiktok_shop_093",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop):
    from backend.api.api.dependencies import get_active_shop
    from backend.integrations.identity.infrastructure.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _seed_host_match_shop(session: AsyncSession, shop_id: uuid.UUID) -> tuple[Creator, Product]:
    creator = Creator(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_creator_id="creator_api_93",
        name="Lan",
        commission_rate=Decimal("0.08"),
    )
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id="prod_api_93",
        name="Serum dưỡng",
        status="ACTIVE",
        revenue=Decimal("3000000"),
        units_sold=120,
        update_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    live = Livestream(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_livestream_id="live_api_93",
        creator_id=creator.id,
        title="Live test",
        start_time=datetime.now(timezone.utc) - timedelta(hours=3),
        end_time=datetime.now(timezone.utc) - timedelta(hours=2),
        viewer_count=800,
        order_count=40,
        revenue=Decimal("8000000"),
        update_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    inv = InventoryItem(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id=product.tiktok_product_id,
        tiktok_sku_id="sku_api_93",
        quantity=50,
        velocity="medium",
        update_time=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    session.add_all([creator, product, live, inv])

    now = datetime.now(timezone.utc)
    orders = [
        Order(
            id=uuid.uuid4(),
            shop_id=shop_id,
            tiktok_order_id=f"ord_{i}",
            status="COMPLETED",
            total_amount=Decimal("100.00"),
            currency="VND",
            update_time=now - timedelta(days=i),
            created_at=now - timedelta(days=i),
        )
        for i in range(14)
    ]
    session.add_all(orders)
    await session.flush()

    repo = GraphRepo(session)
    await repo.upsert_edge(
        shop_id,
        edge_type="potential_match",
        source_node_type="creator",
        source_node_id=creator.id,
        target_node_type="product",
        target_node_id=product.id,
        weight=Decimal("0.92"),
    )
    return creator, product


async def test_recommendations_host_product_match_extended_schema(
    auth_client,
    session,
    shop,
):
    """AC5: GET /v1/recommendations returns predicted_outcome, match_score, action_type."""
    await _seed_host_match_shop(session, shop.id)

    resp = await auth_client.get(
        "/v1/recommendations",
        headers={"X-Shop-Id": str(shop.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    items = body["data"]
    assert len(items) >= 1

    host_items = [
        i for i in items if i["recommendation_type"] == "host_product_match"
    ]
    assert host_items, "expected refreshed host_product_match rows"

    item = host_items[0]
    assert isinstance(item["match_score"], (int, float))
    assert item["match_score"] > 0
    assert item["action_type"] in (
        "contact_creator",
        "adjust_commission",
        "schedule_live",
    )
    assert item["confidence"] in ("high", "medium", "low")
    assert item["cta"]
    assert item.get("source") in ("llm", "rules")

    predicted = item["predicted_outcome"]
    assert predicted is not None
    assert "low" in predicted["gmv_vnd_week"]
    assert "high" in predicted["gmv_vnd_week"]
    assert predicted["gmv_vnd_week"]["high"] >= predicted["gmv_vnd_week"]["low"]
    assert isinstance(predicted["conversion_pct"], (int, float))
    assert isinstance(predicted["engagement_index"], (int, float))
    assert isinstance(predicted["risk_factors"], list)

    payload = item.get("payload") or {}
    assert payload.get("creator_id")
    assert payload.get("tiktok_product_id")
