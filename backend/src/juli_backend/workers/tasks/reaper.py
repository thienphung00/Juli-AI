"""The five-minute reaper — closes both run-abandonment holes through the
normal `EventSink` path (#1130, ADR-074 decision 4; ADR-073's `worker_lost`
amendment, 2026-08-12).

Two closures, both terminal `workflow.failed`-shaped events so a client with
an open SSE stream watches the run die honestly instead of finding it
silently gone on next poll:

1. **Stale `running`/`queued`** — no `workflow_run_events` row for this run
   in `wall_clock_timeout_s` (the playbook's `TerminationPolicy`) plus
   `STALE_RUN_SLACK_S`, and no live Celery task backing it -> `stop_reason:
   worker_lost` -> status `failed`.
2. **Expired `waiting_approval`** — past `approval_timeout_h` (4h) since
   `waiting_approval_since` -> `stop_reason: confirmation_expired` -> status
   `cancelled`. ADR-073 defined the policy; this is where it physically runs.

Neither closure ever emits `stop_reason: tool_error_unrecoverable`. ADR-074
d.4 is explicit about why: infrastructure death (`worker_lost`) and
task-logic failure (`tool_error_unrecoverable`) are different facts feeding
the execution-quality metric, and conflating them corrupts it. This module
never constructs `StopReason.TOOL_ERROR_UNRECOVERABLE` --
`test_workflow_run_reaper.py::test_reaper_module_never_references_tool_error_unrecoverable`
walks this file's source at test time to pin that.

**Why a local `_ReaperEventSink` instead of importing P8-3's
`PersistingEventSink`:** that sink (the runner's own insert-commit-then-
publish implementation) lives in `services/agent/events/`, which this
slice's write paths forbid touching, and it has not landed on this stack at
authoring time regardless. `_ReaperEventSink` below satisfies the same
structural `EventSink` protocol
(`services/agent/events/sink.py::EventSink`, `isinstance`-checkable per
ADR-074 decision 3) and reproduces the same shape narrowly for the one
event type the reaper ever emits (`workflow.failed`): INSERT the
`workflow_run_events` row, flip `workflow_runs.status`/`stop_reason`/
`completed_at` to match, commit once. No side-channel `UPDATE` ever runs
without the event row landing first in the same commit. No Redis publish
step exists here -- that half of the real sink is P8-3's, and Redis is
disposable-by-design (ADR-074 decision 1): a client that missed the publish
still gets this event on replay from Postgres, the authoritative source.

**Playbook resolution.** `workflow_runs` carries no `workflow_key`/playbook
column (#1117 shipped none, and this slice adds no migration -- see the PR
body if a column looks missing). Optimize Product v1
(`services/agent/playbooks/optimize_product.py`) is the only playbook
registered in this repo today, so every row is scored against its
`TerminationPolicy` unconditionally. A second playbook needs its own
follow-up to resolve per-run policy, not a silent broadening of this
constant.

**Imports stay at the public `services.agent` root.** `workers/` is a
different top-level package from `services/`, so the MMU-2 import-boundary
contract (`.importlinter.toml`, `max_cross_package_depth=2`,
`agent-runtime/scripts/ci/check_import_boundaries.py`) caps how deep this
module may reach into it: `juli_backend.services.agent` (depth 2) is the
deepest allowed target, exactly the seam `workers/tasks/agent_workflow.py`
already uses for `WorkflowRunner` (`from juli_backend.services.agent import
runner`). This module does the same for `runner` (re-exports
`StopReason`/`WorkflowRunStatus`, `services/agent/runner/__init__.py`),
`events` (re-exports `WorkflowFailedEvent`/`WorkflowFailedPayload`,
`services/agent/events/__init__.py`), and `playbooks` (re-exports
`OPTIMIZE_PRODUCT_TERMINATION_POLICY`, `services/agent/playbooks/__init__.py`
-- widened by this slice to close exactly this gap; see that module's
docstring). Termination values are READ off `OPTIMIZE_PRODUCT_TERMINATION_POLICY`
here, never redefined as a local literal -- the same discipline the runner
and #1120's in-loop termination follow, per this phase's architect lock: a
literal `300` or `4` reproducing one of the policy's fields anywhere else is
a defect, not a style choice, because it lets the reaper's threshold and the
runner's threshold drift apart silently. `reap_workflow_runs`'s `policy=`
parameter defaults to the real object but is injectable, so
`test_workflow_run_reaper.py` can prove the reaper's thresholds move with an
arbitrary policy rather than merely matching one pinned pair of numbers.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.models.models import WorkflowRun
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent import events as _agent_events
from juli_backend.services.agent import playbooks as _agent_playbooks
from juli_backend.services.agent import runner as _agent_runner
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

# Re-bound from the depth-2 facade imports above -- see the module
# docstring's "Imports stay at the public services.agent root" note.
StopReason = _agent_runner.StopReason
WorkflowRunStatus = _agent_runner.WorkflowRunStatus
WorkflowFailedEvent = _agent_events.WorkflowFailedEvent
WorkflowFailedPayload = _agent_events.WorkflowFailedPayload
TerminationPolicy = _agent_playbooks.TerminationPolicy

# The default policy every workflow_runs row is scored against -- see the
# module docstring's "Playbook resolution" note. Termination values are read
# off this object's fields wherever needed below; `reap_workflow_runs`'s
# `policy=` parameter can override it (tests do, to prove the reaper's
# thresholds genuinely move with the policy rather than a copied constant).
_DEFAULT_TERMINATION_POLICY = _agent_playbooks.OPTIMIZE_PRODUCT_TERMINATION_POLICY

# Judgment call -- issue #1130 does not pin a number. Slack margin added on
# top of the policy's wall_clock_timeout_s before a running/queued run is
# considered abandoned, sized to one beat interval: a run whose last event
# landed just before a scheduled reaper tick must survive that tick on
# scheduling jitter alone. Only silence spanning two beat cycles is reaped.
STALE_RUN_SLACK_S = 300

_AGENT_WORKFLOW_TASK_NAMES = frozenset(
    {"juli_backend.run_agent_workflow", "juli_backend.resume_agent_workflow"}
)

# Injectable liveness probe: given a workflow_run_id, is there a live Celery
# task backing it? Real signature has no notion of "why" -- callers decide.
TaskLivenessCheck = Callable[[uuid.UUID], bool]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    """Normalize a DB-read datetime to aware UTC before comparing to `now`.

    `workflow_runs.created_at`/`updated_at` are plain (naive) `DateTime`
    columns -- no explicit `DateTime(timezone=True)`, unlike
    `started_at`/`completed_at`/`waiting_approval_since` and
    `workflow_run_events.timestamp`, which are already timezone-aware.
    Comparing a naive and an aware datetime raises `TypeError`, so every
    timestamp this module reads passes through here first. Values are
    seeded as naive UTC by every writer in this codebase (never a local
    timezone), so attaching UTC to a naive value is a no-op restoring
    information, not a guess.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _default_has_live_task(run_id: uuid.UUID) -> bool:
    """Best-effort Celery liveness probe via `control.inspect()`.

    Checks active, reserved, and scheduled tasks across every responding
    worker for `run_agent_workflow`/`resume_agent_workflow` carrying this
    `run_id`, matched either positionally (`args[0]`, how every caller in
    this repo enqueues today) or by keyword (`kwargs["run_id"]`) -- no
    caller enqueues by keyword yet, but matching positional-only would read
    a future `enqueue(run_id=...)` call as "no live task" and expose a
    genuinely live run to a false reap, which is exactly the failure
    direction this reaper exists to prevent. `workflow_runs` stores no
    Celery task id (no migration in this slice), so this is the only
    liveness signal available short of one.

    Fails SAFE: any error talking to the broker (unreachable, timeout,
    unsupported transport) returns True -- "assume a live task exists" --
    never False. The no-false-kill guarantee this reaper exists to provide
    would be worthless if a flaky broker probe silently became "no live
    task, reap it"; a probe failure just skips this run for this tick, and
    the next 5-minute tick tries again.
    """
    run_id_str = str(run_id)
    try:
        inspector = celery_app.control.inspect()
        if inspector is None:
            return False
        for method_name in ("active", "reserved", "scheduled"):
            method = getattr(inspector, method_name, None)
            if method is None:
                continue
            found = method() or {}
            for tasks in found.values():
                for task in tasks or ():
                    if not isinstance(task, dict):
                        continue
                    request = task.get("request") if isinstance(task.get("request"), dict) else task
                    name = request.get("name") or task.get("name")
                    if name not in _AGENT_WORKFLOW_TASK_NAMES:
                        continue
                    args = request.get("args") or task.get("args") or []
                    kwargs = request.get("kwargs") or task.get("kwargs") or {}
                    if not isinstance(kwargs, dict):
                        kwargs = {}
                    matches_positional = bool(args) and str(args[0]) == run_id_str
                    matches_keyword = "run_id" in kwargs and str(kwargs["run_id"]) == run_id_str
                    if matches_positional or matches_keyword:
                        return True
        return False
    except Exception:
        logger.warning(
            "reaper_liveness_probe_failed",
            extra={"run_id": str(run_id)},
            exc_info=True,
        )
        return True


