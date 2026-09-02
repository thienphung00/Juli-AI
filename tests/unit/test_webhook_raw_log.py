"""TikTok webhook raw audit log: fail-safe recording of every delivery (#392).

Two things are proven here: end to end, every response the webhook app can
return (auth failure, malformed body, catalog match, deferred, unknown) hands
the injected :class:`RawWebhookEventRecorder` a matching ``processing_status``,
and a failure inside the recorder never changes that response; and the
concrete implementation (:class:`DatabaseRawWebhookEventRecorder` over
:class:`WebhookRawEventsRepo`) redacts the body and the header allowlist
before either reaches the table.

HTTP status codes and event routing themselves (auth, malformed JSON, catalog
dispatch) are ``test_webhook.py``'s contract; this module only adds the
recorder-wiring proof on top.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from juli_backend.models.models import WebhookRawEvent
from juli_backend.repositories import WebhookRawEventsRepo
from juli_backend.services.tiktok.webhook_raw_log import DatabaseRawWebhookEventRecorder
from juli_backend.services.webhook.app import create_app

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
WEBHOOK_PATH = "/webhooks/tiktok"


def _sign(body: bytes) -> str:
    """``HMAC-SHA256(app_secret, app_key + body)`` -- the path is not signed."""
    sign_string = f"{APP_KEY}{body.decode()}"
    return hmac.new(APP_SECRET.encode(), sign_string.encode(), hashlib.sha256).hexdigest()


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
    """Stands in for :class:`DatabaseRawWebhookEventRecorder` -- same signature."""

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
        handoff_calls.append({"channel": channel, "shop_key": shop_key, "value": value})

    return create_app(
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        handoff_fn=fake_handoff,
        raw_event_recorder=recorder,
    )


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestEveryOutcomeIsRecorded:
    """Each response the webhook app can return reaches the recorder with a matching status."""

    async def test_missing_signature_records_401(self, client, recorder):
        resp = await client.post(
            WEBHOOK_PATH, content=_order_body(), headers={"Content-Type": "application/json"}
        )

        assert resp.status_code == 401
        assert len(recorder.calls) == 1
        assert recorder.calls[0]["http_status"] == 401
        assert recorder.calls[0]["processing_status"] == "missing_signature"

    async def test_invalid_signature_records_401(self, client, recorder):
        resp = await client.post(
            WEBHOOK_PATH,
            content=_order_body(),
            headers={"Authorization": "bad", "Content-Type": "application/json"},
        )

        assert resp.status_code == 401
        assert recorder.calls[0]["processing_status"] == "invalid_signature"

    async def test_malformed_json_records_400(self, client, recorder):
        body = b"not-json"
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": _sign(body), "Content-Type": "application/json"},
        )

        assert resp.status_code == 400
        assert recorder.calls[0]["processing_status"] == "malformed_json"

    async def test_missing_fields_records_400(self, client, recorder):
        body = json.dumps({"shop_id": "s1", "timestamp": 1, "data": {}}).encode()
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": _sign(body), "Content-Type": "application/json"},
        )

        assert resp.status_code == 400
        assert recorder.calls[0]["processing_status"] == "missing_fields"

    async def test_catalog_match_records_the_handler_name_and_the_parsed_event(
        self, client, recorder
    ):
        body = _order_body()
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": _sign(body), "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert recorder.calls[0]["http_status"] == 200
        assert recorder.calls[0]["processing_status"] == "order_status_change"
        assert recorder.calls[0]["event"] is not None

    async def test_out_of_scope_event_records_deferred_status(self, client, recorder):
        body = json.dumps(
            {"type": "LIVESTREAM_SESSION_END", "shop_id": "shop_ls_1", "timestamp": 1, "data": {}}
        ).encode()
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": _sign(body), "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert recorder.calls[0]["processing_status"] == "deferred_out_of_scope"

    async def test_unrecognized_event_type_records_unknown_status(self, client, recorder):
        body = json.dumps(
            {
                "type": "TOTALLY_UNKNOWN_EVENT_XYZ",
                "shop_id": "shop_u_1",
                "timestamp": 1,
                "data": {},
            }
        ).encode()
        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": _sign(body), "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert recorder.calls[0]["processing_status"] == "unknown_event"


class TestRecorderFailureIsFailSafe:
    async def test_a_raising_recorder_does_not_change_the_response(
        self, handoff_calls, client, recorder
    ):
        """The audit log is best-effort: a broken recorder must never turn a
        successful delivery into an error the vendor retries forever."""
        recorder.raise_on_record = True
        body = _order_body()

        resp = await client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"Authorization": _sign(body), "Content-Type": "application/json"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"code": 0}
        assert len(handoff_calls) == 1


class TestWebhookRawEventsRepo:
    async def test_insert_persists_the_row(self, session):
        row = await WebhookRawEventsRepo(session).insert(
            tiktok_shop_id="shop_1",
            event_type="ORDER_STATUS_CHANGE",
            event_id="evt_1",
            signature_header="sig",
            headers='{"content-type":"application/json"}',
            raw_body='{"type":"ORDER_STATUS_CHANGE"}',
            http_status=200,
            processing_status="order_status_change",
        )

        loaded = (
            await session.execute(select(WebhookRawEvent).where(WebhookRawEvent.id == row.id))
        ).scalar_one()
        assert loaded.tiktok_shop_id == "shop_1"
        assert loaded.event_type == "ORDER_STATUS_CHANGE"
        assert loaded.http_status == 200
        assert loaded.processing_status == "order_status_change"
        assert loaded.parse_version == 1


class TestDatabaseRawWebhookEventRecorder:
    async def test_redacts_the_body_and_the_header_allowlist_and_skips_malformed_bodies(
        self, session
    ):
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

        rows = {
            row.processing_status: row
            for row in (await session.execute(select(WebhookRawEvent))).scalars().all()
        }
        assert set(rows) == {"order_status_change", "malformed_json"}
        ok, bad = rows["order_status_change"], rows["malformed_json"]
        assert ok.raw_body is not None
        assert "Alice" not in ok.raw_body
        assert "[REDACTED]" in ok.raw_body
        assert "content-type" in (ok.headers or "").lower()
        assert "X-Secret" not in (ok.headers or "")
        assert bad.raw_body is None
        assert bad.processing_status == "malformed_json"
