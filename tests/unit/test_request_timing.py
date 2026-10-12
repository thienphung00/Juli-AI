"""Fast track P21 — server-side request latency: the http_request event and the report.

The event must name the matched route TEMPLATE, never the raw path: the raw path carries
shop ids, and these logs live on the VPS.
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from juli_backend.api.app import create_app
from juli_backend.api.middleware import (
    HTTP_REQUEST_EVENT,
    CorrelationIdMiddleware,
    RequestTimingMiddleware,
    install_error_boundary,
)
from juli_backend.core.observability import CORRELATION_ID_HEADER, JsonFormatter

_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "latency_report.py"
_spec = importlib.util.spec_from_file_location("latency_report", _SCRIPT)
assert _spec and _spec.loader
latency_report = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("latency_report", latency_report)  # dataclasses resolves it
_spec.loader.exec_module(latency_report)

SHOP_ID = "shop-7f3a9c"
SERVER_TIMING = re.compile(r"^app;dur=\d+\.\d$")


def _build(*, enabled: bool | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/ops/shops/{shop_id}/simulation")
    async def _sim(shop_id: str) -> dict[str, str]:
        return {"shop": shop_id}

    @app.get("/v1/missing/{item_id}")
    async def _missing(item_id: str) -> dict[str, str]:
        raise HTTPException(status_code=404, detail="nope")

    @app.get("/boom")
    async def _boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    @app.get("/stream")
    async def _stream() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"a"
            yield b"b"

        return StreamingResponse(chunks())

    @app.get("/health")
    async def _health() -> dict[str, str]:
        return {"status": "ok"}

    if enabled is None:
        app.add_middleware(RequestTimingMiddleware)
    else:
        app.add_middleware(RequestTimingMiddleware, enabled=enabled)
    app.add_middleware(CorrelationIdMiddleware)
    install_error_boundary(app)
    return app


def _events(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == HTTP_REQUEST_EVENT]


def test_logs_route_template_not_raw_path(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_build())
    # Format at emit time, as production does: the correlation id lives in request context.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    timing_logger = logging.getLogger("juli_backend.api.middleware")
    timing_logger.addHandler(handler)
    try:
        with caplog.at_level(logging.INFO):
            resp = client.get(f"/v1/ops/shops/{SHOP_ID}/simulation?email=a@b.c")
    finally:
        timing_logger.removeHandler(handler)
    assert resp.status_code == 200
    [record] = _events(caplog)
    assert record.__dict__["route"] == "/v1/ops/shops/{shop_id}/simulation"
    assert record.__dict__["method"] == "GET"
    assert record.__dict__["status"] == 200
    duration = record.__dict__["duration_ms"]
    assert isinstance(duration, float) and duration >= 0
    assert round(duration, 1) == duration

    [line] = [x for x in stream.getvalue().splitlines() if "http_request" in x]
    payload = json.loads(line)
    assert SHOP_ID not in line and "a@b.c" not in line and "email" not in line
    assert payload["event"] == "http_request"
    assert payload["correlation_id"] == resp.headers[CORRELATION_ID_HEADER]
    assert set(payload) <= {
        "timestamp",
        "level",
        "logger",
        "event",
        "correlation_id",
        "client_address",
        "route",
        "method",
        "status",
        "duration_ms",
    }


def test_server_timing_header(caplog: pytest.LogCaptureFixture) -> None:
    resp = TestClient(_build()).get(f"/v1/ops/shops/{SHOP_ID}/simulation")
    assert SERVER_TIMING.match(resp.headers["server-timing"])


def test_4xx_logged_with_status(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_build())
    with caplog.at_level(logging.INFO):
        assert client.get("/v1/missing/123").status_code == 404
        assert client.get("/no/such/route/42").status_code == 404
        assert client.post(f"/v1/ops/shops/{SHOP_ID}/simulation").status_code == 405
    got = [(r.__dict__["route"], r.__dict__["status"]) for r in _events(caplog)]
    assert got == [
        ("/v1/missing/{item_id}", 404),
        ("unmatched", 404),
        ("/v1/ops/shops/{shop_id}/simulation", 405),
    ]


def test_exception_logs_500_and_reraises(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_build(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO):
        resp = client.get("/boom")
    assert resp.status_code == 500
    [record] = _events(caplog)
    assert (record.__dict__["route"], record.__dict__["status"]) == ("/boom", 500)
    # Re-raised, so the error boundary still ran and logged the exception.
    assert any(r.getMessage() == "unhandled_exception" for r in caplog.records)


def test_exception_propagates_through_middleware(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_build(), raise_server_exceptions=True)
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError, match="kaboom"):
        client.get("/boom")
    assert [r.__dict__["status"] for r in _events(caplog)] == [500]


def test_streaming_response_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_build())
    with caplog.at_level(logging.INFO):
        resp = client.get("/stream")
    assert resp.content == b"ab"
    assert [r.__dict__["route"] for r in _events(caplog)] == ["/stream"]


def test_health_not_timed(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_build())
    with caplog.at_level(logging.INFO):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert _events(caplog) == []
    assert "server-timing" not in resp.headers


@pytest.mark.parametrize("value", ["0", " 0 "])
def test_env_disables(
    value: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("HTTP_TIMING_LOG", value)
    client = TestClient(_build())
    with caplog.at_level(logging.INFO):
        resp = client.get(f"/v1/ops/shops/{SHOP_ID}/simulation")
    assert _events(caplog) == []
    assert "server-timing" not in resp.headers


def test_env_default_on(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("HTTP_TIMING_LOG", raising=False)
    client = TestClient(_build())
    with caplog.at_level(logging.INFO):
        client.get(f"/v1/ops/shops/{SHOP_ID}/simulation")
    assert len(_events(caplog)) == 1


def test_create_app_registers_timing_inside_correlation() -> None:
    classes: list[object] = [m.cls for m in create_app().user_middleware]
    assert classes.count(RequestTimingMiddleware) == 1
    # user_middleware is outermost-first.
    assert classes.index(CorrelationIdMiddleware) < classes.index(RequestTimingMiddleware)


# ------------------------------------------------------------------ latency report


def _line(route: str, ms: float, method: str = "GET") -> str:
    return json.dumps(
        {
            "event": "http_request",
            "route": route,
            "method": method,
            "status": 200,
            "duration_ms": ms,
        }
    )


def test_report_percentiles_on_synthetic_input() -> None:
    lines = [_line("/v1/ops/shops", float(ms)) for ms in range(1, 101)]
    lines += [_line("/v1/ops/staff", 500.0), _line("/v1/shops", 9000.0)]
    lines += ["uvicorn starting", "{not json", json.dumps({"event": "other", "duration_ms": 1})]
    groups = latency_report.collect(lines)
    rows = latency_report.summarise(groups, prefix="/v1/ops")
    assert [r.__dict__["route"] for r in rows] == ["/v1/ops/staff", "/v1/ops/shops"]
    shops = rows[1]
    assert (shops.count, shops.p50, shops.p90, shops.p95, shops.p99, shops.max) == (
        100,
        50.0,
        90.0,
        95.0,
        99.0,
        100.0,
    )
    assert [r.__dict__["route"] for r in latency_report.summarise(groups, min_count=2)] == [
        "/v1/ops/shops"
    ]


def test_report_cli_prints_table() -> None:
    stdin = io.StringIO("\n".join([_line("/v1/ops/x", 10.0), _line("/v1/other", 1.0), "junk"]))
    out = io.StringIO()
    assert latency_report.main(["--prefix", "/v1/ops"], stdin=stdin, stdout=out) == 0
    text = out.getvalue()
    assert "GET /v1/ops/x" in text and "/v1/other" not in text
    assert "p95" in text


def test_report_empty_input() -> None:
    out = io.StringIO()
    latency_report.main([], stdin=io.StringIO(""), stdout=out)
    assert "No http_request events" in out.getvalue()
