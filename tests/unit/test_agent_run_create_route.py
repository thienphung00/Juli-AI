"""`POST /v1/demo/runs` -- REMOVED in #1222.

This route (issue #1145's Gap 2 fix) used to create a `workflow_runs` row
directly from a caller-supplied `product_id`, with no `ActionCard` involved
at all. Owner decision 2026-08-21 (ADR-075 decision 1): "No 'create run'
endpoint and no `approval_id` parameter exist on the agent path" -- a
standalone endpoint taking a bare `product_id` is exactly the caller-
supplied-authority-claim shape that decision forbids, independent of
whether it also required a card argument. `POST /v1/demo/decisions/
{action_card_id}/approve` (`api/routes/demo_execution.py`, transaction in
`services/agent/approval.py`) is now the only way a `workflow_runs` row
comes into existence -- see `test_agent_approval_transaction.py` and
`test_api_demo_execution.py` for its coverage, and
`test_no_unapproved_run_creation.py` for the structural proof that no route
anywhere constructs a `WorkflowRun` directly any more.

Everything this old file used to prove at the HTTP boundary --
`RunState.from_dict` accepting the created row's `state` blob without
raising (issue #1188's regression), and the opening `source: "juli"`
context message carrying the ActionCard's own rationale -- still happens,
just through the new path; that coverage now lives in
`test_agent_approval_transaction.py`'s
`TestInitialRunStateAndPromptPin` (unit-level, against
`services.agent.approval._initial_run_state_for`/`approve_action_card`
directly) rather than through this route, which no longer exists to route
through.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


async def test_post_demo_runs_no_longer_exists(app):
    """405, not 2xx -- direct POST run-creation stays removed; approve is the
    only run-creation path (ADR-075 decision 1). Until #1310 this asserted
    404 because NO verb lived at /v1/demo/runs; the polled run-list read
    model now registers GET there, so Starlette correctly answers 405 for
    POST (path exists, method doesn't). The guard's intent is unchanged:
    a 2xx here would mean run-creation-by-POST came back."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/demo/runs", json={"product_id": "not-even-checked"})
    assert resp.status_code == 405
