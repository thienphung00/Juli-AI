"""Celery task shells for agent workflow execution (ADR-074 decision 4,
issue #1129 -- reconciled against the real `WorkflowRunner` by issue #1145).

Thin shells only (ADR-073 decision 1's rejected alternative is exactly "loop
inline in the Celery task"): **load context -> construct runner -> run**. No
loop or state-machine logic lives in this module -- that lives in
`WorkflowRunner` (`services/agent/runner/core.py`, #1119 / W3-A).

**What #1145 changed.** #1129 authored this module against `_RunnerProtocol`,
a placeholder shaped like `run(self)` / `resume(self, tool_call_id,
decision)`, because `WorkflowRunner` did not exist yet on the stack this
module was authored on. It has since landed (#1119, #1123) with a different,
real signature -- constructor-injected with keyword-only collaborators,
`run(workflow_run_id, *, product_ref)`, `resume(workflow_run_id, *, approved:
bool)`. `_construct_runner` below now builds the real thing and both task
bodies call the real methods; `_RunnerProtocol` is deleted (its own
docstring said it should be, once W3-A landed -- not graduated).

**`tool_call_id` threading + ledger/guard reachability (also #1145).**
`_construct_runner` is also where `ToolExecutionLedger` (`runner/ledger.py`,
#1121) and `ConcurrencyGuard` (`runner/concurrency.py`, #1122) get
constructed and handed to a `ProductToolExecutor` -- both were implemented,
reviewed and fully unit-tested, but structurally unreachable from any real
run before this, because nothing outside a test ever constructed a
`ProductToolExecutor` at all. `core.py`'s own #1145 change (threading
`block.call_id`/the pending call's `call_id` into
`execute(..., tool_call_id=...)`) is what makes the ledger's routing branch
reachable now that a caller here supplies `ledger`/`workflow_run_id` too.

**What this module can now build for real (issue #1173, closing the gap
#1145 flagged above as follow-up work).** `.importlinter.toml`'s
cross-package depth cap (`max_cross_package_depth = 2`) limits every import
this module makes into `services.agent` to that package's own public
depth-2 facade (`juli_backend.services.agent.<child>`) -- and `workers`'
`[allowed_edges]` row does not list `integrations` at all, so this module
can never import `juli_backend.integrations.tiktok` at any depth. That edge
is structural and permanent; it is also not actually needed here, since
`services` -> `integrations` (and `services` -> `core`) *are* allowed edges
-- `services/agent/composition.py` builds `read_resources`/`write_resources`
from inside `services/agent` for exactly this reason (below), the same way
it reaches the LLM adapter and tool registry.

The five named seams below are not blocked by a missing `integrations` edge
at all -- `workers` -> `services` is an allowed edge; only the depth-2 cap
on that edge stood in the way for two of them, and depth-2 caps apply only
*across* a top-level package boundary (`check_import_boundaries.py
::check_import`'s own `importer_package == target_package: return None`
short-circuit). `services/agent/composition.py` (new, #1173) is a
same-top-level-package (`services`) module that reaches every genuinely
deep collaborator directly, unrestricted, and exposes plain functions:

- `build_llm_service()` -- the real production LLM adapter
  (`services.agent.llm.openai_adapter.OpenAIResponsesAdapter`), still
  deliberately *not* re-exported at `services.agent.llm`'s own public facade
  (that package's `MODULE.md`: "so nothing depends on a concrete adapter by
  accident") -- `composition.py` is the one sanctioned place that concrete
  dependency is allowed to exist, reached the same depth-2-facade way
  `_default_playbook` below reaches `services.agent.playbooks`. Fails closed
  via `resolve_llm_config()`'s `require_env("OPENAI_API_KEY")` before the
  adapter is ever constructed.
- `build_product_tool_registry()` -- the real, populated Optimize Product
  `ToolRegistry` (`services.agent.tools.product.register_product_read_tools`
  / `...product_write.register_product_write_tools`), one level below
  `services.agent.tools`'s own public facade (which re-exports only the
  empty `ToolRegistry` class itself). No credentials needed to build this --
  it only registers `ToolSpec`s, never resolves marketplace access.
- `build_read_resources(session)` / `build_write_resources(session)`
  (review round 1 rework) -- the real ADR-069 guarded `ProductionReadResources`
  / `SandboxWriteResources` bundles a run's tool calls actually need, built
  the same way `workers/services/polling/orchestrate.py` (production-read)
  and `services/execution/sandbox_guard.py` (sandbox-write, reused outright)
  already do -- see `composition.py`'s own "Marketplace resources" docstring
  section for the full rationale and the exact compliant import path used to
  reach `core.security`'s credential resolvers without adding a new
  deep-import baseline entry.

The third and fourth seams, `_default_playbook` and (implicitly, via
`composition.py`) nothing else, needed no new composition helper for the
playbook: `OPTIMIZE_PRODUCT_PLAYBOOK` (`services.agent.playbooks
.optimize_product`) is *already* re-exported at `services.agent.playbooks`'s
own depth-2 public facade (that package's own docstring) -- exactly the same
`from juli_backend.services.agent import <child> as <alias>` idiom
`api/routes/agent_runs.py::_resolve_optimize_product_prompt_pin` already
uses for the same package. `_default_llm_service`/`_default_tool_registry`/
`_default_read_resources`/`_default_write_resources` below all reach
`composition.py` the identical way.

**`_construct_runner` is now `async def` (review round 1 rework).**
Resolving real TikTok credentials is inherently a database read
(`resolve_production_read_credential`/`resolve_sandbox_write_credential`,
both `async`) -- `_construct_runner` already receives the open `session`
(`AsyncSession`) `_run_agent_workflow_async`/`_resume_agent_workflow_async`
hold, so awaiting `_default_read_resources(session)`/
`_default_write_resources(session)` inside it, and `await`-ing the call at
both call sites below, is the natural seam; no second session or sync
credential-resolution path was invented for this. This adds no branch/loop
logic to either task body (`test_agent_workflow_task_wiring.py`'s
`TestThinShellBodies` AST check is unaffected by an added `await`).

**Prompt-version/sha256 stamping (ADR-072).** Supplying the real playbook
here is also what makes stamping actually correct: `WorkflowRunner.run`
(`services/agent/runner/core.py`) already calls `compose(self._playbook
.workflow_key, self._playbook.version)` / `prompt_version(...)` /
`prompt_sha256(...)` itself and includes `prompt_version` on the
`WorkflowStartedEvent` payload it emits -- that seam already existed and
needed no change here, it was simply unreachable while `_default_playbook`
raised. The separate `workflow_runs.prompt_version`/`.prompt_sha256`
*columns* are stamped at run-creation time by `api/routes/agent_runs.py`'s
`_resolve_optimize_product_prompt_pin` (issue #1145 territory, unchanged) --
`WorkflowRunner` itself never writes those columns back, by design (that
module's own docstring: "no direct database access here").

None of this changes what #1145 already proved: with the three seams
overridden for isolation (as `tests/unit/test_agent_workflow_task_wiring.py`
still does for its non-composition-focused tests), this module constructs a
real `WorkflowRunner` with its real keyword-only signature; separately
(`tests/unit/test_agent_workflow_ledger_guard_reachability.py`), a WRITE
call dispatched through a real `WorkflowRunner` genuinely reaches both
`ToolExecutionLedger` and `ConcurrencyGuard`. What #1173 adds is that the
*default*, non-overridden path -- a real enqueued run -- now constructs a
real `LLMService`, `ToolRegistry`, `Playbook`, and (review round 1 rework)
real guarded `ProductionReadResources`/`SandboxWriteResources` too, not just
a real `WorkflowRunner` shell around seams that always raised or left the
tool executor's marketplace access unset.

Both tasks stay `acks_late=True, max_retries=1` (ADR-074 decision 4): a
worker crash redelivers the task once, and the retried worker reconstructs
entirely from `workflow_runs.state` -- `_load_context` always re-reads the
row fresh, so a redelivered task naturally resumes from wherever the row
currently is rather than restarting.

**Enqueue + cancel signal (issue #1145's remaining scope, closed in the same
change as the docstring above).** `POST /v1/demo/runs` (`api/routes/
agent_runs.py`) now creates the `workflow_runs` row and calls
`run_agent_workflow.delay(str(run_id))` -- Gap 2 of #1145, previously
nothing in production code ever enqueued either task. `_construct_runner`
also now wires a `cancel_check` (`_make_cancel_check` below) that reads
`workflow_runs.cancel_requested` fresh from the database on every
`WorkflowRunner` checkpoint poll -- Gap 3, fed by `POST /v1/demo/runs/{id}/
cancel` writing that column from a different process. As of #1173 (plus its
review-round-1 rework above), the enqueue path and the five composition
seams together mean a real enqueued run genuinely constructs every
collaborator `WorkflowRunner`/`ProductToolExecutor` need -- the one thing
still not exercised anywhere in this repo's test suite is an actual live
OpenAI completion and a live TikTok API round trip, which stay #1124's HITL
live smokes by design (no live call is ever made from a unit or integration
test in this module's own suite).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.models.models import Product, WorkflowRun
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent import events as events_module
from juli_backend.services.agent import runner as runner_module
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

# Re-bound from depth-2 facade imports for crash handling
StopReason = runner_module.StopReason
WorkflowRunStatus = runner_module.WorkflowRunStatus
WorkflowFailedEvent = events_module.WorkflowFailedEvent
WorkflowFailedPayload = events_module.WorkflowFailedPayload


class RunnerCompositionUnavailableError(RuntimeError):
    """Retired as of issue #1173 -- previously raised by one of the
    `_default_*` seams below when the real collaborator it stood in for was
    not reachable from `workers/` under the import boundary (see git history
    on this module for the pre-#1173 docstring). That failure mode no longer
    occurs: `services/agent/composition.py` (new, #1173) closes the actual
    reachability gap, so none of the seams below can fail for "unreachable"
    reasons anymore. The class is kept, unused, rather than deleted, only
    because deleting a public exception type is itself a breaking change
    worth its own deliberate commit -- nothing in this module raises it.
    The seams that can still fail closed (`_default_llm_service` on a
    missing `OPENAI_API_KEY`; `_default_read_resources`/
    `_default_write_resources`, added in review-round-1 rework, on a
    missing `TIKTOK_APP_KEY`/`TIKTOK_APP_SECRET` or an unprovisioned
    credential row) now raise the plain `RuntimeError`/`NotFound` the
    underlying `require_env`/repository call itself produces, naming the
    missing prerequisite precisely -- wrapping that in this class would
    misrepresent a present, working collaborator with an absent credential
    as a structural reachability problem, which it is not."""


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


@contextlib.contextmanager
def _sync_ledger_session() -> Iterator[Session]:
    """A throwaway sync `Session` for `ToolExecutionLedger`
    (`ledger.py`'s own docstring: "cheap and stateless beyond the injected
    Session" -- a fresh engine per task invocation is deliberate, matching
    that module's own scoping, not an oversight).

    Routes through `workers.tasks.database.get_sync_database_url` rather
    than reading `DATABASE_URL` here directly -- `test_worker_database_url
    .py`'s AC5 keeps `os.getenv("DATABASE_URL", ...)` to that one file as
    the sole choke point across `workers/tasks/`.

    A context manager (#1145 reconciliation) so the task shells can bind it
    in their `async with` header instead of a `try/finally` body: #1129's
    `test_task_body_has_no_loop_or_branch_logic` forbids `ast.Try` in a task
    body, and that guard is worth keeping intact. Disposing the engine on
    exit also closes the per-invocation connection pool, which the previous
    bare-`Session` form leaked once per task run.
    """
    from juli_backend.workers.tasks.database import get_sync_database_url

    engine = create_sync_engine(get_sync_database_url())
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


async def _load_context(session: AsyncSession, run_id: uuid.UUID) -> tuple[WorkflowRun, Product]:
    """Load the current `workflow_runs` row plus its bound `products` row --
    the run-state blob (I6) and the product identity `ProductToolExecutor`
    binds at construction. Reads fresh on every call, including a
    redelivered retry: no task-local cache anywhere in this module."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise LookupError(f"workflow_runs row not found for run_id={run_id}")
    product = await session.get(Product, run.product_id)
    if product is None:
        raise LookupError(f"products row not found for product_id={run.product_id}")
    return run, product


def _default_llm_service():
    """The real ADR-071 `LLMService` (issue #1173) -- `composition.py`'s
    `build_llm_service()`, reached via the depth-2 facade
    `juli_backend.services.agent` (see module docstring). Fails closed with
    a precise `RuntimeError` naming `OPENAI_API_KEY` when that variable is
    absent or blank, before any adapter is constructed -- never a silent
    fake."""
    from juli_backend.services.agent import composition as composition_module

    return composition_module.build_llm_service()


def _default_tool_registry():
    """The real, populated ADR-069 `ToolRegistry` (issue #1173) --
    `composition.py`'s `build_product_tool_registry()`, reached the same
    depth-2-facade way as `_default_llm_service` above."""
    from juli_backend.services.agent import composition as composition_module

    return composition_module.build_product_tool_registry()


def _default_playbook():
    """The real, concrete `OPTIMIZE_PRODUCT_PLAYBOOK` (issue #1173) --
    already re-exported at `services.agent.playbooks`'s own depth-2 public
    facade, so no `composition.py` helper is needed for this one (see module
    docstring)."""
    from juli_backend.services.agent import playbooks as playbooks_module

    return playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK


async def _default_read_resources(session: AsyncSession):
    """The real ADR-069 guarded `ProductionReadResources` (issue #1173
    review-round-1 rework) -- `composition.py`'s `build_read_resources`,
    reached the same depth-2-facade way as `_default_llm_service` above.
    `async` because credential resolution is a database read; awaited by
    `_construct_runner` below. Fails closed with a precise `RuntimeError`
    naming `TIKTOK_APP_KEY`/`TIKTOK_APP_SECRET` when either is absent, or
    `NotFound` when no Fujiwa production-read credential row is provisioned
    yet -- never a silent fake, and never `None` (unlike the pre-rework
    `ProductToolExecutor` this replaced, which left `read_resources` unset
    and crashed uncaught on the first tool call instead)."""
    from juli_backend.services.agent import composition as composition_module

    return await composition_module.build_read_resources(session)


async def _default_write_resources(session: AsyncSession):
    """The real ADR-069 guarded `SandboxWriteResources` (issue #1173
    review-round-1 rework) -- `composition.py`'s `build_write_resources`,
    reached the same depth-2-facade way as `_default_read_resources` above.
    Fails closed the same two ways."""
    from juli_backend.services.agent import composition as composition_module

    return await composition_module.build_write_resources(session)


def _make_cancel_check(sync_session: Session, run_id: uuid.UUID) -> Callable[[], bool]:
    """Build the `cancel_check` `WorkflowRunner` polls at every checkpoint
    (issue #1145 Gap 3) -- reads `workflow_runs.cancel_requested` fresh from
    the database on every call, never a cached snapshot.

    `POST /v1/demo/runs/{id}/cancel` (`api/routes/agent_runs.py`) writes
    this column from the API process; this callable is read from a worker
    process, on the same `sync_session` this task shell binds for the
    ledger, across however many checkpoint polls one `run()`/`resume()`
    call makes. A `Session.get(WorkflowRun, run_id)`-backed check would
    return the identity-map-cached row after its first load and never see
    the API's write again for the rest of this session's lifetime --
    exactly the trap this avoids. Selecting a single column (never the full
    mapped entity) is what keeps this a real query on every call instead of
    an identity-map hit: SQLAlchemy's identity map only caches whole-entity
    loads by primary key, not column-only `select()`s.
    """

    def _cancel_check() -> bool:
        value = sync_session.execute(
            select(WorkflowRun.cancel_requested).where(WorkflowRun.id == run_id)
        ).scalar_one()
        return bool(value)

    return _cancel_check


class _NullEventPublisher:
    """A structural `EventPublisher` (`services.agent.events.EventPublisher`
    -- `async def publish(self, channel, message)`) that no-ops. Bound to
    `PersistingEventSink` when `REDIS_URL` is unset (`_resolve_event_
    publisher` below).

    `PersistingEventSink`'s constructor requires a non-`None` `publisher` --
    unlike `api/routes/agent_runs.py`'s subscriber side, where `None` is
    itself a valid "no live tier configured" answer the route branches on,
    there is no such branch inside the sink: it always calls `self.
    _publisher.publish(...)` after its INSERT commits. `PersistingEventSink
    .emit`'s own contract already treats a publish failure as logged and
    swallowed -- correctness never depends on it (ADR-074 decision 3) -- so
    a real `redis.asyncio.Redis` pointed at an unreachable URL would degrade
    exactly the same way this does. This class only avoids deliberately
    dialling out to nothing when no `REDIS_URL` was ever configured at all.
    """

    async def publish(self, channel: str, message: str) -> None:
        return None


def _resolve_event_publisher():
    """The `EventPublisher` `_construct_runner` hands to `PersistingEventSink`
    (ADR-074 decision 3). Mirrors `api/routes/agent_runs.py::
    _resolve_redis_event_subscriber`'s `REDIS_URL` resolution and `redis
    .from_url(url, decode_responses=True)` construction -- the codebase's
    one existing Redis pub/sub wiring idiom for this event-streaming
    feature, reused here rather than invented fresh. Diverges from that
    sibling only where the two protocols diverge: the subscriber side
    returns `None` for "no live tier" and the caller (the SSE route)
    branches on that explicitly; `PersistingEventSink` has no such branch,
    so an unset `REDIS_URL` here returns `_NullEventPublisher` instead --
    Redis absence must not threaten correctness (ADR-074 decision 3), and
    the `agent_broker_guard` fail-closed check that gates the Celery broker
    itself is a separate, orthogonal concern (`AGENT_WORKFLOWS_ENABLED`
    governs the *queue*, never whether the event-relay tier exists).
    """
    url = (os.getenv("REDIS_URL", "") or "").strip()
    if not url:
        return _NullEventPublisher()

    import redis.asyncio as redis

    return redis.from_url(url, decode_responses=True)


async def _construct_runner(
    session: AsyncSession,
    sync_session: Session,
    run: WorkflowRun,
    product: Product,
):
    """Construct the real `WorkflowRunner` for `run` -- the one-line wiring
    point issue #1145 restores (ADR-073 decision 1). Builds a
    `ToolExecutionLedger` and a `ConcurrencyGuard` and hands both to a
    `ProductToolExecutor`, so a WRITE this run dispatches genuinely reaches
    both (see module docstring). `read_resources`/`write_resources` are now
    the real guarded `ProductionReadResources`/`SandboxWriteResources`
    (issue #1173 review-round-1 rework) -- `_default_read_resources`/
    `_default_write_resources` above, `await`-ed here because credential
    resolution is a database read against the same `session` this function
    already receives. This function is `async def` for exactly that reason
    (it was plain `def` before this rework); both call sites below now
    `await` it.

    `event_sink` is the real `PersistingEventSink` (ADR-074 decision 3,
    issue #1171) -- INSERT + commit to `workflow_run_events` first, then
    best-effort Redis publish (`_resolve_event_publisher` above). Built from
    `_ensure_session_factory()`, the same memoized-per-URL session factory
    `_run_agent_workflow_async`/`_resume_agent_workflow_async` already call
    for their own `session` (`database/database.py::
    ensure_worker_session_factory` caches by URL, so this is not a second
    engine/connection pool) -- `PersistingEventSink` opens its own fresh
    session per `emit` regardless of the caller's own transaction, matching
    its own module docstring's "a fresh session per emit" contract, never
    the `session` this function also threads into `JsonbConversationStore`.
    Unit/test paths keep injecting fakes the same way they always have: by
    monkeypatching `services.agent.runner.WorkflowRunner` itself (this
    module's own `test_agent_workflow_task_wiring.py`), and now also the
    two new `_default_read_resources`/`_default_write_resources` seams the
    same way the other three are already monkeypatched, not by adding
    parameters here -- `_construct_runner`'s signature is unchanged, only
    what it builds by default (and its `async`-ness) is.
    """
    from juli_backend.services.agent import composition as composition_module
    from juli_backend.services.agent import events as events_module
    from juli_backend.services.agent import runner as runner_module

    registry = _default_tool_registry()
    ledger = runner_module.ToolExecutionLedger(sync_session, shop_id=run.shop_id)
    concurrency_guard = runner_module.ConcurrencyGuard(
        basis_snapshot=run.state.get("basis_snapshots", {})
    )
    read_resources = await _default_read_resources(session)
    write_resources = await _default_write_resources(session)
    tool_executor = runner_module.ProductToolExecutor(
        registry=registry,
        product_id=product.tiktok_product_id,
        read_resources=read_resources,
        write_resources=write_resources,
        ledger=ledger,
        workflow_run_id=run.id,
        concurrency_guard=concurrency_guard,
        # #1208: without this the inspect step reports inspected=False and the
        # run still completes -- degraded, never broken.
        image_inspector=composition_module.build_image_inspector(),
    )
    conversation_store = runner_module.JsonbConversationStore(session)
    event_sink = events_module.PersistingEventSink(
        _ensure_session_factory(), _resolve_event_publisher()
    )

    return runner_module.WorkflowRunner(
        llm_service=_default_llm_service(),
        tool_executor=tool_executor,
        event_sink=event_sink,
        conversation_store=conversation_store,
        registry=registry,
        playbook=_default_playbook(),
        cancel_check=_make_cancel_check(sync_session, run.id),
    )


async def _next_sequence_number(session: AsyncSession, run_id: uuid.UUID) -> int:
    """Get the next sequence number for an event on this run.

    Used when emitting a terminal event after a crash. Mirrors the reaper's
    own logic (reaper.py::_next_sequence_number)."""
    result = await session.execute(
        select(func.coalesce(func.max(WorkflowRunEventRow.sequence_number), -1)).where(
            WorkflowRunEventRow.workflow_run_id == run_id
        )
    )
    return result.scalar_one() + 1


async def _emit_crash_terminal_event(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> None:
    """Emit a terminal `workflow.failed` event after a crash (issue #1291).

    Called when the task catches an exception anywhere in run/resume.
    Ensures the run ends in a terminal `failed` state with a proper
    `workflow.failed` event, not stranded in `queued` or `running` with
    no terminal event."""
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        logger.warning(
            "workflow_run_crash_terminal_event_skipped_run_not_found",
            extra={"run_id": str(run_id)},
        )
        return

    try:
        now = datetime.now(UTC)
        seq = await _next_sequence_number(session, run_id)

        event = WorkflowFailedEvent(
            workflow_run_id=run_id,
            sequence_number=seq,
            event_type="workflow.failed",
            timestamp=now,
            payload=WorkflowFailedPayload(
                status=WorkflowRunStatus.FAILED,
                stop_reason=StopReason.WORKER_LOST,
            ),
            v=1,
        )

        # Insert the event row
        row = WorkflowRunEventRow(
            id=uuid.uuid4(),
            workflow_run_id=event.workflow_run_id,
            sequence_number=event.sequence_number,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=event.payload.model_dump(mode="json"),
            v=event.v,
        )
        session.add(row)

        # Update run status
        run.status = WorkflowRunStatus.FAILED.value
        run.stop_reason = StopReason.WORKER_LOST.value
        run.completed_at = now

        # Mark required_steps_completed as False for crash recovery tracking
        run.required_steps_completed = False

        await session.commit()

        logger.info(
            "workflow_run_crash_terminal_event_emitted",
            extra={"run_id": str(run_id)},
        )
    except Exception:
        logger.exception(
            "workflow_run_crash_terminal_event_emission_failed",
            extra={"run_id": str(run_id)},
            exc_info=True,
        )


async def _run_agent_workflow_async(run_id: str) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        with _sync_ledger_session() as sync_session:
            try:
                run, product = await _load_context(session, uuid.UUID(run_id))
                runner = await _construct_runner(session, sync_session, run, product)
                await runner.run(run.id, product_ref=product.tiktok_product_id)
                await session.commit()
            except Exception:
                # Catch any crash and emit a terminal event so the run doesn't
                # stay stranded in queued/running with no terminal event (ADR-074
                # decision 4, issue #1291).
                run_uuid = uuid.UUID(run_id)
                logger.exception(
                    "workflow_run_crashed",
                    extra={"run_id": str(run_uuid)},
                    exc_info=True,
                )
                await _emit_crash_terminal_event(session, run_uuid)


async def _resume_agent_workflow_async(run_id: str, *, approved: bool) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        with _sync_ledger_session() as sync_session:
            try:
                run, product = await _load_context(session, uuid.UUID(run_id))
                runner = await _construct_runner(session, sync_session, run, product)
                await runner.resume(run.id, approved=approved)
                await session.commit()
            except Exception:
                # Same crash handling as run_agent_workflow (issue #1291).
                run_uuid = uuid.UUID(run_id)
                logger.exception(
                    "workflow_resume_crashed",
                    extra={"run_id": str(run_uuid)},
                    exc_info=True,
                )
                await _emit_crash_terminal_event(session, run_uuid)


def run_agent_workflow_sync(run_id: str) -> None:
    asyncio.run(_run_agent_workflow_async(run_id))


def resume_agent_workflow_sync(run_id: str, approved: bool) -> None:
    asyncio.run(_resume_agent_workflow_async(run_id, approved=approved))


@celery_app.task(name="juli_backend.run_agent_workflow", acks_late=True, max_retries=1)
def run_agent_workflow(run_id: str) -> None:
    """Run (or continue) an agent workflow run outside the HTTP request cycle."""
    run_agent_workflow_sync(run_id)


@celery_app.task(name="juli_backend.resume_agent_workflow", acks_late=True, max_retries=1)
def resume_agent_workflow(run_id: str, approved: bool) -> None:
    """Resume a `waiting_approval` run with an approval decision (ADR-073
    decisions 1 and 5; issue #1123's `WorkflowRunner.resume`).

    Enqueued by the confirmation-authorization endpoint (P9 / #W4-A) -- this
    task only carries the already-made `approved` decision through to the
    runner; it does not itself validate or authorize it.
    """
    resume_agent_workflow_sync(run_id, approved=approved)
