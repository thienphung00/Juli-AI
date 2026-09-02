"""HTTP-level tests for ``POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}``
(ADR-075 decision 2, #1224 / AGT-W5A).

The ladder itself -- each rung's own refusal, the consent-binding hash check,
the sequential-vs-race-loser code sharing -- is proven without HTTP in
``test_agent_run_confirmations.py`` by calling ``decide_confirmation``
directly. What is left to prove here is the route's own contribution: tenant
scoping resolves before the ladder runs, each rung's ``ConfirmationRejected``
becomes the documented HTTP status and ``error_code`` body, the confirmation
rate limit gates the endpoint, a won decision is committed *before* the
resume task is enqueued (#1221), and the response shape a client actually
sees.

The two-sequential-CONFIRM regression and the concurrent single-use race both
need a real Postgres partial-unique index and real concurrent connections,
neither reproducible against this file's shared-session SQLite harness; both
live in ``tests/integration/test_agent_confirmation_decision_postgres.py``.
"""

from __future__ import annotations

import functools
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from juli_backend.api.routes import agent_runs as route_module
from juli_backend.models.models import RunConfirmation
from juli_backend.services.agent.abuse_limits import (
    InMemoryAbuseLimitGate,
    set_agent_abuse_limit_gate,
)
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent_runs import (
    ERROR_CONFIRMATION_ALREADY_DECIDED,
    ERROR_CONFIRMATION_EXPIRED,
    ERROR_CONFIRMATION_NOT_FOUND,
    ERROR_INVALID_DECISION,
    ERROR_OPTION_ID_REQUIRED,
    ERROR_PARAMS_SHA_MISMATCH,
    ERROR_RUN_NOT_AWAITING_CONFIRMATION,
    ERROR_UNKNOWN_OPTION_ID,
)
from tests.support.builders import make_tenant, make_workflow_run

TOOL_CALL_ID = "call-listing-1"
PROPOSED_CHANGE = {"title": "New improved title"}


def _error_code(resp) -> str:
    """The machine-readable discriminator in this endpoint's error shape:
    ``{"detail": {"message": ..., "error_code": ...}}``."""
    return resp.json()["detail"]["error_code"]


class RecordingEnqueue:
    """``_enqueue_resume_agent_workflow``'s real signature, recording each call."""

    def __init__(self, celery_task_id: str = "celery-task-1") -> None:
        self.calls: list[tuple[uuid.UUID, bool]] = []
        self._celery_task_id = celery_task_id

    def __call__(self, run_id: uuid.UUID, *, approved: bool) -> str:
        self.calls.append((run_id, approved))
        return self._celery_task_id


async def make_confirmation(
    session,
    run,
    *,
    tool_call_id: str = TOOL_CALL_ID,
    status: str = "pending",
    proposed_change: dict | None = None,
    params_sha: str | None = None,
    expires_at: datetime | None = None,
) -> RunConfirmation:
    """A ``run_confirmations`` row. Candidate for ``tests/support/builders.py``."""
    change = proposed_change if proposed_change is not None else PROPOSED_CHANGE
    sha = params_sha if params_sha is not None else compute_params_sha(change)
    confirmation = RunConfirmation(
        workflow_run_id=run.id,
        tool_call_id=tool_call_id,
        options=[
            {"option_id": "1", "proposed_change": change, "rationale": "why", "params_sha": sha}
        ],
        status=status,
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=4)),
    )
    session.add(confirmation)
    await session.flush()
    return confirmation


async def seed_pending(session, shop, *, tool_call_id: str = TOOL_CALL_ID, arguments=None):
    run = await make_workflow_run(
        session,
        shop,
        status="waiting_approval",
        state={
            "pending_confirmation": {
                "call_id": tool_call_id,
                "tool_name": "update_product_listing",
                "arguments": arguments if arguments is not None else PROPOSED_CHANGE,
            }
        },
    )
    confirmation = await make_confirmation(session, run, tool_call_id=tool_call_id)
    return run, confirmation


async def _post(auth_client, run_id, tool_call_id, body):
    return await auth_client.post(f"/v1/demo/runs/{run_id}/confirmations/{tool_call_id}", json=body)


# ---------------------------------------------------------------------------
# Ladder rung -> HTTP status + error_code
# ---------------------------------------------------------------------------


async def _run_status_setup(session, shop, *, status):
    run = await make_workflow_run(session, shop, status=status)
    return run.id, TOOL_CALL_ID, {"decision": "decline"}


async def _confirmation_not_found_setup(session, shop):
    run = await make_workflow_run(session, shop, status="waiting_approval")
    return run.id, "never-paused-here", {"decision": "decline"}


