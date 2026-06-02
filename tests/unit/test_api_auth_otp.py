"""OTP auth routes proxy Supabase and provision local users."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.asyncio

FAKE_USER_ID = uuid.uuid4()
FAKE_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test.signature"


@pytest_asyncio.fixture
async def app(engine):
    from src.apps.api_gateway.api.app import create_app
    from src.shared.utils.data import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async with factory() as shared:
        async def _test_session():
            yield shared

        application.dependency_overrides[get_session] = _test_session
        yield application, shared
        await shared.commit()
        application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    application, _shared = app
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session(app):
    _application, shared = app
    return shared


async def test_send_otp_success(client):
    mock_auth = AsyncMock()
    mock_auth.send_otp = AsyncMock()
    mock_auth.close = AsyncMock()

    with patch("src.apps.api_gateway.api.routers.auth._supabase_auth", return_value=mock_auth):
        with patch.dict(
            "os.environ",
            {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "key"},
        ):
            resp = await client.post(
                "/v1/auth/otp/send",
                json={"phone": "0901234567"},
            )

    assert resp.status_code == 200
    mock_auth.send_otp.assert_awaited_once_with("+84901234567")


async def test_verify_otp_provisions_user(client, db_session):
    mock_auth = AsyncMock()
    mock_auth.verify_otp = AsyncMock(
        return_value={
            "access_token": FAKE_JWT,
            "user": {"id": str(FAKE_USER_ID), "phone": "+84901234567"},
        }
    )
    mock_auth.close = AsyncMock()

    with patch("src.apps.api_gateway.api.routers.auth._supabase_auth", return_value=mock_auth):
        with patch.dict(
            "os.environ",
            {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "key"},
        ):
            resp = await client.post(
                "/v1/auth/otp/verify",
                json={"phone": "+84901234567", "token": "123456"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == FAKE_JWT
    assert data["user"]["id"] == str(FAKE_USER_ID)

    from src.shared.utils.data.repos import UsersRepo

    user = await UsersRepo(db_session).get(FAKE_USER_ID)
    assert user.phone == "+84901234567"


async def test_send_otp_requires_supabase_config(client):
    with patch.dict("os.environ", {}, clear=True):
        resp = await client.post(
            "/v1/auth/otp/send",
            json={"phone": "+84901234567"},
        )
    assert resp.status_code == 503
