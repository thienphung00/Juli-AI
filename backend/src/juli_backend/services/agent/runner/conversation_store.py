"""`ConversationStore` — the P-CS deferral seam (ADR-073 decision 5, issue
#1118 / AGT-W3A).

`ConversationStore` is the constructor-injected collaborator
`WorkflowRunner` (a later slice, #1119) will use to load/persist
`RunState` (`state.py`, alongside this module). This module ships the
protocol plus its one implementation for now: a JSONB-blob-backed store
that round-trips `RunState` through `workflow_runs.state` (the column
#1117 added).

A full P-CS phase (Redis and/or Postgres chat storage) later swaps the
*implementation* behind this protocol — the protocol itself, and whatever
depends on it, does not change (ADR-073 decision 5: "full Redis/Postgres
chat storage later swaps the implementation, not the runner"). Nothing in
the protocol below assumes a blob, a JSONB column, or SQL at all.

No `WorkflowRunner` here — that's #1119.

**Terminal `status`/`stop_reason`/`completed_at` persistence (issue #1178).**
`WorkflowRunner` always computed `status_for(stop_reason)` and returned it on
`RunResult` (`core.py`, #1119/#1120/#1172), but nothing on the real path ever
wrote it back to the `workflow_runs` row: `PersistingEventSink` only ever
inserts `workflow_run_events` rows (events are its whole job, deliberately no
status handling), and the Celery task bodies that call `runner.run`/
`runner.resume` discard the `RunResult` entirely
(`workers/tasks/agent_workflow.py`). A successful live run's row stayed
`status='running'` forever.

`persist` below is the fix's landing seam — not `EventSink`. `WorkflowRunner`
already calls `persist` once per iteration and at every terminal exit
(`core.py`'s own docstring: "this module has no direct database access of
its own (only `ConversationStore.load`/`persist`) ... writing them to the
row's actual columns is a later slice's job, exactly like
`status`/`stop_reason`"). `persist` grows two new keyword-only parameters,
`status`/`stop_reason`, both defaulting to `None` — a true no-op, so every
existing per-iteration call (which never passes them) behaves identically to
before. `JsonbConversationStore.persist` additionally stamps `completed_at`
when `status` lands on one of the four terminal members
(`COMPLETED`/`CANCELLED`/`TIMED_OUT`/`FAILED`), or `waiting_approval_since`
when it lands on `WAITING_APPROVAL` — the same column-flip idea
`workers/tasks/reaper.py::_ReaperEventSink.emit` already applies for the
reaper's own terminal events, reimplemented narrowly here rather than
imported (`workers/` -> `services/agent/runner` at depth 3 is forbidden by
`.importlinter.toml`'s depth-2 cross-package cap; the reaper's own module
docstring explains why it, in turn, cannot reach `PersistingEventSink`).

This does not conflict with `test_workflow_run_reaper.py::test_reap_never_
mutates_status_without_the_sink_performing_it`: that test pins a fact about
the *reaper's own reap loop* specifically -- `_reap_stale_running_and_queued`/
`_reap_expired_waiting_approval` must never assign `run.status` themselves,
only `_ReaperEventSink.emit` may. It says nothing about this module, which
the reaper never touches and which never touches the reaper — two distinct
authorities for two distinct callers (a run's own terminal transition vs. the
reaper's opportunistic sweep of rows abandoned by a dead worker), never one
reaching into the other's write path.

**`required_steps_completed` persistence (issue #1220, migration
`037_required_steps_completed`).** A third fact, orthogonal to
`status`/`stop_reason`: whether the active `Playbook`'s
`TerminationPolicy.required_steps` all completed successfully during the
run (ADR-073 decision 2's "did the job" outcome fact, feeding the
execution-quality metric — never a synthetic failure folded into
`stop_reason`). `persist` grows one more keyword-only parameter,
`required_steps_completed`, defaulting to `None` exactly like
`status`/`stop_reason` — the same true no-op for every non-terminal,
per-iteration call. `WorkflowRunner` (`core.py`) computes the value (via
`termination.py::required_steps_completed`, scanning the persisted
conversation window) at every terminal exit and passes it alongside
`status`/`stop_reason`; this module only ever forwards it onto the row.
The reaper's own terminal write (`_ReaperEventSink.emit`) computes and
writes the same fact independently, off `run.state` directly, for the
`worker_lost`/`confirmation_expired` paths this module never sees.

**`running_seconds_elapsed` column mirror (issue #1216).** The
`workflow_runs.running_seconds_elapsed` `Integer` column (#1117) existed
before this module did, but nothing on the live path ever wrote it --
`WorkflowRunner` only ever accumulated the authoritative float on
`RunState.running_seconds_elapsed`, never mirrored it onto the row.
`persist` grows a fourth keyword-only parameter, `running_seconds_elapsed`
(an `int`, already rounded -- the caller is expected to have called
`termination.running_seconds_column_value(state.running_seconds_elapsed)`
first; this module never rounds anything itself), defaulting to `None`.
Unlike `status`/`stop_reason`/`required_steps_completed` -- which are only
ever non-`None` at a terminal exit -- `WorkflowRunner` passes this one on
every `persist` call, terminal or not (issue #1216's own framing: "the
per-iteration persist and every terminal persist"), so the column tracks
the float at every write, not only at the end of a run. `None` stays a
true no-op regardless, so any caller that omits it (an older test double,
a future non-runner caller) leaves the column untouched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import WorkflowRun
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import (
    NON_TERMINAL_STATUSES,
    StopReason,
    WorkflowRunStatus,
)

# Derived, never a copied literal set: "terminal" is exactly every
# WorkflowRunStatus member that is neither pre-stop (`NON_TERMINAL_STATUSES`
# -- QUEUED/RUNNING) nor the one other non-terminal-but-active member,
# WAITING_APPROVAL. If `status.py` ever grows a new member, this set updates
# itself rather than silently staying stale.
_TERMINAL_STATUSES: frozenset[WorkflowRunStatus] = (
    frozenset(WorkflowRunStatus) - NON_TERMINAL_STATUSES - {WorkflowRunStatus.WAITING_APPROVAL}
)


@runtime_checkable
class ConversationStore(Protocol):
    """Load/persist a `RunState` for a given `workflow_runs` row.

    Two methods plus one optional terminal-transition seam on `persist`
    (issue #1178's `status`/`stop_reason` keyword-only parameters, both
    defaulting to `None`) — still the minimal surface `WorkflowRunner`
    needs. Keeping the protocol this narrow is what makes the P-CS seam
    real: an implementation only has to satisfy `load` and `persist`, so a
    later chat-store implementation is a straightforward swap, not a
    refactor of every caller.
    """

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        """Return the `RunState` currently persisted for this run."""
        ...

    async def persist(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        *,
        status: WorkflowRunStatus | None = None,
        stop_reason: StopReason | None = None,
        required_steps_completed: bool | None = None,
        running_seconds_elapsed: int | None = None,
    ) -> None:
        """Persist `state` as this run's current `RunState`.

        `status`/`stop_reason` are `None` (the default) for every
        non-terminal, per-iteration persist call — a true no-op, touching
        nothing about the row's status columns. When a caller passes a
        `status`, an implementation is expected to also stamp
        `completed_at` (terminal statuses) or `waiting_approval_since`
        (`WAITING_APPROVAL`) — see `JsonbConversationStore.persist` below.

        `required_steps_completed` (issue #1220) is a third, independent
        outcome fact — never `stop_reason` and never derived from it — set
        alongside `status`/`stop_reason` at the same call sites, `None`
        by the same no-op default. `WorkflowRunner` computes it off the
        active `Playbook`'s `TerminationPolicy.required_steps`; this
        protocol only ever forwards the caller-computed value.

        `running_seconds_elapsed` (issue #1216) is a fourth, independent
        value: the `workflow_runs.running_seconds_elapsed` `Integer`
        column's mirror of `RunState.running_seconds_elapsed`, already
        rounded by the caller (`termination.running_seconds_column_value`)
        — this protocol never rounds anything itself. `None` by the same
        no-op default, but unlike the three fields above, `WorkflowRunner`
        passes a value here on *every* `persist` call, not only terminal
        ones — the column must track the float at every write, not only
        at a run's end.
        """
        ...


class JsonbConversationStore:
    """`ConversationStore` backed by the `workflow_runs.state` JSONB blob
    (ADR-073 decision 5's stand-in implementation; ADR-073 decision 5:
    "the `workflow_runs.state` blob behind the `ConversationStore`
    protocol is the stand-in; no Redis chat storage, no
    conversations/messages tables").

    Constructor-injected `AsyncSession`, matching the shape of the
    repositories in `juli_backend.repositories.repos` (this module is not
    a repository itself — out of scope for this slice — but follows the
    same collaborator shape so a later promotion is a move, not a
    rewrite).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        run = await self._session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise NotFound(f"WorkflowRun {workflow_run_id} not found")
        return RunState.from_dict(run.state)

    async def persist(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        *,
        status: WorkflowRunStatus | None = None,
        stop_reason: StopReason | None = None,
        required_steps_completed: bool | None = None,
        running_seconds_elapsed: int | None = None,
    ) -> None:
        run = await self._session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise NotFound(f"WorkflowRun {workflow_run_id} not found")
        run.state = state.to_dict()
        if running_seconds_elapsed is not None:
            run.running_seconds_elapsed = running_seconds_elapsed
        if status is not None:
            run.status = status.value
            run.stop_reason = stop_reason.value if stop_reason is not None else None
            run.required_steps_completed = required_steps_completed
            now = datetime.now(UTC)
            if status in _TERMINAL_STATUSES:
                run.completed_at = now
            elif status is WorkflowRunStatus.WAITING_APPROVAL:
                run.waiting_approval_since = now
        await self._session.flush()