async def _already_decided_setup(session, shop, *, status):
    run = await make_workflow_run(session, shop, status="waiting_approval")
    await make_confirmation(session, run, status=status)
    return run.id, TOOL_CALL_ID, {"decision": "decline"}


async def _invalid_decision_setup(session, shop):
    run, _ = await seed_pending(session, shop)
    return run.id, TOOL_CALL_ID, {"decision": "maybe"}


async def _option_id_required_setup(session, shop):
    run, _ = await seed_pending(session, shop)
    return run.id, TOOL_CALL_ID, {"decision": "approve"}


async def _unknown_option_id_setup(session, shop):
    run, _ = await seed_pending(session, shop)
    return run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "not-a-real-option"}


LADDER_RUNGS = [
    pytest.param(
        functools.partial(_run_status_setup, status="queued"),
        409,
        ERROR_RUN_NOT_AWAITING_CONFIRMATION,
        id="run-queued",
    ),
    pytest.param(
        functools.partial(_run_status_setup, status="running"),
        409,
        ERROR_RUN_NOT_AWAITING_CONFIRMATION,
        id="run-running",
    ),
    pytest.param(
        functools.partial(_run_status_setup, status="completed"),
        409,
        ERROR_RUN_NOT_AWAITING_CONFIRMATION,
        id="run-completed",
    ),
    pytest.param(
        functools.partial(_run_status_setup, status="cancelled"),
        409,
        ERROR_RUN_NOT_AWAITING_CONFIRMATION,
        id="run-cancelled",
    ),
    pytest.param(
        _confirmation_not_found_setup,
        404,
        ERROR_CONFIRMATION_NOT_FOUND,
        id="confirmation-not-found",
    ),
    pytest.param(
        functools.partial(_already_decided_setup, status="approved"),
        409,
        ERROR_CONFIRMATION_ALREADY_DECIDED,
        id="already-approved",
    ),
    pytest.param(
        functools.partial(_already_decided_setup, status="declined"),
        409,
        ERROR_CONFIRMATION_ALREADY_DECIDED,
        id="already-declined",
    ),
    pytest.param(
        functools.partial(_already_decided_setup, status="expired"),
        410,
        ERROR_CONFIRMATION_EXPIRED,
        id="row-flipped-expired",
    ),
    pytest.param(_invalid_decision_setup, 422, ERROR_INVALID_DECISION, id="invalid-decision"),
    pytest.param(_option_id_required_setup, 422, ERROR_OPTION_ID_REQUIRED, id="option-id-required"),
    pytest.param(_unknown_option_id_setup, 422, ERROR_UNKNOWN_OPTION_ID, id="unknown-option-id"),
]


class TestLadderRungs:
    """Each rung's ``ConfirmationRejected`` becomes its documented status and code."""

    @pytest.mark.parametrize("setup, expected_status, expected_error_code", LADDER_RUNGS)
    async def test_rung_maps_to_its_http_status_and_error_code(
        self, auth_client, session, shop, setup, expected_status, expected_error_code
    ):
        run_id, tool_call_id, body = await setup(session, shop)

        resp = await _post(auth_client, run_id, tool_call_id, body)

        assert resp.status_code == expected_status
        assert _error_code(resp) == expected_error_code


class TestTenantScoping:
    """A run under another shop is missing, not forbidden -- no existence oracle."""

    async def test_cross_tenant_and_nonexistent_run_both_404(self, auth_client, session, shop):
        _, other_shop = await make_tenant(session)
        other_run, _ = await seed_pending(session, other_shop)

        cross_tenant = await _post(
            auth_client, other_run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )
        nonexistent = await _post(
            auth_client, uuid.uuid4(), TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )

        assert cross_tenant.status_code == 404
        assert cross_tenant.status_code != 403
        assert nonexistent.status_code == 404
        # Same status, same detail shape -- no existence oracle leaks through
        # a differently-worded message either.
        assert cross_tenant.json().keys() == nonexistent.json().keys()

    async def test_decision_field_is_required(self, auth_client, session, shop):
        run = await make_workflow_run(session, shop, status="waiting_approval")

        resp = await _post(auth_client, run.id, TOOL_CALL_ID, {})

        assert resp.status_code == 422


class TestRateLimit:
    """The confirmation bucket gates this endpoint (ADR-075 decision 4)."""

    async def test_exhausted_bucket_returns_429_with_retry_after(self, auth_client, session, shop):
        run, _ = await seed_pending(session, shop)
        set_agent_abuse_limit_gate(InMemoryAbuseLimitGate(confirmation_max_requests=0))

        resp = await _post(auth_client, run.id, TOOL_CALL_ID, {"decision": "decline"})

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers


