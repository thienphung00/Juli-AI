"""TikTok Sandbox webhook signature integration tests — Issue #366.

Uses real Partner Center app_key/app_secret to sign payloads and exercise the
webhook FastAPI app end-to-end (no HTTP mocks).
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.services.webhook.app import WEBHOOK_PATH, create_app

from tests.integration.tiktok_sandbox import (
    requires_sandbox_credentials,
    sandbox_app_key,
    sandbox_app_secret,
    sign_webhook_body,
)


def _order_event_body() -> bytes:
    return json.dumps(
        {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": "7658096633384781588",
            "timestamp": 1_700_000_000,
            "data": {
                "order_id": "577000000000366",
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1_700_000_000,
            },
        }
    ).encode()


@pytest.fixture
def handoff_calls():
    return []


@pytest.fixture
def webhook_app(handoff_calls):
    async def fake_handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append(
            {"channel": channel, "shop_key": shop_key, "value": value}
        )

    return create_app(
        app_key=sandbox_app_key(),
        app_secret=sandbox_app_secret(),
        handoff_fn=fake_handoff,
    )


@pytest_asyncio.fixture
async def webhook_client(webhook_app):
    transport = ASGITransport(app=webhook_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@requires_sandbox_credentials
class TestSandboxWebhookSignature:
    @pytest.mark.asyncio
    async def test_valid_sandbox_signature_accepted(self, webhook_client, handoff_calls):
        body = _order_event_body()
        signature = sign_webhook_body(sandbox_app_key(), sandbox_app_secret(), body)

        response = await webhook_client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": signature, "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {"code": 0}
        assert len(handoff_calls) == 1
        assert handoff_calls[0]["shop_key"] == "7658096633384781588"

    @pytest.mark.asyncio
    async def test_invalid_sandbox_signature_rejected(self, webhook_client, handoff_calls):
        body = _order_event_body()

        response = await webhook_client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": "invalid_signature_366", "Content-Type": "application/json"},
        )

        assert response.status_code == 401
        assert response.json() == {"error": "Invalid signature"}
        assert handoff_calls == []

    @pytest.mark.asyncio
    async def test_missing_authorization_rejected(self, webhook_client, handoff_calls):
        body = _order_event_body()

        response = await webhook_client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401
        assert response.json() == {"error": "Missing signature"}
        assert handoff_calls == []
