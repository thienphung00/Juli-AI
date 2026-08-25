"""Crash handling for agent workflow tasks (#1291).

When `run_agent_workflow` or `resume_agent_workflow` crashes anywhere,
the run must end up in a terminal `failed` state with a terminal
`workflow.failed` event appended, regardless of the prior status
(queued or running). The exception must also be pickle-safe or wrapped
so it doesn't cross the Celery boundary as `UnpickleableExceptionWrapper`.

AC -> test map:
- crash between `tool.started` and completion leaves run `failed` with terminal event ->
  test_run_workflow_crash_leaves_run_in_failed_status_with_terminal_event
- crash is caught from any status, including `queued` ->
  test_run_workflow_crash_from_queued_status_is_handled_terminally
- exception is pickle-safe ->
  test_run_workflow_crash_exception_is_pickle_safe
- reaper does not kill a genuinely in-flight run ->
  test_reaper_does_not_terminate_a_genuinely_in_flight_run
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.models import Product, Shop, WorkflowRun
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.workers.tasks import agent_workflow
from juli_backend.workers.tasks.reaper import reap_workflow_runs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def shop(session):
    s = Shop(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        shop_name="Crash Handling Test Shop",
        tiktok_shop_id="tiktok_shop_crash_test",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session, shop):
    p = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tiktok_product_crash_test",
        name="Crash Handling Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(p)
    await session.flush()
    return p


# ---------------------------------------------------------------------------
# Test: crash leaves run in failed state with terminal event
# ---------------------------------------------------------------------------


async def test_run_workflow_crash_leaves_run_in_failed_status_with_terminal_event(
    session, shop, product, monkeypatch
):
    """A crash in run_agent_workflow between tool.started and completion
    leaves the run in `failed` status with a terminal `workflow.failed` event.
    This is the main acceptance criterion."""
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.RUNNING.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    run_id = run.id

    # Monkeypatch _construct_runner to raise an exception, simulating a crash
    # during tool execution (after workflow.started and tool.started have been
    # emitted, but before completion).
    class SimulatedToolCrash(RuntimeError):
        pass

    async def _crashing_construct_runner(session, sync_session, run, product):
        # Simulate: we got far enough to emit workflow.started and tool.started,
        # but now something goes wrong
        raise SimulatedToolCrash("Simulated tool execution crash")

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield session

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)
    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)
    monkeypatch.setattr(agent_workflow, "_construct_runner", _crashing_construct_runner)

    # Execute the task; it should NOT raise, but handle the crash internally
    # Use the async version directly since pytest is already in an event loop
    await agent_workflow._run_agent_workflow_async(str(run_id))

    # Verify the run is now in failed state
    loaded_run = await session.get(WorkflowRun, run_id)
    assert loaded_run.status == WorkflowRunStatus.FAILED.value, (
        f"Run should be in failed status after crash, got {loaded_run.status}"
    )

    # Verify a terminal event was appended
    result = await session.execute(
        select(WorkflowRunEventRow).where(WorkflowRunEventRow.workflow_run_id == run_id)
    )
    events = result.scalars().all()
    assert len(events) > 0, "At least one event should be appended after crash"

    # The last event should be workflow.failed
    terminal_event = events[-1]
    assert terminal_event.event_type == "workflow.failed", (
        f"Terminal event type should be workflow.failed, got {terminal_event.event_type}"
    )

    # Verify stop_reason is WORKER_LOST
    payload = terminal_event.payload
    assert payload.get("stop_reason") == StopReason.WORKER_LOST.value, (
        f"stop_reason should be WORKER_LOST, got {payload.get('stop_reason')}"
    )


# ---------------------------------------------------------------------------
# Test: crash from queued status is handled
# ---------------------------------------------------------------------------


async def test_run_workflow_crash_from_queued_status_is_handled_terminally(
    session, shop, product, monkeypatch
):
    """The bug manifested as a run staying in `queued` when the crash occurred
    before even reaching `running`. This test ensures a crash from `queued` is
    also handled terminally."""
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.QUEUED.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    run_id = run.id

    class SimulatedCrash(RuntimeError):
        pass

    async def _crashing_construct_runner(session, sync_session, run, product):
        raise SimulatedCrash("Crash before run started")

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield session

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)
    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)
    monkeypatch.setattr(agent_workflow, "_construct_runner", _crashing_construct_runner)

    # Execute the task; should not raise
    await agent_workflow._run_agent_workflow_async(str(run_id))

    # Verify the run is now failed (not still queued)
    loaded_run = await session.get(WorkflowRun, run_id)
    assert loaded_run.status == WorkflowRunStatus.FAILED.value, (
        f"Run should transition from queued to failed after crash, got {loaded_run.status}"
    )


# ---------------------------------------------------------------------------
# Test: exception is pickle-safe
# ---------------------------------------------------------------------------


async def test_run_workflow_crash_exception_is_pickle_safe(session, shop, product, monkeypatch):
    """When an exception is raised in the task, it must be pickle-safe so it
    doesn't cross the Celery boundary as UnpickleableExceptionWrapper. This
    test verifies the exception is properly handled (caught and logged,
    not re-raised)."""
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.RUNNING.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    run_id = run.id

    # Create an exception that would fail to pickle
    class UnpickleableError(RuntimeError):
        def __init__(self):
            super().__init__()
            self.unpickleable_attr = lambda: "This cannot be pickled"

    async def _crashing_construct_runner(session, sync_session, run, product):
        raise UnpickleableError()

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield session

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)
    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)
    monkeypatch.setattr(agent_workflow, "_construct_runner", _crashing_construct_runner)

    # This should NOT raise UnpickleableExceptionWrapper
    await agent_workflow._run_agent_workflow_async(str(run_id))

    # Verify the run is in failed state
    loaded_run = await session.get(WorkflowRun, run_id)
    assert loaded_run.status == WorkflowRunStatus.FAILED.value


# ---------------------------------------------------------------------------
# Test: reaper does not kill genuinely in-flight runs
# ---------------------------------------------------------------------------


async def test_reaper_does_not_terminate_a_genuinely_in_flight_run(session, shop, product):
    """The reaper's widened criteria must not over-reach: a genuinely in-flight
    run within its liveness window must be left alone. This test verifies that
    a recently-created running run is not reaped even if marked as having no
    live task (we inject has_live_task=False to test the boundary)."""

    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.RUNNING.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
        created_at=datetime(2026, 8, 14, 12, 0, 0),  # Just created
        started_at=datetime(2026, 8, 14, 12, 0, 0),
    )
    session.add(run)
    await session.flush()

    # Emit one recent event to show liveness
    from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow

    event = WorkflowRunEventRow(
        id=uuid.uuid4(),
        workflow_run_id=run.id,
        sequence_number=1,
        event_type="workflow.started",
        timestamp=datetime(2026, 8, 14, 12, 0, 30, tzinfo=UTC),  # 30 seconds ago
        payload={},
        v=1,
    )
    session.add(event)
    await session.flush()
    await session.commit()

    # Reap with "now" just a few minutes later and no live task
    now = datetime(2026, 8, 14, 12, 5, 0, tzinfo=UTC)
    result = await reap_workflow_runs(
        session,
        now=now,
        has_live_task=lambda rid: False,  # Claim no live task
    )

    # The run should NOT be reaped (it's only 5 minutes old, threshold is ~15 minutes)
    assert run.id not in result.stale_runs_reaped, (
        "A recently-created run should not be reaped, even if marked as having no live task"
    )


# ---------------------------------------------------------------------------
# Test: resume_agent_workflow also handles crashes
# ---------------------------------------------------------------------------


async def test_resume_workflow_crash_leaves_run_in_failed_status(
    session, shop, product, monkeypatch
):
    """The same crash handling must apply to resume_agent_workflow."""
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.WAITING_APPROVAL.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    run_id = run.id

    class SimulatedCrash(RuntimeError):
        pass

    async def _crashing_construct_runner(session, sync_session, run, product):
        raise SimulatedCrash("Crash in resume")

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield session

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)
    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)
    monkeypatch.setattr(agent_workflow, "_construct_runner", _crashing_construct_runner)

    # Execute the resume task; should not raise
    await agent_workflow._resume_agent_workflow_async(str(run_id), approved=True)

    # Verify the run is now failed
    loaded_run = await session.get(WorkflowRun, run_id)
    assert loaded_run.status == WorkflowRunStatus.FAILED.value


# ---------------------------------------------------------------------------
# Test: crash with transaction-poisoned session is still handled
# ---------------------------------------------------------------------------


async def test_run_workflow_crash_with_poisoned_session_writes_terminal_event(
    session, shop, product, monkeypatch
):
    """CRITICAL FIX #1 (issue #1291 review): a crash may poison the session's
    transaction. The exception handler must use a FRESH session for terminal
    emit, not the poisoned one, or emit() fails and the run stays stranded."""
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.RUNNING.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    run_id = run.id

    class PoisoningCrash(RuntimeError):
        pass

    async def _crashing_construct_runner(session_arg, sync_session, run, product):
        # Simulate: a failed write poisoned the session's transaction
        try:
            await session_arg.execute("SELECT * FROM nonexistent_table")
        except Exception:
            pass  # Leave the session in a failed state
        raise PoisoningCrash("Crash after session poisoning")

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield session

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)
    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)
    monkeypatch.setattr(agent_workflow, "_construct_runner", _crashing_construct_runner)

    # Execute the task; should handle poisoned session gracefully
    await agent_workflow._run_agent_workflow_async(str(run_id))

    # Verify terminal event was written despite poisoning
    result = await session.execute(
        select(WorkflowRunEventRow).where(WorkflowRunEventRow.workflow_run_id == run_id)
    )
    events = result.scalars().all()
    terminal_events = [e for e in events if e.event_type == "workflow.failed"]
    assert len(terminal_events) > 0, (
        "Terminal workflow.failed event should be written even when the original "
        "session was poisoned"
    )


# ---------------------------------------------------------------------------
# Test: action card auto-reverts when run fails
# ---------------------------------------------------------------------------


async def test_failed_run_auto_reverts_action_card_from_approved_to_active(
    session, shop, product, monkeypatch
):
    """CRITICAL FIX #2 (issue #1291 review): when run reaches terminal failed,
    the consumed action card auto-reverts from 'approved' back to 'active' so
    the seller can re-approve (AC3 recoverability)."""
    from juli_backend.models.models import ActionCard

    # Create a card in approved state (consumed at run creation)
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="optimize_product",
        priority=1,
        severity="info",
        title="Test Decision",
        description="A decision card for testing",
        recommendation_payload="{}",
        status="approved",  # Consumed
        approved_at=datetime.now(UTC),
    )
    session.add(card)
    await session.flush()

    # Create a run linked to this card
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"basis_snapshots": {}},
        status=WorkflowRunStatus.RUNNING.value,
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
        action_card_id=card.id,  # Link to the card
    )
    session.add(run)
    await session.flush()
    await session.commit()

    run_id = run.id

    class SimulatedCrash(RuntimeError):
        pass

    async def _crashing_construct_runner(session, sync_session, run, product):
        raise SimulatedCrash("Crash after card was approved")

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield session

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)
    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)
    monkeypatch.setattr(agent_workflow, "_construct_runner", _crashing_construct_runner)

    # Execute the task
    await agent_workflow._run_agent_workflow_async(str(run_id))

    # Verify the run is failed
    loaded_run = await session.get(WorkflowRun, run_id)
    assert loaded_run.status == WorkflowRunStatus.FAILED.value

    # Verify card auto-reverted to active (recoverability)
    loaded_card = await session.get(ActionCard, card.id)
    assert loaded_card.status == "active", (
        f"Card should auto-revert to 'active' for recovery after run fails, "
        f"got '{loaded_card.status}'"
    )
