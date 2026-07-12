"""Contract tests for TikTok OAuth/webhook infrastructure (issue #259 acceptance mapping)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload

APP_SECRET = "test_app_secret"
APP_KEY = "test_app_key"
CALLBACK_PATH = "/v1/auth/tiktok/callback"

pytestmark = pytest.mark.asyncio


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
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)


@pytest.fixture(autouse=True)
def mock_token_exchange(monkeypatch):
    from unittest.mock import MagicMock

    mock = MagicMock(
        return_value={
            "access_token": "secret",
            "refresh_token": "secret",
            "access_token_expire_in": 604800,
            "open_id": "seller_1",
        }
    )
    monkeypatch.setattr(
        "juli_backend.integrations.tiktok.auth.TikTokAuth.exchange_code",
        mock,
    )
    return mock


@pytest_asyncio.fixture
async def api_client(engine, monkeypatch):
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
    ) as client:
        yield client


async def test_oauth_callback_endpoint_exists_and_is_reachable(api_client):
    openapi = await api_client.get("/openapi.json")
    assert openapi.status_code == 200
    assert CALLBACK_PATH in openapi.json()["paths"]


async def test_oauth_callback_validates_required_parameters(api_client):
    resp = await api_client.get(CALLBACK_PATH)
    assert resp.status_code == 400
    assert "code" in resp.json()["detail"].lower()


async def test_webhook_accepts_json_payload_with_valid_signature():
    import json as json_mod

    from juli_backend.services.tiktok.signature import TikTokWebhookSignatureVerifier
    from juli_backend.services.tiktok.webhook import TikTokWebhookService
    from juli_backend.services.tiktok import TikTokWebhookDispatcher

    app_key = "key"
    app_secret = "secret"
    path = "/webhooks/tiktok"
    body = json_mod.dumps({"type": "ORDER_CREATED", "shop_id": "s1"}).encode()
    sign_string = f"{app_key}{path}{body.decode()}"
    sig = hmac.new(
        app_secret.encode(), sign_string.encode(), hashlib.sha256
    ).hexdigest()
    handoffs: list[tuple[str, str, bytes]] = []

    async def handoff(channel: str, shop_key: str, payload: bytes) -> None:
        handoffs.append((channel, shop_key, payload))

    service = TikTokWebhookService(
        verifier=TikTokWebhookSignatureVerifier(
            app_key=app_key, app_secret=app_secret, path=path
        ),
        dispatcher=TikTokWebhookDispatcher(),
        handoff_fn=handoff,
    )
    result = await service.handle(body=body, signature=sig)
    assert result.status_code == 200
    assert result.body == {"code": 0}
    assert len(handoffs) == 1


async def test_webhook_dispatcher_routes_order_status_change_event():
    dispatcher = TikTokWebhookDispatcher()
    event = TikTokWebhookPayload(type="ORDER_STATUS_CHANGE", shop_id="shop_1")
    handler_name = await dispatcher.dispatch(event)
    assert handler_name == "order_status_change"


async def test_oauth_callback_returns_proper_http_responses(api_client, user_id):
    state = _build_state(user_id)
    bad = await api_client.get(
        CALLBACK_PATH, params={"code": "c", "state": "bad.state"}
    )
    assert bad.status_code == 401

    ok = await api_client.get(
        CALLBACK_PATH, params={"code": "auth_code", "state": state}
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "ok"
