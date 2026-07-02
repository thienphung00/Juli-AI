import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.database.models import Shop, User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(engine):
    from backend.api.api.app import create_app
    from backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+84123456789")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user):
    from backend.integrations.identity.infrastructure.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_api_boots_with_versioned_routes(client):
    """AC1: FastAPI app boots with /v1/* router and OpenAPI docs."""
    resp = await client.get("/docs")
    assert resp.status_code == 200

    openapi = await client.get("/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json().get("paths", {})
    assert any(path.startswith("/v1/") for path in paths)


async def test_api_rejects_unauthenticated(client):
    """AC2: Auth middleware rejects unauthenticated requests with 401."""
    resp = await client.get("/v1/shops")
    assert resp.status_code == 401
    assert "detail" in resp.json()


async def test_list_shops_returns_user_shops(auth_client, session, user_id):
    """AC3: GET /v1/shops returns authenticated user's connected shops."""
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Test Shop",
        tiktok_shop_id="tiktok_123",
    )
    session.add(shop)
    await session.flush()

    resp = await auth_client.get("/v1/shops")
    assert resp.status_code == 200

    data = resp.json()
    assert len(data) == 1
    assert data[0]["shop_name"] == "Test Shop"
    assert data[0]["tiktok_shop_id"] == "tiktok_123"


async def test_shop_scoping_header(auth_client, session, user_id):
    """AC4: X-Shop-Id header scopes requests; invalid shop_id returns 403."""
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="My Shop",
        tiktok_shop_id="tiktok_456",
    )
    session.add(shop)
    await session.flush()

    resp = await auth_client.get(
        "/v1/shops/me", headers={"X-Shop-Id": str(shop.id)}
    )
    assert resp.status_code == 200
    assert resp.json()["shop_name"] == "My Shop"

    fake_id = str(uuid.uuid4())
    resp = await auth_client.get(
        "/v1/shops/me", headers={"X-Shop-Id": fake_id}
    )
    assert resp.status_code == 403
