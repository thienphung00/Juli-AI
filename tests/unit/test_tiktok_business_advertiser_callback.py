"""Route tests for TikTok Business Advertiser OAuth callback."""

from __future__ import annotations

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
from sqlalchemy import select

from juli_backend.integrations.tiktok.exceptions import AuthenticationError
from juli_backend.models.models import TikTokCredential

APP_ID = "test_business_app_id"
APP_SECRET = "test_business_app_secret"
CALLBACK_PATH = "/v1/auth/tiktok/business/callback"
BUSINESS_ADVERTISER_CAPABILITY = "business_advertiser"

TOKEN_FIXTURE = {
    "access_token": "ROW_secret_access",
    "refresh_token": "ROW_secret_refresh",
    "advertiser_ids": ["7123456789012345"],
    "scope": [1, 2, 3],
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
def business_advertiser_oauth_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_BUSINESS_APP_ID", APP_ID)
    monkeypatch.setenv("TIKTOK_BUSINESS_APP_SECRET", APP_SECRET)
    monkeypatch.setenv(
        "TIKTOK_BUSINESS_REDIRECT_URI",
        "https://api.app-juli.com/v1/auth/tiktok/business/callback",
    )


@pytest.fixture(autouse=True)
def mock_token_exchange(monkeypatch):
    mock = MagicMock(return_value=dict(TOKEN_FIXTURE))
    monkeypatch.setattr(
        "juli_backend.integrations.tiktok.business_advertiser_auth."
        "TikTokBusinessAdvertiserAuth.exchange_code",
        mock,
    )
    return mock


@pytest_asyncio.fixture
async def client(engine, monkeypatch):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session
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


class TestBusinessAdvertiserOAuthCallbackRoute:
    @pytest.mark.asyncio
    async def test_callback_missing_code_returns_400(self, client):
        resp = await client.get(CALLBACK_PATH)
        assert resp.status_code == 400
        assert "code" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_missing_state_returns_400(self, client):
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "ROW_test_auth_code"},
        )
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_rejects_invalid_state(self, client, mock_token_exchange):
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code", "state": "tampered.state"},
        )
        assert resp.status_code == 401
        mock_token_exchange.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_exchanges_code_and_persists_encrypted_credentials(
        self, client, session, user_id, mock_token_exchange
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
        assert body["advertiser_id_present"] is True
        mock_token_exchange.assert_called_once_with("auth_code_123")

        raw = resp.text
        assert TOKEN_FIXTURE["access_token"] not in raw
        assert TOKEN_FIXTURE["refresh_token"] not in raw

        stored = await session.execute(
            select(
                TikTokCredential.access_token,
                TikTokCredential.refresh_token,
                TikTokCredential.merchant_authorization_id,
                TikTokCredential.capability,
            )
        )
        (
            stored_access_token,
            stored_refresh_token,
            merchant_authorization_id,
            capability,
        ) = stored.one()
        assert stored_access_token != TOKEN_FIXTURE["access_token"]
        assert stored_refresh_token != TOKEN_FIXTURE["refresh_token"]
        assert merchant_authorization_id == TOKEN_FIXTURE["advertiser_ids"][0]
        assert capability == BUSINESS_ADVERTISER_CAPABILITY

    @pytest.mark.asyncio
    async def test_callback_token_exchange_failure_returns_502(
        self, client, user_id, mock_token_exchange
    ):
        mock_token_exchange.side_effect = AuthenticationError(
            code=40002, message="Invalid auth code"
        )
        state = _build_state(user_id)
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "bad_code", "state": state},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "TikTok token exchange failed"
        assert TOKEN_FIXTURE["access_token"] not in resp.text

    @pytest.mark.asyncio
    async def test_callback_missing_app_id_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("TIKTOK_BUSINESS_APP_ID", raising=False)
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code", "state": "ignored"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "TikTok Business OAuth is not configured"

    @pytest.mark.asyncio
    async def test_callback_missing_app_secret_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("TIKTOK_BUSINESS_APP_SECRET", raising=False)
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code", "state": "ignored"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "TikTok Business OAuth is not configured"

    @pytest.mark.asyncio
    async def test_callback_does_not_require_jwt(self, client):
        resp = await client.get(CALLBACK_PATH)
        assert resp.status_code != 401 or "authorization" not in resp.json().get(
            "detail", ""
        ).lower()

    @pytest.mark.asyncio
    async def test_callback_route_is_listed_in_openapi(self, client):
        openapi = await client.get("/openapi.json")
        assert openapi.status_code == 200
        assert CALLBACK_PATH in openapi.json()["paths"]
