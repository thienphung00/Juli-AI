"""Exit gate for #902 — structured logging, correlation, and a safe error body.

Before this, the application had no logging configuration at all. The root logger had no
handler, so Python's last-resort handler took over: WARNING-and-above only, message-only
format. Every ``logger.info`` audit call site was computed and discarded, every
``extra={...}`` payload on the warnings that did print was built and thrown away, nothing
carried a correlation id, and an unhandled exception returned whatever it happened to say.

These tests pin all four halves of the fix. The most important one is
``test_unhandled_exception_leaks_nothing``: the asymmetry between what the client sees
and what the log keeps is the entire security property, and it is easy to regress by
"helpfully" adding the exception text back into the response.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from juli_backend.api.middleware import (
    GENERIC_ERROR_DETAIL,
    CorrelationIdMiddleware,
    install_error_boundary,
)
from juli_backend.core.observability import (
    CORRELATION_ID_HEADER,
    JsonFormatter,
    coerce_correlation_id,
    configure_logging,
    get_correlation_id,
)

SECRET_MARKER = "SECRET_INTERNAL_DETAIL_ThatMustNeverReachAClient"


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()

    @application.get("/ok")
    async def _ok() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/boom")
    async def _boom() -> dict[str, str]:
        raise RuntimeError(f"{SECRET_MARKER} at /internal/path/secrets.py:42")

    @application.get("/emit")
    async def _emit() -> dict[str, str]:
        logging.getLogger("juli_backend.test_emitter").info(
            "audit_event", extra={"shop_id": "shop-123", "action": "approved"}
        )
        return {"status": "ok"}

    application.add_middleware(CorrelationIdMiddleware)
    install_error_boundary(application)
    return application


# ------------------------------------------------------------------ correlation id


def test_correlation_id_on_a_successful_response(app):
    resp = TestClient(app).get("/ok")
    assert resp.status_code == 200
    assert uuid.UUID(resp.headers[CORRELATION_ID_HEADER])
    # Body must be byte-compatible with the pre-#902 response — header only.
    assert resp.json() == {"status": "ok"}


def test_correlation_id_on_an_error_response(app):
    resp = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert resp.status_code == 500
    assert uuid.UUID(resp.headers[CORRELATION_ID_HEADER])
    assert uuid.UUID(resp.json()["request_id"])


def test_inbound_correlation_id_is_honoured(app):
    supplied = str(uuid.uuid4())
    resp = TestClient(app).get("/ok", headers={CORRELATION_ID_HEADER: supplied})
    assert resp.headers[CORRELATION_ID_HEADER] == supplied


def test_malformed_inbound_correlation_id_is_replaced_not_echoed(app):
    """An inbound header is attacker-supplied and lands in every log line.

    Echoing arbitrary text would let a caller inject newlines into the log stream or
    forge another request's id into the audit trail, so anything not a UUID is discarded.
    """
    hostile = "not-a-uuid\nlevel=INFO event=forged_admin_login"
    resp = TestClient(app).get("/ok", headers={CORRELATION_ID_HEADER: hostile})
    returned = resp.headers[CORRELATION_ID_HEADER]
    assert returned != hostile
    assert "\n" not in returned
    assert uuid.UUID(returned)


@pytest.mark.parametrize("raw", ["", "   ", "abc", "12345", "not-a-uuid", None, "../../etc/passwd"])
def test_coerce_correlation_id_always_returns_a_uuid(raw):
    assert uuid.UUID(coerce_correlation_id(raw))


# ------------------------------------------------------------------ error boundary


def test_unhandled_exception_leaks_nothing(app):
    """The client gets a generic body and an id. Nothing else. This is the point."""
    resp = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert resp.status_code == 500
    assert resp.json()["detail"] == GENERIC_ERROR_DETAIL
    body = resp.text
    assert SECRET_MARKER not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body
    assert "/internal/path" not in body
    assert ".py" not in body
    # The response carries exactly the generic detail plus the id — nothing more.
    assert set(resp.json()) == {"detail", "request_id"}


def test_unhandled_exception_is_still_logged_with_the_id_and_traceback(app, caplog):
    """The asymmetry: withheld from the client, kept for the operator."""
    with caplog.at_level(logging.ERROR):
        resp = TestClient(app, raise_server_exceptions=False).get("/boom")

    record = next(r for r in caplog.records if r.message == "unhandled_exception")
    assert record.correlation_id == resp.json()["request_id"]
    assert record.exc_info is not None
    assert SECRET_MARKER in JsonFormatter().format(record)


# ------------------------------------------------------------------ log emission


def test_info_records_reach_the_handler_with_context_intact(app, caplog):
    """Previously info-level records were discarded before they were written."""
    with caplog.at_level(logging.INFO):
        TestClient(app).get("/emit")

    record = next(r for r in caplog.records if r.message == "audit_event")
    assert record.shop_id == "shop-123"
    assert record.action == "approved"


def test_json_formatter_preserves_extra_context_and_correlation(app):
    configure_logging(force=True)
    record = logging.LogRecord(
        name="juli_backend.thing",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="audit_event",
        args=(),
        exc_info=None,
    )
    record.shop_id = "shop-abc"
    record.correlation_id = "11111111-2222-3333-4444-555555555555"

    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "audit_event"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "juli_backend.thing"
    assert payload["shop_id"] == "shop-abc"
    assert payload["correlation_id"] == "11111111-2222-3333-4444-555555555555"
    # Standard LogRecord noise must not bloat every line.
    assert "msecs" not in payload
    assert "relativeCreated" not in payload


def test_configure_logging_is_idempotent():
    """uvicorn --reload, Celery and the test suite all import the app repeatedly."""
    configure_logging(force=True)
    before = len(logging.getLogger().handlers)
    configure_logging()
    configure_logging()
    assert len(logging.getLogger().handlers) == before


def test_correlation_context_does_not_leak_between_requests(app):
    client = TestClient(app)
    first = client.get("/ok").headers[CORRELATION_ID_HEADER]
    second = client.get("/ok").headers[CORRELATION_ID_HEADER]
    assert first != second
    # And nothing is left bound once the request is done.
    assert get_correlation_id() is None
