"""Route tests for TikTok OAuth callback infrastructure (GET /v1/auth/tiktok/callback)."""

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.integrations.catalog.domain.integrations.tiktok.exceptions import (
    AuthenticationError,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
CALLBACK_PATH = "/v1/auth/tiktok/callback"

TOKEN_FIXTURE = {
    "access_token": "ROW_secret_access",
    "refresh_token": "ROW_secret_refresh",
    "access_token_expire_in": 604800,
    "open_id": "seller_123",
    "seller_name": "Test Shop",
}


def _build_state(user_id: uuid.UUID, *, secret: str = APP_SECRET) -> str:
    payload = json.dumps(
        {"user_id": str(user_id), "nonce": secrets.token_urlsafe(16)}
    )
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    signature = hmac.new(
        secret.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


@pytest.fixture(autouse=True)
def tiktok_oauth_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)


@pytest.fixture(autouse=True)
def mock_token_exchange(monkeypatch):
    mock = MagicMock(return_value=dict(TOKEN_FIXTURE))
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


class TestOAuthCallbackRoute:
    @pytest.mark.asyncio
    async def test_callback_missing_params_returns_400(self, client):
        resp = await client.get(CALLBACK_PATH)
        assert resp.status_code == 400
        assert "code" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_accepts_code_without_state(
        self, client, mock_token_exchange
    ):
        """Partner Center redirects with code but no state (App Review flow)."""
        resp = await client.get(
            CALLBACK_PATH,
            params={
                "app_key": "6kdu4f07vvlv9",
                "code": "ROW_test_auth_code",
                "locale": "vi-VN",
                "shop_region": "VN",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "completed" in body["message"].lower()
        assert body["open_id_present"] is True
        mock_token_exchange.assert_called_once_with("ROW_test_auth_code")

    @pytest.mark.asyncio
    async def test_callback_rejects_invalid_state(self, client, mock_token_exchange):
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code", "state": "tampered.state"},
        )
        assert resp.status_code == 401
        mock_token_exchange.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_exchanges_code_and_returns_sanitized_response(
        self, client, user_id, mock_token_exchange
    ):
        state = _build_state(user_id)
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code_123", "state": state},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "completed" in body["message"].lower()
        assert body["open_id_present"] is True
        assert body["access_token_expires_in"] == 604800
        mock_token_exchange.assert_called_once_with("auth_code_123")

        raw = resp.text
        assert TOKEN_FIXTURE["access_token"] not in raw
        assert TOKEN_FIXTURE["refresh_token"] not in raw

    @pytest.mark.asyncio
    async def test_callback_token_exchange_failure_returns_502(
        self, client, mock_token_exchange
    ):
        mock_token_exchange.side_effect = AuthenticationError(
            code=100002, message="Invalid auth code"
        )
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "bad_code"},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "TikTok token exchange failed"
        assert TOKEN_FIXTURE["access_token"] not in resp.text

    @pytest.mark.asyncio
    async def test_callback_missing_app_key_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        resp = await client.get(CALLBACK_PATH, params={"code": "auth_code"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "TikTok OAuth is not configured"

    @pytest.mark.asyncio
    async def test_callback_missing_app_secret_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        resp = await client.get(CALLBACK_PATH, params={"code": "auth_code"})
        assert resp.status_code == 503
        assert resp.json()["detail"] == "TikTok OAuth is not configured"

    @pytest.mark.asyncio
    async def test_callback_does_not_require_jwt(self, client):
        """Public OAuth redirect must not require Supabase JWT."""
        resp = await client.get(CALLBACK_PATH)
        assert resp.status_code != 401 or "authorization" not in resp.json().get(
            "detail", ""
        ).lower()

    @pytest.mark.asyncio
    async def test_callback_route_is_listed_in_openapi(self, client):
        openapi = await client.get("/openapi.json")
        assert openapi.status_code == 200
        assert CALLBACK_PATH in openapi.json()["paths"]
