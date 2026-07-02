"""Tests for Issue #38: Livestream + Creator + Settlement API endpoints.

Test mapping:
- AC1 → test_livestreams_endpoint_session_metrics
- AC2 → test_creators_endpoint_attribution
- AC3 → test_creator_content_funnel
- AC4 → test_settlements_net_revenue
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.database.models import Creator, Livestream, Settlement, Shop, User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def settlement(session, shop):
    now = datetime.now(timezone.utc)
    s = Settlement(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_settlement_id="settle_001",
        amount=Decimal("1000000.00"),
        currency="VND",
        status="confirmed",
        platform_commission=Decimal("50000.00"),
        affiliate_commission=Decimal("30000.00"),
        shipping_fee=Decimal("20000.00"),
        settlement_time=now,
        update_time=now,
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, shop):
    from backend.api.api.dependencies import get_active_shop

    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# AC1 — GET /v1/livestreams returns session metrics
# ---------------------------------------------------------------------------


async def test_livestreams_endpoint_session_metrics(
    auth_client, creator, livestream
):
    """AC1: Returns per-session metrics: duration, viewers, peak concurrent, orders placed."""
    resp = await auth_client.get("/v1/livestreams")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["tiktok_livestream_id"] == "live_001"
    assert item["title"] == "Flash Sale Stream"
    assert "duration_seconds" in item
    assert item["duration_seconds"] == 3600
    assert item["viewer_count"] == 1000
    assert item["peak_concurrent_viewers"] == 800
    assert item["order_count"] == 50


# ---------------------------------------------------------------------------
# AC2 — GET /v1/creators returns GMV attribution and commission efficiency
# ---------------------------------------------------------------------------


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
    # commission_efficiency = total_gmv * commission_rate
    assert Decimal(item["commission_efficiency"]) == Decimal("250000.0000")


# ---------------------------------------------------------------------------
# AC3 — GET /v1/creators/{id}/content returns conversion funnel
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# AC4 — GET /v1/settlements returns net revenue after deductions
# ---------------------------------------------------------------------------


async def test_settlements_net_revenue(auth_client, settlement):
    """AC4: Returns net revenue after platform commission, affiliate commission, shipping fees."""
    resp = await auth_client.get("/v1/settlements")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1

    item = data["items"][0]
    assert item["tiktok_settlement_id"] == "settle_001"
    assert item["status"] == "confirmed"
    assert "gross_amount" in item
    assert "platform_commission" in item
    assert "affiliate_commission" in item
    assert "shipping_fee" in item
    assert "net_revenue" in item

    # net_revenue = amount - platform_commission - affiliate_commission - shipping_fee
    gross = Decimal(item["gross_amount"])
    net = Decimal(item["net_revenue"])
    deductions = (
        Decimal(item["platform_commission"])
        + Decimal(item["affiliate_commission"])
        + Decimal(item["shipping_fee"])
    )
    assert gross - deductions == net
    assert net == Decimal("900000.00")
