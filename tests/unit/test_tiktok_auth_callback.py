"""Route tests for TikTok OAuth callback infrastructure (GET /v1/auth/tiktok/callback)."""

import base64
import hashlib
import hmac
import json
import secrets
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

APP_SECRET = "test_app_secret"
CALLBACK_PATH = "/v1/auth/tiktok/callback"


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
def tiktok_app_secret(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)


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
    async def test_callback_missing_state_returns_400(self, client):
        resp = await client.get(CALLBACK_PATH, params={"code": "abc"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_rejects_invalid_state(self, client):
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code", "state": "tampered.state"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_callback_accepts_valid_params(self, client, user_id):
        state = _build_state(user_id)
        resp = await client.get(
            CALLBACK_PATH,
            params={"code": "auth_code_123", "state": state},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "pending" in body["message"].lower()

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