class _ReaperEventSink:
    """Local `EventSink`-protocol implementation, scoped to `workflow.failed`
    only -- see the module docstring for why this exists instead of
    importing P8-3's `PersistingEventSink`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def emit(self, event: WorkflowFailedEvent) -> None:
        run = await self._session.get(WorkflowRun, event.workflow_run_id)
        if run is None:
            raise LookupError(f"workflow_runs row not found for run_id={event.workflow_run_id}")

        row = WorkflowRunEventRow(
            id=uuid.uuid4(),
            workflow_run_id=event.workflow_run_id,
            sequence_number=event.sequence_number,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=event.payload.model_dump(mode="json"),
            v=event.v,
        )
        self._session.add(row)

        run.status = event.payload.status.value
        run.stop_reason = event.payload.stop_reason.value
        run.completed_at = event.timestamp

        await self._session.commit()


@dataclass(frozen=True)
class ReapResult:
    """Which runs each closure reaped this tick -- logged, not asserted on
    by production code."""

    stale_runs_reaped: tuple[uuid.UUID, ...]
    expired_approvals_reaped: tuple[uuid.UUID, ...]


async def _next_sequence_number(session: AsyncSession, run_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(WorkflowRunEventRow.sequence_number), -1)).where(
            WorkflowRunEventRow.workflow_run_id == run_id
        )
    )
    return result.scalar_one() + 1


async def _last_activity_at(session: AsyncSession, run: WorkflowRun) -> datetime:
    """Most recent liveness signal for `run`: the latest event timestamp if
    any event has ever been emitted, else `started_at`, else `created_at` --
    the run's own insertion moment for a `queued` run that never started."""
    result = await session.execute(
        select(func.max(WorkflowRunEventRow.timestamp)).where(
            WorkflowRunEventRow.workflow_run_id == run.id
        )
    )
    last_event_ts = result.scalar_one_or_none()
    if last_event_ts is not None:
        return _as_aware_utc(last_event_ts)
    if run.started_at is not None:
        return _as_aware_utc(run.started_at)
    return _as_aware_utc(run.created_at)


