"""HTTP-level tests for the agent-run routes -- ADR-074 decisions 3 and 5,
#1128 / AGT-W3B: the SSE wire format, tenant scoping (404 never 403), and
cancel idempotency.

`event_stream`'s internal mechanics (subscribe-before-replay, dedupe,
heartbeat, poll fallback, terminal close) are proven directly against the
generator in `test_agent_run_events_stream.py`; this file proves the
FastAPI route wraps it correctly and enforces auth/tenant scoping.

The confirmation-decision endpoint's own authorization ladder, consent
binding and single-use behavior (ADR-075 decision 2, issue #1224 / AGT-W5A
-- this route used to be a reserved 501 shape only) has its own dedicated
suite: `test_agent_confirmation_decision_route.py`. The one confirmations
test that stays here, `test_cross_tenant_run_returns_404_never_403_on_confirmations`,
is kept alongside its `/events` and `/cancel` siblings because all three
prove the identical `_resolve_owned_run` tenant-scoping contract this file
is otherwise about; `test_confirmations_route_requires_decision_field`
stays for the same reason (a body-shape check, not a decision-ladder one).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.api.routes.agent_runs import (
        get_heartbeat_interval_s,
        get_poll_interval_s,
        get_run_event_subscriber,
        get_run_events_session_factory,
    )
    from juli_backend.database import get_session

    application = create_app()
    stream_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _test_session():
        yield session

    async def _stream_session_factory():
        return stream_session_factory

    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_run_events_session_factory] = _stream_session_factory
    application.dependency_overrides[get_run_event_subscriber] = lambda: None
    application.dependency_overrides[get_heartbeat_interval_s] = lambda: 0.05
    application.dependency_overrides[get_poll_interval_s] = lambda: 0.02
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(session):
    u = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop(session, user):
    s = Shop(user_id=user.id, shop_name="AGT-W3B P8-4 Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="AGT-W3B P8-4 Other Shop")
    session.add(s)
    await session.flush()
    return s


async def _make_run(session: AsyncSession, shop: Shop, status: str = "running") -> WorkflowRunRow:
    product = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-w3b-p8-4-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(product)
    await session.flush()
    run = WorkflowRunRow(
        shop_id=shop.id,
        product_id=product.id,
        state={},
        status=status,
        prompt_version="optimize_product.v1",
        prompt_sha256="a" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run


async def _add_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    seq: int,
    event_type: str,
    payload: dict,
) -> None:
    session.add(
        WorkflowRunEventRow(
            workflow_run_id=run_id,
            sequence_number=seq,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            payload=payload,
            v=1,
        )
    )
    await session.commit()


def _client_for(app, user: User, shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip("\n").split("\n\n"):
        if not block or block.startswith(":"):
            continue
        lines = block.split("\n")
        record: dict = {}
        for line in lines:
            key, _, value = line.partition(": ")
            record[key] = value
        events.append(record)
    return events


# ---------------------------------------------------------------------------
# AC (ADR-074 d.2) -- SSE wire format
# ---------------------------------------------------------------------------


async def test_sse_wire_format_id_event_data(app, session, user, shop):
    run = await _make_run(session, shop, status="running")
    await _add_event(session, run.id, 1, "workflow.status", {"phase_narration": "starting"})
    await _add_event(
        session,
        run.id,
        2,
        "workflow.completed",
        {"stop_reason": "final_response"},
    )

    async with _client_for(app, user, shop) as client:
        resp = await client.get(f"/v1/demo/runs/{run.id}/events")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    records = _parse_sse(resp.text)
    assert len(records) == 2

    assert records[0]["id"] == "1"
    assert records[0]["event"] == "workflow.status"
    envelope0 = json.loads(records[0]["data"])
    assert envelope0["sequence_number"] == 1
    assert envelope0["event_type"] == "workflow.status"
    assert envelope0["workflow_run_id"] == str(run.id)
    assert envelope0["payload"] == {"phase_narration": "starting"}
    assert envelope0["v"] == 1

    assert records[1]["id"] == "2"
    assert records[1]["event"] == "workflow.completed"
    envelope1 = json.loads(records[1]["data"])
    assert envelope1["payload"] == {"stop_reason": "final_response"}


async def test_after_query_param_resolves_after_seq(app, session, user, shop):
    run = await _make_run(session, shop, status="completed")
    await _add_event(session, run.id, 1, "workflow.status", {"phase_narration": "a"})
    await _add_event(session, run.id, 2, "workflow.completed", {"stop_reason": "final_response"})

    async with _client_for(app, user, shop) as client:
        resp = await client.get(f"/v1/demo/runs/{run.id}/events", params={"after": 1})

    records = _parse_sse(resp.text)
    assert [r["id"] for r in records] == ["2"]


async def test_last_event_id_header_takes_priority_over_after_query_param(app, session, user, shop):
    run = await _make_run(session, shop, status="completed")
    await _add_event(session, run.id, 1, "workflow.status", {"phase_narration": "a"})
    await _add_event(session, run.id, 2, "workflow.completed", {"stop_reason": "final_response"})

    async with _client_for(app, user, shop) as client:
        resp = await client.get(
            f"/v1/demo/runs/{run.id}/events",
            params={"after": 0},
            headers={"Last-Event-ID": "1"},
        )

    records = _parse_sse(resp.text)
    assert [r["id"] for r in records] == ["2"]


# ---------------------------------------------------------------------------
# AC (ADR-074 d.5) -- tenant scoping: 404 never 403
# ---------------------------------------------------------------------------


async def test_cross_tenant_run_returns_404_never_403_on_events(
    app, session, user, other_shop, shop
):
    other_run = await _make_run(session, other_shop, status="running")

    async with _client_for(app, user, shop) as client:
        resp = await client.get(f"/v1/demo/runs/{other_run.id}/events")

    assert resp.status_code == 404
    assert resp.status_code != 403


async def test_cross_tenant_run_returns_404_never_403_on_cancel(
    app, session, user, other_shop, shop
):
    other_run = await _make_run(session, other_shop, status="running")

    async with _client_for(app, user, shop) as client:
        resp = await client.post(f"/v1/demo/runs/{other_run.id}/cancel")

    assert resp.status_code == 404
    assert resp.status_code != 403


async def test_cross_tenant_run_returns_404_never_403_on_confirmations(
    app, session, user, other_shop, shop
):
    other_run = await _make_run(session, other_shop, status="waiting_approval")

    async with _client_for(app, user, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{other_run.id}/confirmations/tool-call-1",
            json={"decision": "approve"},
        )

    assert resp.status_code == 404
    assert resp.status_code != 403


async def test_nonexistent_run_returns_404(app, user, shop):
    async with _client_for(app, user, shop) as client:
        resp = await client.get(f"/v1/demo/runs/{uuid.uuid4()}/events")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC (ADR-074 d.5) -- cancel is 202, idempotent
# ---------------------------------------------------------------------------


async def test_cancel_returns_202_twice_and_after_terminal(app, session, user, shop):
    run = await _make_run(session, shop, status="running")

    async with _client_for(app, user, shop) as client:
        first = await client.post(f"/v1/demo/runs/{run.id}/cancel")
        second = await client.post(f"/v1/demo/runs/{run.id}/cancel")

    assert first.status_code == 202
    assert second.status_code == 202

    terminal_run = await _make_run(session, shop, status="completed")
    async with _client_for(app, user, shop) as client:
        third = await client.post(f"/v1/demo/runs/{terminal_run.id}/cancel")

    assert third.status_code == 202


# ---------------------------------------------------------------------------
# AC (issue #1145 Gap 3) -- cancel writes workflow_runs.cancel_requested
# ---------------------------------------------------------------------------


async def test_cancel_sets_cancel_requested_flag(app, session, user, shop):
    run = await _make_run(session, shop, status="running")
    assert run.cancel_requested is False

    async with _client_for(app, user, shop) as client:
        resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")

    assert resp.status_code == 202
    await session.refresh(run)
    assert run.cancel_requested is True


async def test_cancel_success_is_logged(app, session, user, shop, caplog):
    run = await _make_run(session, shop, status="running")
    run_id = run.id

    with caplog.at_level("INFO", logger="juli_backend.api.routes.agent_runs"):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/runs/{run_id}/cancel")

    assert resp.status_code == 202
    records = [r for r in caplog.records if r.message == "agent_run_cancel_requested"]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "shop_id", None) == str(shop.id)
    assert getattr(record, "run_id", None) == str(run_id)


async def test_cancel_twice_stays_202_and_flag_stays_true(app, session, user, shop):
    run = await _make_run(session, shop, status="running")

    async with _client_for(app, user, shop) as client:
        first = await client.post(f"/v1/demo/runs/{run.id}/cancel")
        second = await client.post(f"/v1/demo/runs/{run.id}/cancel")

    assert first.status_code == 202
    assert second.status_code == 202
    await session.refresh(run)
    assert run.cancel_requested is True


async def test_cancel_on_terminal_run_still_sets_flag_without_error(app, session, user, shop):
    run = await _make_run(session, shop, status="completed")

    async with _client_for(app, user, shop) as client:
        resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")

    assert resp.status_code == 202
    await session.refresh(run)
    assert run.cancel_requested is True


async def test_cross_tenant_cancel_never_sets_flag_on_other_shops_run(
    app, session, user, other_shop, shop
):
    other_run = await _make_run(session, other_shop, status="running")

    async with _client_for(app, user, shop) as client:
        resp = await client.post(f"/v1/demo/runs/{other_run.id}/cancel")

    assert resp.status_code == 404
    await session.refresh(other_run)
    assert other_run.cancel_requested is False


# ---------------------------------------------------------------------------
# AC (ADR-075 d.2 / #1224) -- confirmations body-shape validation. The
# route's own authorization ladder, consent binding and single-use tests
# live in `test_agent_confirmation_decision_route.py`; the 501-only
# "reserved shape" test this replaced is
# `test_agent_confirmation_decision_route.py
# ::test_endpoint_no_longer_returns_501_for_a_valid_request`.
# ---------------------------------------------------------------------------


async def test_confirmations_route_requires_decision_field(app, session, user, shop):
    run = await _make_run(session, shop, status="waiting_approval")

    async with _client_for(app, user, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/confirmations/tool-call-1",
            json={},
        )

    assert resp.status_code == 422
