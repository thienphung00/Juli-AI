"""Tests for the TikTok debug verify-connection endpoint.

Since #903 the route is gated three ways: not mounted in production at all, requires an
authenticated session that owns the shop (``get_active_shop``), and still honours
``ENABLE_TIKTOK_DEBUG`` within non-production. It no longer accepts a client-supplied
``shop_id`` or ``merchant_authorization_id`` — those made it a cross-tenant probe.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.integrations.tiktok.merchant import (
    TikTokCapability,
)
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo

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
        "juli_backend.integrations.tiktok.auth.TikTokAuth.exchange_code",
        mock,
    )
    return mock


@pytest_asyncio.fixture
async def client(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
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
        merchant_authorization_id="seller_123",
        capability=TikTokCapability.SELLER_CONNECT.value,
    )
    await session.commit()
    return credential, shop


@pytest_asyncio.fixture
async def authed_client(engine, stored_credential):
    """Client whose caller owns the shop that holds the stored credential.

    Overrides ``get_active_shop`` rather than minting a JWT: the ownership logic itself
    is covered by the dependency's own tests, and what matters here is that the route
    *depends* on it and operates only on the shop it returns.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.api.app import create_app
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.database import get_session

    _, shop = stored_credential
    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
        yield c


class TestVerifyConnectionRoute:
    @pytest.mark.asyncio
    async def test_verify_connection_hidden_when_debug_disabled(
        self, client, stored_credential, monkeypatch
    ):
        monkeypatch.delenv("ENABLE_TIKTOK_DEBUG", raising=False)
        resp = await client.get(VERIFY_PATH)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_connection_returns_shop_metadata(self, authed_client, stored_credential):
        with patch(
            "juli_backend.services.tiktok.verify_connection.TikTokVerifyConnectionService.verify",
            new=AsyncMock(
                return_value={
                    "connected": True,
                    "shop_id": "7494512345678901234",
                    "shop_name": "VN Test Shop",
                    "market": "VN",
                }
            ),
        ):
            # No shop_id parameter exists any more — the route reads the active shop.
            resp = await authed_client.get(VERIFY_PATH)

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
    async def test_verify_connection_requires_an_owned_shop(self, client):
        """Unauthenticated callers cannot reach it at all (#903).

        Previously this returned 400 complaining about missing query parameters, which
        told an anonymous caller the route existed and was usable. Now the ownership
        dependency rejects them before any lookup happens.
        """
        resp = await client.get(VERIFY_PATH)
        assert resp.status_code in (401, 403, 422), resp.text
        assert "merchant_authorization_id" not in resp.text

    @pytest.mark.asyncio
    async def test_verify_connection_404s_when_the_owned_shop_has_no_credentials(
        self, engine, session, user_id
    ):
        """An owned shop with nothing stored is a 404, not a leak about other shops."""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from juli_backend.api.app import create_app
        from juli_backend.api.dependencies import get_active_shop
        from juli_backend.database import get_session

        session.add(User(id=user_id, phone="+84901234567"))
        await session.flush()
        bare_shop = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name="No Creds Shop",
            tiktok_shop_id="seller_nocreds",
        )
        session.add(bare_shop)
        await session.commit()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        application = create_app()

        async def _test_session():
            async with factory() as sess:
                yield sess

        application.dependency_overrides[get_session] = _test_session
        application.dependency_overrides[get_active_shop] = lambda: bare_shop

        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as c:
            resp = await c.get(VERIFY_PATH)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_oauth_callback_persists_credentials_for_verify(
        self, client, engine, session, mock_token_exchange
    ):
        """End-to-end: OAuth callback stores a credential, verify reads it back.

        Deliberately does not use the ``authed_client`` fixture — that fixture depends on
        ``stored_credential``, which pre-claims the shop, so the callback under test
        would fail with ``tiktok_shop_already_claimed``. Instead the shop the callback
        itself creates becomes the active shop.
        """
        resp = await client.get(
            CALLBACK_PATH,
            params={
                "code": "ROW_test_auth_code",
                "locale": "vi-VN",
                "shop_region": "VN",
            },
        )
        assert resp.status_code == 200

        with patch(
            "juli_backend.services.tiktok.verify_connection.TikTokVerifyConnectionService.verify",
            new=AsyncMock(
                return_value={
                    "connected": True,
                    "shop_id": "7494512345678901234",
                    "shop_name": "VN Test Shop",
                    "market": "VN",
                }
            ),
        ):
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from juli_backend.api.app import create_app
            from juli_backend.api.dependencies import get_active_shop
            from juli_backend.database import get_session

            created_shop = (await session.execute(select(Shop))).scalars().first()
            assert created_shop is not None, "callback did not create a shop"

            factory = async_sessionmaker(engine, expire_on_commit=False)
            application = create_app()

            async def _test_session():
                async with factory() as sess:
                    yield sess

            application.dependency_overrides[get_session] = _test_session
            application.dependency_overrides[get_active_shop] = lambda: created_shop

            async with AsyncClient(
                transport=ASGITransport(app=application), base_url="http://test"
            ) as authed:
                verify = await authed.get(VERIFY_PATH)

        assert verify.status_code == 200
        assert verify.json()["connected"] is True
        assert verify.json()["market"] == "VN"