async def _emit_terminal_event(
    session: AsyncSession,
    sink: object,
    run: WorkflowRun,
    *,
    stop_reason: StopReason,
    status: WorkflowRunStatus,
    now: datetime,
) -> None:
    seq = await _next_sequence_number(session, run.id)
    event = WorkflowFailedEvent(
        workflow_run_id=run.id,
        sequence_number=seq,
        event_type="workflow.failed",
        timestamp=now,
        payload=WorkflowFailedPayload(status=status, stop_reason=stop_reason),
        v=1,
    )
    await sink.emit(event)


async def _reap_stale_running_and_queued(
    session: AsyncSession,
    sink: object,
    now: datetime,
    has_live_task: TaskLivenessCheck,
    policy: TerminationPolicy,
) -> tuple[uuid.UUID, ...]:
    active_statuses = (WorkflowRunStatus.QUEUED.value, WorkflowRunStatus.RUNNING.value)
    stmt = select(WorkflowRun).where(WorkflowRun.status.in_(active_statuses))
    result = await session.execute(stmt)
    runs = result.scalars().all()
    threshold_s = policy.wall_clock_timeout_s + STALE_RUN_SLACK_S

    reaped: list[uuid.UUID] = []
    for run in runs:
        last_activity = await _last_activity_at(session, run)
        elapsed_s = (now - last_activity).total_seconds()
        if elapsed_s < threshold_s:
            continue
        if has_live_task(run.id):
            continue
        await _emit_terminal_event(
            session,
            sink,
            run,
            stop_reason=StopReason.WORKER_LOST,
            status=WorkflowRunStatus.FAILED,
            now=now,
        )
        reaped.append(run.id)
    return tuple(reaped)


