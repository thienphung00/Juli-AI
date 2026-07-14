"""Unit tests for TikTok webhook raw audit log (#392)."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from juli_backend.models.models import WebhookRawEvent
from juli_backend.repositories.repos import WebhookRawEventsRepo
from juli_backend.services.tiktok.webhook_raw_log import DatabaseRawWebhookEventRecorder
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


def _order_body() -> bytes:
    return json.dumps(
        {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": "7000000000000001",
            "timestamp": 1234567890,
            "data": {
                "order_id": "577000000000001",
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1234567890,
            },
        }
    ).encode()


@dataclass
class CapturingRecorder:
    calls: list[dict] = field(default_factory=list)
    raise_on_record: bool = False

    async def record(
        self,
        *,
        body: bytes,
        signature: str | None,
        http_status: int,
        processing_status: str,
        event,
        headers=None,
    ) -> None:
        if self.raise_on_record:
            raise RuntimeError("recorder boom")
        self.calls.append(
            {
                "body": body,
                "signature": signature,
                "http_status": http_status,
                "processing_status": processing_status,
                "event": event,
                "headers": dict(headers) if headers else None,
            }
        )


@pytest.fixture
def handoff_calls():
    return []


@pytest.fixture
def recorder():
    return CapturingRecorder()


@pytest.fixture
def app(handoff_calls, recorder):
    async def fake_handoff(channel: str, shop_key: str, value: bytes) -> None:
        handoff_calls.append(
            {"channel": channel, "shop_key": shop_key, "value": value}
        )

    return create_app(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        handoff_fn=fake_handoff,
        raw_event_recorder=recorder,
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRawLogRecording:
    @pytest.mark.asyncio
    async def test_missing_signature_records_401(self, client, recorder):
        body = _order_body()
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert len(recorder.calls) == 1
        assert recorder.calls[0]["http_status"] == 401
        assert recorder.calls[0]["processing_status"] == "missing_signature"

    @pytest.mark.asyncio
    async def test_invalid_signature_records_401(self, client, recorder):
        body = _order_body()
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": "bad", "Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert recorder.calls[0]["processing_status"] == "invalid_signature"

    @pytest.mark.asyncio
    async def test_malformed_json_records_400(self, client, recorder):
        body = b"not-json"
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert recorder.calls[0]["processing_status"] == "malformed_json"

    @pytest.mark.asyncio
    async def test_missing_fields_records_400(self, client, recorder):
        body = json.dumps({"shop_id": "s1", "timestamp": 1, "data": {}}).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert recorder.calls[0]["processing_status"] == "missing_fields"

    @pytest.mark.asyncio
    async def test_catalog_match_records_handler_name(self, client, recorder):
        body = _order_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert recorder.calls[0]["http_status"] == 200
        assert recorder.calls[0]["processing_status"] == "order_status_change"
        assert recorder.calls[0]["event"] is not None

    @pytest.mark.asyncio
    async def test_deferred_records_deferred_status(self, client, recorder):
        body = json.dumps(
            {
                "type": "LIVESTREAM_SESSION_END",
                "shop_id": "shop_ls_1",
                "timestamp": 1,
                "data": {},
            }
        ).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert recorder.calls[0]["processing_status"] == "deferred_out_of_scope"

    @pytest.mark.asyncio
    async def test_unknown_records_unknown_status(self, client, recorder):
        body = json.dumps(
            {
                "type": "TOTALLY_UNKNOWN_EVENT_XYZ",
                "shop_id": "shop_u_1",
                "timestamp": 1,
                "data": {},
            }
        ).encode()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert recorder.calls[0]["processing_status"] == "unknown_event"

    @pytest.mark.asyncio
    async def test_recorder_failure_does_not_change_response(
        self, handoff_calls, client, recorder
    ):
        recorder.raise_on_record = True
        body = _order_body()
        sig = _sign(APP_KEY, APP_SECRET, WEBHOOK_PATH, body)
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"code": 0}
        assert len(handoff_calls) == 1


class TestWebhookRawEventsRepo:
    @pytest.mark.asyncio
    async def test_insert_persists_row(self, session):
        repo = WebhookRawEventsRepo(session)
        row = await repo.insert(
            tiktok_shop_id="shop_1",
            event_type="ORDER_STATUS_CHANGE",
            event_id="evt_1",
            signature_header="sig",
            headers='{"content-type":"application/json"}',
            raw_body='{"type":"ORDER_STATUS_CHANGE"}',
            http_status=200,
            processing_status="order_status_change",
        )
        await session.commit()

        result = await session.execute(
            select(WebhookRawEvent).where(WebhookRawEvent.id == row.id)
        )
        loaded = result.scalar_one()
        assert loaded.tiktok_shop_id == "shop_1"
        assert loaded.event_type == "ORDER_STATUS_CHANGE"
        assert loaded.http_status == 200
        assert loaded.processing_status == "order_status_change"
        assert loaded.parse_version == 1


class TestDatabaseRawWebhookEventRecorder:
    @pytest.mark.asyncio
    async def test_records_redacted_body_and_skips_malformed(self, session):
        recorder = DatabaseRawWebhookEventRecorder(session)

        good = json.dumps(
            {
                "type": "ORDER_STATUS_CHANGE",
                "shop_id": "s1",
                "timestamp": 1,
                "data": {"buyer_name": "Alice", "order_id": "o1"},
            }
        ).encode()
        await recorder.record(
            body=good,
            signature="sig",
            http_status=200,
            processing_status="order_status_change",
            event=None,
            headers={"Content-Type": "application/json", "X-Secret": "nope"},
        )

        await recorder.record(
            body=b"not-json",
            signature="sig",
            http_status=400,
            processing_status="malformed_json",
            event=None,
            headers=None,
        )
        await session.commit()

        result = await session.execute(select(WebhookRawEvent))
        rows = {row.processing_status: row for row in result.scalars().all()}
        assert set(rows) == {"order_status_change", "malformed_json"}
        ok = rows["order_status_change"]
        bad = rows["malformed_json"]
        assert ok.raw_body is not None
        assert "Alice" not in ok.raw_body
        assert "[REDACTED]" in ok.raw_body
        assert ok.headers is not None
        assert "content-type" in ok.headers.lower()
        assert "X-Secret" not in (ok.headers or "")
        assert bad.raw_body is None
        assert bad.processing_status == "malformed_json"
