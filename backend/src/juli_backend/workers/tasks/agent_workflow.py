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

**What this module still cannot build for real -- a pre-existing, structural
gap, not introduced by #1145.** `.importlinter.toml`'s cross-package depth
cap (`max_cross_package_depth = 2`) limits every import this module makes
into `services.agent` to that package's own public depth-2 facade
(`juli_backend.services.agent.<child>`, e.g. `services.agent.runner`) -- and
`workers`' `[allowed_edges]` row does not list `integrations` at all, so
this module can never import `juli_backend.integrations.tiktok` at any
depth. Three collaborators a real Optimize Product run needs are, today,
reachable only from *inside* `services/agent` itself, never from `workers/`:

- the production LLM adapter (`services.agent.llm.openai_adapter
  .OpenAIResponsesAdapter`) -- deliberately *not* re-exported at
  `services.agent.llm`'s public facade (that package's `MODULE.md`: "so
  nothing depends on a concrete adapter by accident");
- the populated Optimize Product `ToolRegistry`
  (`services.agent.tools.product.register_product_read_tools` /
  `...product_write.register_product_write_tools`) -- one level below
  `services.agent.tools`'s public facade, which re-exports only the empty
  `ToolRegistry` class itself;
- the concrete `OPTIMIZE_PRODUCT_PLAYBOOK`
  (`services.agent.playbooks.optimize_product`) -- one level below
  `services.agent.playbooks`'s public facade, which re-exports only the
  generic `Playbook`/`PlaybookStep` shapes.

`_default_llm_service`/`_default_tool_registry`/`_default_playbook` below
are the three named seams standing in for this: each raises
`RunnerCompositionUnavailableError` naming exactly which import boundary
blocks it, rather than faking a registry/playbook that would look real and
silently do nothing. Closing this gap needs a small composition-root
addition *inside* `services/agent` (its own `__init__.py`, or a new module
there) -- outside #1145's write-path allowlist, so not attempted here;
flagged as follow-up work in that issue's report. `read_resources`/
`write_resources` are left `None` on the constructed `ProductToolExecutor`
for the same reason -- a configuration that module's own docstring already
treats as supported ("Either may be left `None` when a run only ever needs
the other side").

None of this blocks what #1145 actually proves: with the three seams
overridden (as `tests/unit/test_agent_workflow_task_wiring.py` does), this
module constructs a real `WorkflowRunner` with its real keyword-only
signature; separately (`tests/unit/test_agent_workflow_ledger_guard_reachability.py`),
a WRITE call dispatched through a real `WorkflowRunner` genuinely reaches
both `ToolExecutionLedger` and `ConcurrencyGuard`.

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
cancel` writing that column from a different process. Neither closes the
three `RunnerCompositionUnavailableError` seams above: a live enqueued run
still cannot construct a real LLM service, tool registry or playbook from
`workers/` today, so an end-to-end live run remains unreachable regardless
of the enqueue path now existing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections.abc import Callable, Iterator

from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from juli_backend.models.models import Product, WorkflowRun
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url


class RunnerCompositionUnavailableError(RuntimeError):
    """Raised by one of the `_default_*` seams below when the real
    collaborator it stands in for is not reachable from `workers/` under
    today's import boundary -- see the module docstring's "What this module
    still cannot build for real" section. Never silently swapped for a
    fake that would look real."""


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
    raise RunnerCompositionUnavailableError(
        "services.agent.llm.openai_adapter.OpenAIResponsesAdapter is not reachable "
        "from workers/ under .importlinter.toml's depth-2 cross-package cap, and is "
        "deliberately not re-exported at services.agent.llm's public facade -- see "
        "this module's docstring."
    )


def _default_tool_registry():
    raise RunnerCompositionUnavailableError(
        "register_product_read_tools/register_product_write_tools "
        "(services.agent.tools.product / .product_write) are not reachable from "
        "workers/ under .importlinter.toml's depth-2 cross-package cap -- see this "
        "module's docstring."
    )


def _default_playbook():
    raise RunnerCompositionUnavailableError(
        "OPTIMIZE_PRODUCT_PLAYBOOK (services.agent.playbooks.optimize_product) is "
        "not reachable from workers/ under .importlinter.toml's depth-2 "
        "cross-package cap -- see this module's docstring."
    )


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


def _construct_runner(
    session: AsyncSession,
    sync_session: Session,
    run: WorkflowRun,
    product: Product,
):
    """Construct the real `WorkflowRunner` for `run` -- the one-line wiring
    point issue #1145 restores (ADR-073 decision 1). Builds a
    `ToolExecutionLedger` and a `ConcurrencyGuard` and hands both to a
    `ProductToolExecutor`, so a WRITE this run dispatches genuinely reaches
    both (see module docstring). `read_resources`/`write_resources` stay
    `None` -- a `ProductToolExecutor`-supported configuration for a run that
    cannot yet reach real marketplace credentials from this package.

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
    module's own `test_agent_workflow_task_wiring.py`), not by adding an
    `event_sink` parameter here -- `_construct_runner`'s signature is
    unchanged, only what it builds by default is.
    """
    from juli_backend.services.agent import events as events_module
    from juli_backend.services.agent import runner as runner_module

    registry = _default_tool_registry()
    ledger = runner_module.ToolExecutionLedger(sync_session, shop_id=run.shop_id)
    concurrency_guard = runner_module.ConcurrencyGuard(
        basis_snapshot=run.state.get("basis_snapshots", {})
    )
    tool_executor = runner_module.ProductToolExecutor(
        registry=registry,
        product_id=product.tiktok_product_id,
        ledger=ledger,
        workflow_run_id=run.id,
        concurrency_guard=concurrency_guard,
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


async def _run_agent_workflow_async(run_id: str) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        with _sync_ledger_session() as sync_session:
            run, product = await _load_context(session, uuid.UUID(run_id))
            runner = _construct_runner(session, sync_session, run, product)
            await runner.run(run.id, product_ref=product.tiktok_product_id)
            await session.commit()


async def _resume_agent_workflow_async(run_id: str, *, approved: bool) -> None:
    factory = _ensure_session_factory()
    async with factory() as session:
        with _sync_ledger_session() as sync_session:
            run, product = await _load_context(session, uuid.UUID(run_id))
            runner = _construct_runner(session, sync_session, run, product)
            await runner.resume(run.id, approved=approved)
            await session.commit()


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