async def _reap_expired_waiting_approval(
    session: AsyncSession,
    sink: object,
    now: datetime,
    policy: TerminationPolicy,
) -> tuple[uuid.UUID, ...]:
    result = await session.execute(
        select(WorkflowRun).where(WorkflowRun.status == WorkflowRunStatus.WAITING_APPROVAL.value)
    )
    runs = result.scalars().all()
    threshold_s = policy.approval_timeout_h * 3600

    reaped: list[uuid.UUID] = []
    for run in runs:
        if run.waiting_approval_since is None:
            continue
        elapsed_s = (now - _as_aware_utc(run.waiting_approval_since)).total_seconds()
        if elapsed_s < threshold_s:
            continue
        await _emit_terminal_event(
            session,
            sink,
            run,
            stop_reason=StopReason.CONFIRMATION_EXPIRED,
            status=WorkflowRunStatus.CANCELLED,
            now=now,
        )
        reaped.append(run.id)
    return tuple(reaped)


async def reap_workflow_runs(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    has_live_task: TaskLivenessCheck | None = None,
    sink: object | None = None,
    policy: TerminationPolicy | None = None,
) -> ReapResult:
    """The reaper's core logic -- the seam every test in
    `test_workflow_run_reaper.py` drives directly. `now` and `has_live_task`
    are injectable so boundary behaviour is deterministic (no real sleeping,
    no wall-clock flakiness); `sink` is injectable so tests can prove the
    reaper drives the `EventSink` path rather than writing
    `workflow_runs.status` itself; `policy` is injectable so tests can prove
    the reaper's thresholds are genuinely read off a `TerminationPolicy`
    object rather than a copied constant -- defaults to the real
    `OPTIMIZE_PRODUCT_TERMINATION_POLICY`, the only playbook registered in
    this repo today (see the module docstring's "Playbook resolution" note).
    """
    now = now if now is not None else _utcnow()
    has_live_task = has_live_task if has_live_task is not None else _default_has_live_task
    sink = sink if sink is not None else _ReaperEventSink(session)
    policy = policy if policy is not None else _DEFAULT_TERMINATION_POLICY

    stale = await _reap_stale_running_and_queued(session, sink, now, has_live_task, policy)
    expired = await _reap_expired_waiting_approval(session, sink, now, policy)
    return ReapResult(stale_runs_reaped=stale, expired_approvals_reaped=expired)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _reap_abandoned_workflow_runs_async() -> ReapResult:
    factory = _ensure_session_factory()
    async with factory() as session:
        result = await reap_workflow_runs(session)
        logger.info(
            "reap_abandoned_workflow_runs_complete",
            extra={
                "stale_runs_reaped": len(result.stale_runs_reaped),
                "expired_approvals_reaped": len(result.expired_approvals_reaped),
            },
        )
        return result


@celery_app.task(name="juli_backend.reap_abandoned_workflow_runs")
def reap_abandoned_workflow_runs() -> None:
    """Celery Beat periodic task, every 5 minutes (ADR-074 decision 4).

    Thin wrapper only: opens a session, delegates to `reap_workflow_runs`
    with production defaults (real clock, real Celery liveness probe, the
    real `_ReaperEventSink`), logs a summary. No loop/branch logic lives
    here -- both closures' decision logic lives in
    `_reap_stale_running_and_queued`/`_reap_expired_waiting_approval`.
    """
    asyncio.run(_reap_abandoned_workflow_runs_async())
