"""Tests for temporary TikTok debug verify-connection endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.database.models import Shop, User
from backend.database.repos import TikTokCredentialRepo

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
VERIFY_PATH = "/debug/tiktok/verify-connection"
CALLBACK_PATH = "/v1/auth/tiktok/callback"


@pytest.fixture(autouse=True)
def tiktok_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("ENABLE_TIKTOK_DEBUG", "1")


@pytest.fixture(autouse=True)
def mock_token_exchange(monkeypatch):
    mock = MagicMock(
        return_value={
            "access_token": "ROW_secret_access",
            "refresh_token": "ROW_secret_refresh",
            "access_token_expire_in": 1783658262,
            "open_id": "seller_123",
            "seller_name": "VN Test Shop",
            "granted_scopes": ["seller.shop.info"],
        }
    )
    monkeypatch.setattr(
        "backend.integrations.catalog.domain.integrations.tiktok.auth.TikTokAuth.exchange_code",
        mock,
    )
    return mock


@pytest_asyncio.fixture
async def client(engine, monkeypatch):
    from backend.api.api.app import create_app
    from backend.database import get_session
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def stored_credential(session, user_id):
    user = User(id=user_id, phone="+84901234567")
    session.add(user)
    await session.flush()

    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="VN Test Shop",
        tiktok_shop_id="seller_123",
    )
    session.add(shop)
    await session.flush()

    credential = await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token="stored_access_token",
        refresh_token="stored_refresh_token",
        token_expires_at=__import__("datetime").datetime(2026, 7, 10),
    )
    await session.commit()
    return credential, shop


class TestVerifyConnectionRoute:
    @pytest.mark.asyncio
    async def test_verify_connection_hidden_when_debug_disabled(
        self, client, stored_credential, monkeypatch
    ):
        monkeypatch.delenv("ENABLE_TIKTOK_DEBUG", raising=False)
        resp = await client.get(VERIFY_PATH)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_connection_returns_shop_metadata(
        self, client, stored_credential
    ):
        with patch(
            "backend.api.services.tiktok.verify_connection.TikTokVerifyConnectionService.verify",
            new=AsyncMock(
                return_value={
                    "connected": True,
                    "shop_id": "7494512345678901234",
                    "shop_name": "VN Test Shop",
                    "market": "VN",
                }
            ),
        ):
            resp = await client.get(VERIFY_PATH)

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "connected": True,
            "shop_id": "7494512345678901234",
            "shop_name": "VN Test Shop",
            "market": "VN",
            "error": None,
        }
        assert "ROW_secret_access" not in resp.text

    @pytest.mark.asyncio
    async def test_verify_connection_without_credentials_returns_404(
        self, client
    ):
        resp = await client.get(VERIFY_PATH)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "No stored TikTok credentials found"

    @pytest.mark.asyncio
    async def test_oauth_callback_persists_credentials_for_verify(
        self, client, session, mock_token_exchange
    ):
        resp = await client.get(
            CALLBACK_PATH,
            params={
                "code": "ROW_test_auth_code",
                "locale": "vi-VN",
                "shop_region": "VN",
            },
        )
        assert resp.status_code == 200

        credential = await TikTokCredentialRepo(session).get_latest()
        assert credential.access_token == "ROW_secret_access"
        assert credential.refresh_token == "ROW_secret_refresh"

        with patch(
            "backend.api.services.tiktok.verify_connection.TikTokVerifyConnectionService.verify",
            new=AsyncMock(
                return_value={
                    "connected": True,
                    "shop_id": "7494512345678901234",
                    "shop_name": "VN Test Shop",
                    "market": "VN",
                }
            ),
        ):
            verify = await client.get(VERIFY_PATH)

        assert verify.status_code == 200
        assert verify.json()["connected"] is True
        assert verify.json()["market"] == "VN"
