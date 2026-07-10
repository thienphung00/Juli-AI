"""Tests for Issue #38: Creator API endpoints.

Test mapping:
- AC2 → test_creators_endpoint_attribution
- AC3 → test_creator_content_funnel
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.models.models import Creator, Livestream, Shop, User

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
    user = User(id=user_id, phone="+84999888001")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Test Shop 38",
        tiktok_shop_id="tiktok_shop_038",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def creator(session, shop):
    now = datetime.now(timezone.utc)
    c = Creator(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_creator_id="creator_001",
        name="Nguyen Van A",
        follower_count=50000,
        total_gmv=Decimal("5000000.00"),
        commission_rate=Decimal("0.05"),
        update_time=now,
    )
    session.add(c)
    await session.flush()
    return c


@pytest_asyncio.fixture
async def livestream(session, shop, creator):
    now = datetime.now(timezone.utc)
    ls = Livestream(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_livestream_id="live_001",
        creator_id=creator.id,
        title="Flash Sale Stream",
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(hours=1),
        viewer_count=1000,
        peak_concurrent_viewers=800,
        order_count=50,
        click_count=200,
        revenue=Decimal("2000000.00"),
        update_time=now,
    )
    session.add(ls)
    await session.flush()
    return ls


@pytest_asyncio.fixture
async def auth_client(app, shop):
    from juli_backend.api.dependencies import get_active_shop

    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_creators_endpoint_attribution(auth_client, creator, livestream):
    """AC2: Returns per-creator GMV attribution and commission efficiency ratio."""
    resp = await auth_client.get("/v1/creators")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["tiktok_creator_id"] == "creator_001"
    assert item["name"] == "Nguyen Van A"
    assert "total_gmv" in item
    assert Decimal(item["total_gmv"]) == Decimal("5000000.00")
    assert "commission_efficiency" in item
    assert Decimal(item["commission_efficiency"]) == Decimal("250000.0000")


async def test_creator_content_funnel(auth_client, creator, livestream):
    """AC3: Returns content-to-conversion funnel: views → clicks → orders."""
    resp = await auth_client.get(f"/v1/creators/{creator.id}/content")

    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data

    assert len(data["sessions"]) == 1
    session_data = data["sessions"][0]
    assert session_data["tiktok_livestream_id"] == "live_001"
    assert session_data["views"] == 1000
    assert session_data["clicks"] == 200
    assert session_data["orders"] == 50


async def test_creator_content_funnel_404(auth_client):
    """AC3: Returns 404 for unknown creator."""
    resp = await auth_client.get(f"/v1/creators/{uuid.uuid4()}/content")

    assert resp.status_code == 404
