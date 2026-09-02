"""HTTP-level tests for the agent-run transport routes -- ADR-074 decisions 3
and 5, #1128 / AGT-W3B: the SSE wire format and cancel idempotency.

``event_stream``'s internal mechanics (subscribe-before-replay, dedupe,
heartbeat, poll fallback, terminal close) are proven directly against the
generator in ``test_agent_run_event_stream.py``; this file proves the FastAPI
route wraps it correctly. The confirmation-decision endpoint's own
authorization ladder has its own dedicated suites,
``test_agent_run_confirmations.py`` (the ladder, no HTTP) and
``test_agent_confirmation_decision_route.py`` (the HTTP mapping); the one
thing about confirmations proven here is that it shares the identical
``_resolve_owned_run`` tenant-scoping guard as ``/events`` and ``/cancel``,
alongside those two in ``TestTenantScoping``.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.support.api import build_app
from tests.support.builders import make_run_event, make_tenant, make_workflow_run

CROSS_TENANT_REQUESTS = [
    pytest.param("GET", "/events", None, id="events"),
    pytest.param("POST", "/cancel", None, id="cancel"),
    pytest.param("POST", "/confirmations/tool-call-1", {"decision": "approve"}, id="confirmations"),
]


@pytest_asyncio.fixture
async def app(session, engine):
    """Adds the SSE stream's own dependency overrides on top of the base app.

    The stream reads through its own session factory (never the request
    session, which FastAPI closes before a ``StreamingResponse`` body
    finishes) -- bound here to the same in-memory engine as ``session`` so a
    seeded row is visible to it. Short intervals keep the poll-fallback and
    heartbeat tests fast without a real sleep in the test body.
    """
    from juli_backend.api.routes.agent_runs import (
        get_heartbeat_interval_s,
        get_poll_interval_s,
        get_run_event_subscriber,
        get_run_events_session_factory,
    )

    application = build_app(session)
    stream_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _stream_session_factory():
        return stream_session_factory

    application.dependency_overrides[get_run_events_session_factory] = _stream_session_factory
    application.dependency_overrides[get_run_event_subscriber] = lambda: None
    application.dependency_overrides[get_heartbeat_interval_s] = lambda: 0.05
    application.dependency_overrides[get_poll_interval_s] = lambda: 0.02
    yield application
    application.dependency_overrides.clear()


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip("\n").split("\n\n"):
        if not block or block.startswith(":"):
            continue
        record: dict = {}
        for line in block.split("\n"):
            key, _, value = line.partition(": ")
            record[key] = value
        events.append(record)
    return events


class TestSSEWireFormat:
    """The ``events`` route wraps ``event_stream`` as SSE with the right headers."""

    async def test_id_event_and_data_match_the_persisted_envelope(self, auth_client, session, shop):
        run = await make_workflow_run(session, shop, status="completed")
        await make_run_event(session, run.id, 1, payload={"phase_narration": "starting"})
        await make_run_event(
            session,
            run.id,
            2,
            event_type="workflow.completed",
            payload={"stop_reason": "final_response"},
        )

        resp = await auth_client.get(f"/v1/demo/runs/{run.id}/events")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("x-accel-buffering") == "no", (
            "must not let an edge buffer it (#1292)"
        )

        records = _parse_sse(resp.text)
        assert [r["id"] for r in records] == ["1", "2"]
        assert [r["event"] for r in records] == ["workflow.status", "workflow.completed"]
        envelope0 = json.loads(records[0]["data"])
        assert envelope0["workflow_run_id"] == str(run.id)
        assert envelope0["payload"] == {"phase_narration": "starting"}
        envelope1 = json.loads(records[1]["data"])
        assert envelope1["payload"] == {"stop_reason": "final_response"}

    async def test_after_query_param_resolves_the_replay_cursor(self, auth_client, session, shop):
        run = await make_workflow_run(session, shop, status="completed")
        await make_run_event(session, run.id, 1)
        await make_run_event(session, run.id, 2, event_type="workflow.completed")

        resp = await auth_client.get(f"/v1/demo/runs/{run.id}/events", params={"after": 1})

        assert [r["id"] for r in _parse_sse(resp.text)] == ["2"]

    async def test_last_event_id_header_beats_the_after_query_param(
        self, auth_client, session, shop
    ):
        run = await make_workflow_run(session, shop, status="completed")
        await make_run_event(session, run.id, 1)
        await make_run_event(session, run.id, 2, event_type="workflow.completed")

        resp = await auth_client.get(
            f"/v1/demo/runs/{run.id}/events",
            params={"after": 0},
            headers={"Last-Event-ID": "1"},
        )

        assert [r["id"] for r in _parse_sse(resp.text)] == ["2"]


class TestTenantScoping:
    """``_resolve_owned_run`` 404s a run under another shop -- never 403 -- for
    every route it guards."""

    @pytest.mark.parametrize("method, suffix, body", CROSS_TENANT_REQUESTS)
    async def test_cross_tenant_run_returns_404_never_403(
        self, auth_client, session, shop, method, suffix, body
    ):
        _, other_shop = await make_tenant(session)
        other_run = await make_workflow_run(session, other_shop, status="running")

        resp = await auth_client.request(method, f"/v1/demo/runs/{other_run.id}{suffix}", json=body)

        assert resp.status_code == 404
        assert resp.status_code != 403

    async def test_nonexistent_run_returns_404_on_events(self, auth_client):
        resp = await auth_client.get(f"/v1/demo/runs/{uuid.uuid4()}/events")

        assert resp.status_code == 404


class TestCancel:
    """Cancel is an idempotent 202 that sets ``cancel_requested`` unconditionally."""

    async def test_repeat_and_terminal_calls_all_202_and_the_flag_stays_true(
        self, auth_client, session, shop
    ):
        run = await make_workflow_run(session, shop, status="running")
        assert run.cancel_requested is False

        first = await auth_client.post(f"/v1/demo/runs/{run.id}/cancel")
        second = await auth_client.post(f"/v1/demo/runs/{run.id}/cancel")

        assert first.status_code == 202
        assert second.status_code == 202
        await session.refresh(run)
        assert run.cancel_requested is True

        terminal_run = await make_workflow_run(session, shop, status="completed")
        third = await auth_client.post(f"/v1/demo/runs/{terminal_run.id}/cancel")

        assert third.status_code == 202
        await session.refresh(terminal_run)
        assert terminal_run.cancel_requested is True

    async def test_cross_tenant_cancel_never_sets_the_flag(self, auth_client, session, shop):
        _, other_shop = await make_tenant(session)
        other_run = await make_workflow_run(session, other_shop, status="running")

        resp = await auth_client.post(f"/v1/demo/runs/{other_run.id}/cancel")

        assert resp.status_code == 404
        await session.refresh(other_run)
        assert other_run.cancel_requested is False
