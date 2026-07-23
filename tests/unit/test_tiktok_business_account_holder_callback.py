"""Route tests for TikTok Business account-holder OAuth callback."""

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
from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.models import TikTokCredential

APP_ID = "test_business_app_id"
APP_SECRET = "test_business_app_secret"
CALLBACK_PATH = "/v1/auth/tiktok/business/account-holder/callback"
ACCOUNT_HOLDER_CAPABILITY = "business_account_holder"
ADVERTISER_CAPABILITY = "business_advertiser"

TOKEN_FIXTURE = {
    "access_token": "ROW_secret_access",
    "refresh_token": "ROW_secret_refresh",
    "expires_in": 86400,
    "creator_id": "creator_123",
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
def business_account_holder_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_BUSINESS_APP_ID", APP_ID)
    monkeypatch.setenv("TIKTOK_BUSINESS_APP_SECRET", APP_SECRET)
    monkeypatch.setenv(
        "TIKTOK_BUSINESS_ACCOUNT_HOLDER_REDIRECT_URI",
        "https://api.app-juli.com/v1/auth/tiktok/business/account-holder/callback",
    )


@pytest.fixture(autouse=True)
def mock_token_exchange(monkeypatch):
    mock = MagicMock(return_value=dict(TOKEN_FIXTURE))
    monkeypatch.setattr(
        "juli_backend.integrations.tiktok.business_account_holder_auth."
        "TikTokBusinessAccountHolderAuth.exchange_auth_code",
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


class TestBusinessAccountHolderCallbackRoute:
    @pytest.mark.asyncio
    async def test_callback_missing_params_returns_400(self, client):
        resp = await client.get(CALLBACK_PATH)
        assert resp.status_code == 400
        assert "auth_code" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_missing_state_returns_400(self, client):
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "ROW_test_auth_code"},
        )
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_callback_rejects_invalid_state(self, client, mock_token_exchange):
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "auth_code", "state": "tampered.state"},
        )
        assert resp.status_code == 401
        mock_token_exchange.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_exchanges_code_and_persists_account_holder_credential(
        self, client, session, user_id, mock_token_exchange
    ):
        state = _build_state(user_id)
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "auth_code_123", "state": state},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "completed" in body["message"].lower()
        assert body["subject_id_present"] is True
        assert body["access_token_expires_in"] == 86400
        mock_token_exchange.assert_called_once_with("auth_code_123")

        raw = resp.text
        assert TOKEN_FIXTURE["access_token"] not in raw
        assert TOKEN_FIXTURE["refresh_token"] not in raw

        stored = await session.execute(
            select(
                TikTokCredential.access_token,
                TikTokCredential.refresh_token,
                TikTokCredential.capability,
                TikTokCredential.merchant_authorization_id,
            ).where(TikTokCredential.capability == ACCOUNT_HOLDER_CAPABILITY)
        )
        rows = stored.all()
        assert len(rows) == 1
        stored_access_token, stored_refresh_token, capability, merchant_id = rows[0]
        assert capability == ACCOUNT_HOLDER_CAPABILITY
        assert merchant_id == TOKEN_FIXTURE["creator_id"]
        assert stored_access_token != TOKEN_FIXTURE["access_token"]
        assert stored_refresh_token != TOKEN_FIXTURE["refresh_token"]

    @pytest.mark.asyncio
    async def test_callback_does_not_overwrite_shop_or_advertiser_credentials(
        self, client, session, user_id, mock_token_exchange
    ):
        from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo
        from juli_backend.services.tiktok.token_expiry import access_token_expires_at

        shops_repo = ShopsRepo(session)
        shop = await shops_repo.create(user_id, "Existing Shop", "seller_open_999")
        cred_repo = TikTokCredentialRepo(session)
        expires_at = access_token_expires_at(604800)
        await cred_repo.create(
            shop_id=shop.id,
            access_token="shop_access_plain",
            refresh_token="shop_refresh_plain",
            token_expires_at=expires_at,
            merchant_authorization_id="seller_open_999",
            capability=TikTokCapability.SELLER_CONNECT.value,
        )
        await cred_repo.create(
            shop_id=shop.id,
            access_token="advertiser_access_plain",
            refresh_token="advertiser_refresh_plain",
            token_expires_at=expires_at,
            merchant_authorization_id="adv_555",
            capability=ADVERTISER_CAPABILITY,
        )
        await session.commit()

        state = _build_state(user_id)
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "auth_code_123", "state": state},
        )
        assert resp.status_code == 200

        shop_cred = await session.execute(
            select(TikTokCredential.capability, TikTokCredential.access_token).where(
                TikTokCredential.capability == TikTokCapability.SELLER_CONNECT.value
            )
        )
        shop_capability, shop_access = shop_cred.one()
        assert shop_capability == TikTokCapability.SELLER_CONNECT.value
        assert shop_access != "shop_access_plain"

        adv_cred = await session.execute(
            select(TikTokCredential.capability, TikTokCredential.access_token).where(
                TikTokCredential.capability == ADVERTISER_CAPABILITY
            )
        )
        adv_capability, adv_access = adv_cred.one()
        assert adv_capability == ADVERTISER_CAPABILITY
        assert adv_access != "advertiser_access_plain"

        holder_count = await session.execute(
            select(TikTokCredential.id).where(
                TikTokCredential.capability == ACCOUNT_HOLDER_CAPABILITY
            )
        )
        assert len(holder_count.all()) == 1

    @pytest.mark.asyncio
    async def test_callback_secrets_never_logged_in_response(
        self, client, user_id, mock_token_exchange
    ):
        state = _build_state(user_id)
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "auth_code_123", "state": state},
        )
        assert resp.status_code == 200
        raw = resp.text
        assert TOKEN_FIXTURE["access_token"] not in raw
        assert TOKEN_FIXTURE["refresh_token"] not in raw
        assert "auth_code_123" not in raw

    @pytest.mark.asyncio
    async def test_callback_token_exchange_failure_returns_502(
        self, client, mock_token_exchange
    ):
        mock_token_exchange.side_effect = AuthenticationError(
            code=40002, message="Invalid auth code"
        )
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "bad_code", "state": _build_state(uuid.uuid4())},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"] == "TikTok token exchange failed"
        assert TOKEN_FIXTURE["access_token"] not in resp.text

    @pytest.mark.asyncio
    async def test_callback_missing_app_id_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("TIKTOK_BUSINESS_APP_ID", raising=False)
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "auth_code", "state": _build_state(uuid.uuid4())},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "TikTok Business OAuth is not configured"

    @pytest.mark.asyncio
    async def test_callback_missing_app_secret_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("TIKTOK_BUSINESS_APP_SECRET", raising=False)
        resp = await client.get(
            CALLBACK_PATH,
            params={"auth_code": "auth_code", "state": _build_state(uuid.uuid4())},
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