class TestExpiryAndConsentNeverEnqueue:
    """A refused decision never enqueues the resume, and never mutates state."""

    async def test_wall_clock_expired_leaves_run_and_row_untouched(
        self, auth_client, session, shop, monkeypatch
    ):
        run, confirmation = await seed_pending(session, shop)
        confirmation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.flush()
        enqueue = RecordingEnqueue()
        monkeypatch.setattr(route_module, "_enqueue_resume_agent_workflow", enqueue)

        resp = await _post(
            auth_client, run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )

        assert resp.status_code == 410
        assert _error_code(resp) == ERROR_CONFIRMATION_EXPIRED
        assert enqueue.calls == []
        await session.refresh(run)
        await session.refresh(confirmation)
        assert run.status == "waiting_approval"
        assert confirmation.status == "pending"

    async def test_params_sha_mismatch_never_enqueues(
        self, auth_client, session, shop, monkeypatch
    ):
        run, confirmation = await seed_pending(
            session, shop, arguments={"title": "a different title than what was shown"}
        )
        enqueue = RecordingEnqueue()
        monkeypatch.setattr(route_module, "_enqueue_resume_agent_workflow", enqueue)

        resp = await _post(
            auth_client, run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )

        assert resp.status_code == 409
        assert _error_code(resp) == ERROR_PARAMS_SHA_MISMATCH
        assert enqueue.calls == []
        await session.refresh(confirmation)
        assert confirmation.status == "pending"


class TestWonDecisions:
    """A won decision answers 202, transitions the row, and enqueues the resume."""

    async def test_decline_enqueues_with_approved_false(
        self, auth_client, session, shop, monkeypatch
    ):
        run, confirmation = await seed_pending(session, shop)
        enqueue = RecordingEnqueue()
        monkeypatch.setattr(route_module, "_enqueue_resume_agent_workflow", enqueue)

        resp = await _post(auth_client, run.id, TOOL_CALL_ID, {"decision": "decline"})

        assert resp.status_code == 202
        assert resp.json() == {
            "decision": "decline",
            "status": "declined",
            "celery_task_id": "celery-task-1",
        }
        assert enqueue.calls == [(run.id, False)]
        await session.refresh(confirmation)
        assert confirmation.status == "declined"
        assert confirmation.selected_option_id is None

    async def test_approve_enqueues_with_approved_true(
        self, auth_client, session, shop, monkeypatch
    ):
        run, confirmation = await seed_pending(session, shop)
        enqueue = RecordingEnqueue()
        monkeypatch.setattr(route_module, "_enqueue_resume_agent_workflow", enqueue)

        resp = await _post(
            auth_client, run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )

        assert resp.status_code == 202
        assert resp.json() == {
            "decision": "approve",
            "status": "approved",
            "celery_task_id": "celery-task-1",
        }
        assert enqueue.calls == [(run.id, True)]
        await session.refresh(confirmation)
        assert confirmation.status == "approved"
        assert confirmation.selected_option_id == "1"

    async def test_second_decision_returns_409_and_does_not_enqueue_again(
        self, auth_client, session, shop, monkeypatch
    ):
        run, confirmation = await seed_pending(session, shop)
        enqueue = RecordingEnqueue()
        monkeypatch.setattr(route_module, "_enqueue_resume_agent_workflow", enqueue)

        first = await _post(
            auth_client, run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )
        second = await _post(auth_client, run.id, TOOL_CALL_ID, {"decision": "decline"})

        assert first.status_code == 202
        assert second.status_code == 409
        assert _error_code(second) == ERROR_CONFIRMATION_ALREADY_DECIDED
        assert enqueue.calls == [(run.id, True)], "never a second enqueue"
        await session.refresh(confirmation)
        assert confirmation.status == "approved", "the losing request must not overwrite it"

    async def test_commit_happens_before_the_enqueue_call(
        self, auth_client, session, shop, monkeypatch
    ):
        """Enqueuing first would let a worker observe the row still ``pending``
        mid-flight -- the exact race #1221's review reproduced."""
        run, confirmation = await seed_pending(session, shop)
        order: list[str] = []
        original_commit = session.commit

        async def _wrapped_commit() -> None:
            await original_commit()
            order.append("commit")

        def _enqueue(run_id: uuid.UUID, *, approved: bool) -> str:
            order.append("enqueue")
            return "celery-task-1"

        monkeypatch.setattr(session, "commit", _wrapped_commit)
        monkeypatch.setattr(route_module, "_enqueue_resume_agent_workflow", _enqueue)

        resp = await _post(
            auth_client, run.id, TOOL_CALL_ID, {"decision": "approve", "option_id": "1"}
        )

        assert resp.status_code == 202
        assert order == ["commit", "enqueue"]
        await session.refresh(confirmation)
        assert confirmation.status == "approved"
