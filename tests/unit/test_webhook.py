"""TDD tests for TikTok webhook receiver endpoint.

Behaviors under test:
- Valid signature → hands event to ingest pipeline → returns {"code": 0}
- Missing Authorization header → returns 401
- Invalid signature → returns 401
- Ingest channel is derived from event type (lowercased)
- shop_id is used as the handoff shop key
- Malformed JSON body → returns 400
"""

import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.services.webhook.app import create_app


APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
WEBHOOK_PATH = "/webhooks/tiktok"


def _sign(app_key: str, app_secret: str, path: str, body: bytes) -> str:
    sign_string = f"{app_key}{path}{body.decode()}"
    return hmac.new(
        app_secret.encode(),
        sign_string.encode(),
        hashlib.sha256,
    ).hexdigest()


@pytest.fixture
def handoff_calls():
    """Accumulator for ingest handoffs — replaces production ETL wiring in tests."""
    return []


@pytest.fixture
def app(handoff_calls):
    async def fake_handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append({"channel": channel, "shop_key": shop_key, "value": value})

    return create_app(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        handoff_fn=fake_handoff,
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _order_event_body() -> bytes:
    return json.dumps({
        "type": "ORDER_STATUS_CHANGE",
        "shop_id": "7000000000000001",
        "timestamp": 1234567890,
        "data": {
            "order_id": "577000000000001",
            "order_status": "AWAITING_SHIPMENT",
            "update_time": 1234567890,
        },
    }).encode()


class TestValidWebhook:
    @pytest.mark.asyncio
    async def test_returns_200_with_code_zero(self, client):
        body = _order_event_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"code": 0}

    @pytest.mark.asyncio
    async def test_publishes_to_kafka_with_correct_topic(self, client, handoff_calls):
        body = _order_event_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert len(handoff_calls) == 1
        assert handoff_calls[0]["channel"] == "tiktok.order_status_change"

    @pytest.mark.asyncio
    async def test_kafka_key_is_shop_id(self, client, handoff_calls):
        body = _order_event_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert handoff_calls[0]["shop_key"] == "7000000000000001"

    @pytest.mark.asyncio
    async def test_kafka_value_is_raw_body(self, client, handoff_calls):
        body = _order_event_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert handoff_calls[0]["value"] == body

    @pytest.mark.asyncio
    async def test_product_event_routes_to_product_topic(self, client, handoff_calls):
        event = {
            "type": "PRODUCT_STATUS_CHANGE",
            "shop_id": "shop_42",
            "timestamp": 9999999999,
            "data": {"product_id": "p1"},
        }
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert handoff_calls[0]["channel"] == "tiktok.product_status_change"


class TestSignatureRejection:
    @pytest.mark.asyncio
    async def test_missing_authorization_returns_401(self, client):
        body = _order_event_body()

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, client):
        body = _order_event_body()

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": "bad_sig", "Content-Type": "application/json"},
        )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_signature_does_not_publish(self, client, handoff_calls):
        body = _order_event_body()

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": "bad_sig", "Content-Type": "application/json"},
        )

        assert len(handoff_calls) == 0


class TestMalformedRequest:
    @pytest.mark.asyncio
    async def test_non_json_body_returns_400(self, client):
        body = b"this is not json"
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_type_field_returns_400(self, client):
        event = {"shop_id": "s1", "timestamp": 123, "data": {}}
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert resp.status_code == 400


class TestNewEventTypeRouting:
    """Issue #27 — new event types routed to category topics."""

    @pytest.mark.asyncio
    async def test_webhook_livestream_event_published(self, client, handoff_calls):
        """AC1: Livestream events published to 'livestream-events' topic."""
        event = {
            "type": "LIVESTREAM_SESSION_END",
            "shop_id": "shop_ls_1",
            "timestamp": 1700000001,
            "data": {"session_id": "sess_001", "duration_seconds": 3600},
        }
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert len(handoff_calls) == 1
        assert handoff_calls[0]["channel"] == "livestream-events"
        assert handoff_calls[0]["shop_key"] == "shop_ls_1"
        assert handoff_calls[0]["value"] == body

    @pytest.mark.asyncio
    async def test_webhook_livestream_start_also_routes_correctly(
        self, client, handoff_calls
    ):
        """AC1: All livestream subtypes route to the same topic."""
        event = {
            "type": "LIVESTREAM_SESSION_START",
            "shop_id": "shop_ls_2",
            "timestamp": 1700000002,
            "data": {"session_id": "sess_002"},
        }
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert handoff_calls[0]["channel"] == "livestream-events"

    @pytest.mark.asyncio
    async def test_webhook_creator_event_published(self, client, handoff_calls):
        """AC2: Creator/affiliate events published to 'creator-events' topic."""
        event = {
            "type": "CREATOR_AFFILIATE_LINK",
            "shop_id": "shop_cr_1",
            "timestamp": 1700000003,
            "data": {"creator_id": "c_001", "link_id": "lk_001"},
        }
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert len(handoff_calls) == 1
        assert handoff_calls[0]["channel"] == "creator-events"
        assert handoff_calls[0]["shop_key"] == "shop_cr_1"

    @pytest.mark.asyncio
    async def test_webhook_affiliate_event_routes_to_creator_topic(
        self, client, handoff_calls
    ):
        """AC2: Affiliate-prefixed events also go to 'creator-events'."""
        event = {
            "type": "AFFILIATE_COMMISSION_CHANGE",
            "shop_id": "shop_af_1",
            "timestamp": 1700000004,
            "data": {"affiliate_id": "a_001", "new_rate": "0.08"},
        }
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert handoff_calls[0]["channel"] == "creator-events"

    @pytest.mark.asyncio
    async def test_webhook_settlement_event_published(self, client, handoff_calls):
        """AC3: Settlement events published to 'settlement-events' topic."""
        event = {
            "type": "SETTLEMENT_COMPLETED",
            "shop_id": "shop_st_1",
            "timestamp": 1700000005,
            "data": {"settlement_id": "stl_001", "amount": "1500000"},
        }
        body = json.dumps(event).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert len(handoff_calls) == 1
        assert handoff_calls[0]["channel"] == "settlement-events"
        assert handoff_calls[0]["shop_key"] == "shop_st_1"

    @pytest.mark.asyncio
    async def test_existing_order_event_still_uses_generic_topic(
        self, client, handoff_calls
    ):
        """Backward compat: unrecognized types fallback to tiktok.{type}."""
        body = _order_event_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)

        await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )

        assert handoff_calls[0]["channel"] == "tiktok.order_status_change"
