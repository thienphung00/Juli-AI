"""Every agent-run route requires a Supabase JWT (ADR-075 decision 3,
issue #1217 / AGT-W5B) -- **verification**, not new behaviour: all four
routes already resolved the run under `get_active_shop`, which itself
depends on `get_current_user`, before this issue. `get_current_user`
(`core/security/dependencies.py`) 401s on a missing/absent bearer credential
before it ever touches `require_env("SUPABASE_JWT_SECRET")` or the database,
so these tests need no JWT secret configured and no dependency override for
auth -- exactly the caller-has-no-credential case.

Explicitly covers the fetch-streamed SSE endpoint (`GET
/v1/demo/runs/{run_id}/events`) per the issue's own callout: "streaming
responses are the easy one to miss." The 401 happens before the route
handler ever constructs a `StreamingResponse`, so it is an ordinary JSON
error response from the client's point of view -- no special streaming
handling needed in the test itself.

`POST /v1/demo/runs` (the previous "create a run for a bare product_id"
route) is REMOVED as of #1222 -- ADR-075 decision 1 forbids a standalone
create-run endpoint entirely, so there is nothing left to auth-gate there;
`test_agent_run_create_route.py` documents the removal itself. Its slot in
this suite is taken by `POST /v1/demo/decisions/{action_card_id}/approve`
-- #1222 is what brought THAT route under auth in the first place (#1217
deliberately left it as the one unauthenticated exception, naming #1222 as
the slice that would close it).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


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

    async def _test_session():
        yield session

    # Non-auth deps still overridden so a route that somehow got past auth
    # would fail on something else entirely, not a missing test wiring
    # artifact -- these tests must fail closed on AUTH specifically.
    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_run_events_session_factory] = lambda: None
    application.dependency_overrides[get_run_event_subscriber] = lambda: None
    application.dependency_overrides[get_heartbeat_interval_s] = lambda: 0.05
    application.dependency_overrides[get_poll_interval_s] = lambda: 0.02
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauthenticated_client(app) -> AsyncClient:
    """No `Authorization` header, no auth dependency override -- the exact
    shape of a caller presenting no credential at all."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_approve_decision_returns_401_without_jwt(unauthenticated_client):
    """#1222: the sole route that creates an agent run. Previously the one
    deliberately unauthenticated exception on this surface (#1217); this is
    the test proving that exception is closed."""
    resp = await unauthenticated_client.post(f"/v1/demo/decisions/{uuid.uuid4()}/approve")
    assert resp.status_code == 401


async def test_events_sse_returns_401_without_jwt(unauthenticated_client):
    """The fetch-streamed SSE endpoint -- explicitly named in the issue as
    the easy one to miss."""
    resp = await unauthenticated_client.get(f"/v1/demo/runs/{uuid.uuid4()}/events")
    assert resp.status_code == 401


async def test_cancel_run_returns_401_without_jwt(unauthenticated_client):
    resp = await unauthenticated_client.post(f"/v1/demo/runs/{uuid.uuid4()}/cancel")
    assert resp.status_code == 401


async def test_confirmation_decision_returns_401_without_jwt(unauthenticated_client):
    resp = await unauthenticated_client.post(
        f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-1",
        json={"decision": "approve"},
    )
    assert resp.status_code == 401
