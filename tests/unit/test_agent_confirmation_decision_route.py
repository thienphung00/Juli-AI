"""HTTP-level tests for `POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}`
-- ADR-075 decision 2, issue #1224 / AGT-W5A.

Before this slice the route was a reserved shape: it tenant-scoped the run
and accepted a `{decision}` body, then always answered `501`. This suite
proves the real authorization ladder, consent binding, and single-use
behavior that replaced it -- `test_agent_run_events_api.py` keeps only the
body-shape (`decision` required) and tenant-scoping tests that predate this
slice and are unaffected by it.

AC -> test map (issue #1224):
- every ladder rung its own status, tested individually ->
  `TestRung1TenantScoping`, `TestRung2RunStatus`, `TestRung3ConfirmationMatch`,
  `TestRung4Expiry`
- cross-tenant and nonexistent both 404 ->
  `TestRung1TenantScoping::test_cross_tenant_and_nonexistent_run_both_404`
- params_sha mismatch never executes the tool (spy = the enqueue call,
  since `ToolExecutor.execute` is only ever reachable via the enqueued
  Celery task -- `resume_agent_workflow` -- never dispatched here) ->
  `test_params_sha_mismatch_is_rejected_and_never_enqueues`
- second decision -> 409, no second enqueue ->
  `test_second_decision_on_same_confirmation_returns_409_and_does_not_enqueue_again`
- option_id not in stored options rejected ->
  `test_approve_with_unknown_option_id_is_rejected`
- expired -> 410, run left for the reaper (untouched) ->
  `TestRung4Expiry`
- no longer 501 for a valid request ->
  `test_endpoint_no_longer_returns_501_for_a_valid_request`
- transition committed before enqueue ->
  `test_transition_is_committed_before_the_enqueue_call`
- structured `error_code` discriminator, distinct per condition (#1224
  review finding: three different 409s were indistinguishable except by
  parsing free text) -> an `error_code` assertion on every failing-path
  test above, plus `test_race_loser_at_transition_returns_confirmation_already_decided_code`
  for the one condition (`_transition_confirmation_or_none` losing a race)
  no sequential test path reaches on its own -- it shares
  `ERROR_CONFIRMATION_ALREADY_DECIDED` with the sequential "already
  decided" 409 deliberately (see that constant's docstring in
  `agent_runs.py`), so this test pins that sharing directly rather than
  assuming it.

The two-sequential-CONFIRM regression (#1221 review) and the concurrent
single-use race proof both need a real Postgres partial-unique index and
real concurrent connections respectively -- neither is reproducible against
this file's shared-session SQLite harness, so both live in
`tests/integration/test_agent_confirmation_decision_postgres.py`, gated on
a reachable `DATABASE_URL`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.api.routes.agent_runs import (
    ERROR_CONFIRMATION_ALREADY_DECIDED,
    ERROR_CONFIRMATION_EXPIRED,
    ERROR_CONFIRMATION_NOT_FOUND,
    ERROR_INVALID_DECISION,
    ERROR_OPTION_ID_REQUIRED,
    ERROR_PARAMS_SHA_MISMATCH,
    ERROR_RUN_NOT_AWAITING_CONFIRMATION,
    ERROR_UNKNOWN_OPTION_ID,
)
from juli_backend.models.models import Product, RunConfirmation, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.runner.confirmation import compute_params_sha

pytestmark = pytest.mark.asyncio

TOOL_CALL_ID = "call-listing-1"
PROPOSED_CHANGE = {"title": "New improved title"}


def _error_code(resp) -> str:
    """Pull the machine-readable discriminator out of this endpoint's error
    shape: `{"detail": {"message": ..., "error_code": ...}}`."""
    return resp.json()["detail"]["error_code"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest_asyncio.fixture
async def user(session):
    u = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop(session, user):
    s = Shop(user_id=user.id, shop_name="AGT-W5A #1224 Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="AGT-W5A #1224 Other Shop")
    session.add(s)
    await session.flush()
    return s


def _client_for(app, user: User, shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _mock_resume_task() -> MagicMock:
    mock_task = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.id = "celery-task-id-1224"
    mock_task.delay.return_value = mock_async_result
    return mock_task


async def _make_run(
    session,
    shop: Shop,
    *,
    status: str = "waiting_approval",
    pending_confirmation: dict | None = None,
) -> WorkflowRunRow:
    product = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-1224-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(product)
    await session.flush()
    run = WorkflowRunRow(
        shop_id=shop.id,
        product_id=product.id,
        state={"pending_confirmation": pending_confirmation} if pending_confirmation else {},
        status=status,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="a" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run


async def _make_confirmation(
    session,
    run: WorkflowRunRow,
    *,
    tool_call_id: str = TOOL_CALL_ID,
    status: str = "pending",
    proposed_change: dict | None = None,
    params_sha: str | None = None,
    expires_at: datetime | None = None,
    selected_option_id: str | None = None,
) -> RunConfirmation:
    change = proposed_change if proposed_change is not None else PROPOSED_CHANGE
    sha = params_sha if params_sha is not None else compute_params_sha(change)
    confirmation = RunConfirmation(
        workflow_run_id=run.id,
        tool_call_id=tool_call_id,
        options=[
            {
                "option_id": "1",
                "proposed_change": change,
                "rationale": "Improves conversion.",
                "params_sha": sha,
            }
        ],
        status=status,
        selected_option_id=selected_option_id,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=4)),
    )
    session.add(confirmation)
    await session.flush()
    await session.commit()
    return confirmation


async def _seed_pending(session, shop: Shop, *, tool_call_id: str = TOOL_CALL_ID):
    """The common case: a run paused mid-CONFIRM with a matching pending
    `run_confirmations` row -- `arguments` and `proposed_change` agree, so
    `params_sha` matches by construction (a caller wanting a mismatch
    overrides one or the other explicitly)."""
    run = await _make_run(
        session,
        shop,
        status="waiting_approval",
        pending_confirmation={
            "call_id": tool_call_id,
            "tool_name": "update_product_listing",
            "arguments": PROPOSED_CHANGE,
        },
    )
    confirmation = await _make_confirmation(session, run, tool_call_id=tool_call_id)
    return run, confirmation


# ---------------------------------------------------------------------------
# Rung 1: tenant scoping -- 404, never 403, cross-tenant and nonexistent alike
# ---------------------------------------------------------------------------


class TestRung1TenantScoping:
    async def test_cross_tenant_and_nonexistent_run_both_404(
        self, app, session, user, shop, other_shop
    ):
        other_run, _ = await _seed_pending(session, other_shop)

        async with _client_for(app, user, shop) as client:
            cross_tenant_resp = await client.post(
                f"/v1/demo/runs/{other_run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )
            nonexistent_resp = await client.post(
                f"/v1/demo/runs/{uuid.uuid4()}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )

        assert cross_tenant_resp.status_code == 404
        assert cross_tenant_resp.status_code != 403
        assert nonexistent_resp.status_code == 404
        # Indistinguishable: same status, same detail shape -- no existence
        # oracle leaks through a differently-worded message either.
        assert cross_tenant_resp.json().keys() == nonexistent_resp.json().keys()


# ---------------------------------------------------------------------------
# Rung 2: run must be waiting_approval
# ---------------------------------------------------------------------------


class TestRung2RunStatus:
    @pytest.mark.parametrize("run_status", ["running", "completed", "cancelled", "queued"])
    async def test_non_waiting_approval_run_returns_409(self, app, session, user, shop, run_status):
        run = await _make_run(session, shop, status=run_status)

        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "decline"},
            )

        assert resp.status_code == 409
        assert _error_code(resp) == ERROR_RUN_NOT_AWAITING_CONFIRMATION


# ---------------------------------------------------------------------------
# Rung 3: tool_call_id must match THE pending confirmation; a second
# decision on an already-resolved one is single-use 409
# ---------------------------------------------------------------------------


class TestRung3ConfirmationMatch:
    async def test_unknown_tool_call_id_returns_404(self, app, session, user, shop):
        run, _ = await _seed_pending(session, shop)

        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/never-paused-here",
                json={"decision": "decline"},
            )

        assert resp.status_code == 404
        assert _error_code(resp) == ERROR_CONFIRMATION_NOT_FOUND

    async def test_already_approved_confirmation_returns_409(self, app, session, user, shop):
        run = await _make_run(session, shop, status="waiting_approval")
        await _make_confirmation(session, run, status="approved", selected_option_id="1")

        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "decline"},
            )

        assert resp.status_code == 409
        assert _error_code(resp) == ERROR_CONFIRMATION_ALREADY_DECIDED

    async def test_already_declined_confirmation_returns_409(self, app, session, user, shop):
        run = await _make_run(session, shop, status="waiting_approval")
        await _make_confirmation(session, run, status="declined")

        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "decline"},
            )

        assert resp.status_code == 409
        assert _error_code(resp) == ERROR_CONFIRMATION_ALREADY_DECIDED

    async def test_row_already_flipped_expired_returns_410(self, app, session, user, shop):
        """Defensive: nothing in this codebase writes `status='expired'`
        onto a `run_confirmations` row today (the reaper only ever
        transitions `workflow_runs.status`), but the endpoint must still
        answer correctly, not 409, if a future writer ever does."""
        run = await _make_run(session, shop, status="waiting_approval")
        await _make_confirmation(session, run, status="expired")

        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "decline"},
            )

        assert resp.status_code == 410
        assert _error_code(resp) == ERROR_CONFIRMATION_EXPIRED


# ---------------------------------------------------------------------------
# Rung 4: wall-clock expiry, checked directly against expires_at -- left for
# the reaper, never force-terminated here
# ---------------------------------------------------------------------------


class TestRung4Expiry:
    async def test_expired_confirmation_returns_410_and_leaves_run_and_row_untouched(
        self, app, session, user, shop
    ):
        run = await _make_run(
            session,
            shop,
            status="waiting_approval",
            pending_confirmation={
                "call_id": TOOL_CALL_ID,
                "tool_name": "update_product_listing",
                "arguments": PROPOSED_CHANGE,
            },
        )
        confirmation = await _make_confirmation(
            session,
            run,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        mock_task = _mock_resume_task()

        with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
            async with _client_for(app, user, shop) as client:
                resp = await client.post(
                    f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                    json={"decision": "approve", "option_id": "1"},
                )

        assert resp.status_code == 410
        assert _error_code(resp) == ERROR_CONFIRMATION_EXPIRED
        mock_task.delay.assert_not_called()

        await session.refresh(run)
        await session.refresh(confirmation)
        assert run.status == "waiting_approval", "the endpoint must never force-terminate the run"
        assert confirmation.status == "pending", "the row is left for the reaper, not mutated here"


# ---------------------------------------------------------------------------
# Body validation -- decision vocabulary, option_id presence/membership
# ---------------------------------------------------------------------------


async def test_unknown_decision_value_is_rejected(app, session, user, shop):
    run, _ = await _seed_pending(session, shop)

    async with _client_for(app, user, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
            json={"decision": "maybe"},
        )

    assert resp.status_code == 422
    assert _error_code(resp) == ERROR_INVALID_DECISION


async def test_approve_without_option_id_is_rejected(app, session, user, shop):
    run, _ = await _seed_pending(session, shop)

    async with _client_for(app, user, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
            json={"decision": "approve"},
        )

    assert resp.status_code == 422
    assert _error_code(resp) == ERROR_OPTION_ID_REQUIRED


async def test_approve_with_unknown_option_id_is_rejected(app, session, user, shop):
    run, _ = await _seed_pending(session, shop)

    async with _client_for(app, user, shop) as client:
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
            json={"decision": "approve", "option_id": "not-a-real-option"},
        )

    assert resp.status_code == 422
    assert _error_code(resp) == ERROR_UNKNOWN_OPTION_ID


# ---------------------------------------------------------------------------
# Consent binding -- a params_sha mismatch never executes the tool
# ---------------------------------------------------------------------------


async def test_params_sha_mismatch_is_rejected_and_never_enqueues(app, session, user, shop):
    """The stored option's `params_sha` was computed over
    `{"title": "New improved title"}`, but the run's reconstructed
    `pending_confirmation.arguments` blob now names a different title --
    simulating drift between what was shown and what would execute.
    `ToolExecutor.execute` is only ever reachable through the enqueued
    `resume_agent_workflow` Celery task (`workers/tasks/agent_workflow.py`);
    proving that `.delay` -- the one call site that could ever reach it --
    is never invoked is exactly "the spy executor recorded zero calls",
    one level up: nothing downstream of a call that never happened can
    have executed anything.
    """
    run = await _make_run(
        session,
        shop,
        status="waiting_approval",
        pending_confirmation={
            "call_id": TOOL_CALL_ID,
            "tool_name": "update_product_listing",
            "arguments": {"title": "A DIFFERENT title than what was shown"},
        },
    )
    confirmation = await _make_confirmation(session, run)  # params_sha over PROPOSED_CHANGE

    mock_task = _mock_resume_task()
    with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )

    assert resp.status_code == 409
    assert _error_code(resp) == ERROR_PARAMS_SHA_MISMATCH
    mock_task.delay.assert_not_called()

    await session.refresh(confirmation)
    assert confirmation.status == "pending", "a mismatch must not consume the single-use decision"


# ---------------------------------------------------------------------------
# Single-use, happy paths, ordering, and the replaced 501
# ---------------------------------------------------------------------------


async def test_decline_transitions_row_and_enqueues_resume_with_approved_false(
    app, session, user, shop
):
    run, confirmation = await _seed_pending(session, shop)
    mock_task = _mock_resume_task()

    with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "decline"},
            )

    assert resp.status_code == 202
    body = resp.json()
    assert body["decision"] == "decline"
    assert body["status"] == "declined"
    assert body["celery_task_id"] == "celery-task-id-1224"

    mock_task.delay.assert_called_once_with(str(run.id), False)

    await session.refresh(confirmation)
    assert confirmation.status == "declined"
    assert confirmation.selected_option_id is None
    assert confirmation.decided_at is not None


async def test_endpoint_no_longer_returns_501_for_a_valid_request(app, session, user, shop):
    """Replaces the old `test_confirmations_route_exists_accepts_shape_and_does_not_authorize`
    501 assertion (`tests/unit/test_agent_run_events_api.py`, pre-#1224):
    the same request shape that used to always 501 now actually authorizes
    and mutates state."""
    run, confirmation = await _seed_pending(session, shop)
    mock_task = _mock_resume_task()

    with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )

    assert resp.status_code != 501
    assert resp.status_code == 202
    body = resp.json()
    assert body["decision"] == "approve"
    assert body["status"] == "approved"

    mock_task.delay.assert_called_once_with(str(run.id), True)

    await session.refresh(confirmation)
    assert confirmation.status == "approved"
    assert confirmation.selected_option_id == "1"


async def test_second_decision_on_same_confirmation_returns_409_and_does_not_enqueue_again(
    app, session, user, shop
):
    run, confirmation = await _seed_pending(session, shop)
    mock_task = _mock_resume_task()

    with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            first = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )
            second = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "decline"},
            )

    assert first.status_code == 202
    assert second.status_code == 409
    assert _error_code(second) == ERROR_CONFIRMATION_ALREADY_DECIDED

    mock_task.delay.assert_called_once()  # never a second enqueue

    await session.refresh(confirmation)
    assert confirmation.status == "approved", "the second (losing) request must not overwrite it"


async def test_race_loser_at_transition_returns_confirmation_already_decided_code(
    app, session, user, shop, monkeypatch
):
    """`_transition_confirmation_or_none` losing a race (its `UPDATE`'s
    `rowcount` comes back 0 because a concurrent request already won) is a
    DIFFERENT code path than rung 3's sequential "already decided" read --
    but the exact same client-observable fact. This pins that both paths
    carry the identical `error_code`, not two different ones, by forcing
    the race-loser branch directly: the row is genuinely still `pending`
    when this request reads it (so rung 3 passes it through), but the
    atomic transition itself is monkeypatched to report a loss, standing
    in for a concurrent winner this single-session unit test cannot
    otherwise construct (real concurrency is
    `tests/integration/test_agent_confirmation_decision_postgres.py
    ::TestSingleUseUnderConcurrentDecisions`'s job).
    """
    from juli_backend.api.routes import agent_runs as agent_runs_module

    run, confirmation = await _seed_pending(session, shop)

    async def _always_lose(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(agent_runs_module, "_transition_confirmation_or_none", _always_lose)

    mock_task = _mock_resume_task()
    with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )

    assert resp.status_code == 409
    assert _error_code(resp) == ERROR_CONFIRMATION_ALREADY_DECIDED
    mock_task.delay.assert_not_called()

    await session.refresh(confirmation)
    assert confirmation.status == "pending", "the monkeypatched loss must not itself mutate the row"


async def test_transition_is_committed_before_the_enqueue_call(app, session, user, shop):
    """Proves the ordering directly via call order, not timing: by the time
    `.delay` fires, `session.commit()` has already returned. Enqueuing
    first would let a worker observe the row still `pending` mid-flight --
    the exact race #1221's review reproduced as an `IntegrityError` against
    a second, sequential CONFIRM pause on the same run.
    """
    run, confirmation = await _seed_pending(session, shop)
    order: list[str] = []

    original_commit = session.commit

    async def _wrapped_commit():
        await original_commit()
        order.append("commit")

    mock_task = _mock_resume_task()

    def _delay_side_effect(*args, **kwargs):
        order.append("enqueue")
        return mock_task.delay.return_value

    mock_task.delay.side_effect = _delay_side_effect

    with (
        patch.object(session, "commit", _wrapped_commit),
        patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task),
    ):
        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{run.id}/confirmations/{TOOL_CALL_ID}",
                json={"decision": "approve", "option_id": "1"},
            )

    assert resp.status_code == 202
    assert order == ["commit", "enqueue"]

    await session.refresh(confirmation)
    assert confirmation.status == "approved"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
