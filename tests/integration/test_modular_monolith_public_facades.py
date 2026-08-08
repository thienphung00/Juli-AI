"""Modular monolith integration example — public facades only (MMU-14 / #564).

Demonstrates module collaboration through package-root public APIs:

- ``juli_backend.integrations.tiktok`` — Partner app identity (``TikTokAuth``)
- ``juli_backend.services.webhook`` — inbound webhook ASGI app (``create_app``)

Integration tests must import facades only; leaf modules such as
``integrations.tiktok.auth`` or ``services.webhook.app`` are forbidden here.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.integrations.tiktok import TikTokAuth
from juli_backend.services.webhook import WEBHOOK_PATH, create_app

APP_KEY = "mmu14_integration_app_key"
APP_SECRET = "mmu14_integration_app_secret"


def _sign_webhook(app_key: str, app_secret: str, body: bytes) -> str:
    """Compute HMAC-SHA256 signature for webhook: HMAC-SHA256(app_secret, app_key + body).

    The path is NOT included in webhook signatures (unlike API request signing).
    """
    sign_string = f"{app_key}{body.decode()}"
    return hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()


def _order_event_body() -> bytes:
    return json.dumps(
        {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": "7000000000005641",
            "timestamp": 1_700_000_564,
            "data": {
                "order_id": "577000000000564",
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1_700_000_564,
            },
        }
    ).encode()


@pytest.fixture
def handoff_calls() -> list[dict[str, object]]:
    return []


@pytest.fixture
def partner_auth() -> TikTokAuth:
    """Integration facade — Partner credentials without leaf imports."""
    return TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET)


@pytest.fixture
def webhook_app(handoff_calls: list[dict[str, object]]):
    async def fake_handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append({"channel": channel, "shop_key": shop_key, "value": value})

    return create_app(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        handoff_fn=fake_handoff,
    )


@pytest_asyncio.fixture
async def webhook_client(webhook_app):
    transport = ASGITransport(app=webhook_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_integration_example_uses_public_facades_only(
    partner_auth: TikTokAuth,
    webhook_client: AsyncClient,
    handoff_calls: list[dict[str, object]],
) -> None:
    """Two modules collaborate exclusively via published package roots (webhook path)."""
    assert APP_KEY in partner_auth.generate_auth_url(
        "https://example.com/oauth/callback",
        "mmu14-webhook",
    )
    body = _order_event_body()
    signature = _sign_webhook(APP_KEY, APP_SECRET, body)

    response = await webhook_client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"Authorization": signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}
    assert len(handoff_calls) == 1
    assert handoff_calls[0]["shop_key"] == "7000000000005641"
    assert handoff_calls[0]["channel"] == "tiktok.order_status_change"


def test_tiktok_auth_facade_builds_oauth_url(partner_auth: TikTokAuth) -> None:
    """Two modules collaborate exclusively via published package roots (OAuth path)."""
    url = partner_auth.generate_auth_url(
        redirect_uri="https://example.com/oauth/callback",
        state="mmu14-state",
    )
    assert APP_KEY in url
    assert "redirect_uri=" in url
    assert "state=mmu14-state" in url
