"""Contract tests for the agent-run Celery task shells (#1129, ADR-074 d.4).

AC -> test map:
- distinct `agent_runs` queue, inspecting routing not naming ->
  test_agent_runs_queue_is_distinct_from_beat_and_analytics_routing
- `juli_backend.<name>` registration ->
  test_run_and_resume_tasks_are_registered_with_juli_backend_naming
- thin shells (load context -> construct runner -> run/resume, no loop logic
  in the task body) -> test_*_body_has_no_loop_or_branch_logic,
  test_*_async_calls_load_context_then_construct_runner_then_*
- acks_late=True, max_retries=1 -> test_tasks_configured_acks_late_and_max_retries_one
- simulated retry reconstructs from the run-state blob ->
  test_simulated_retry_reconstructs_from_run_state_blob_not_from_scratch
- existing beat entries / analytics + beat routing unaffected ->
  test_existing_beat_schedule_entries_survive_the_agent_queue_change
"""

from __future__ import annotations

import ast
import contextlib
import inspect
import textwrap
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from juli_backend.models.models import Product, Shop, WorkflowRun
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks import agent_workflow

# asyncio_mode = auto (pytest.ini) picks up every `async def test_*` in this
# file without a marker; sync tests need none either.


# ---------------------------------------------------------------------------
# Queue routing — inspect resolution, not naming (ADR-074 d.4)
# ---------------------------------------------------------------------------


def _resolved_queue_name(task_name: str) -> str:
    route = celery_app.amqp.router.route({}, task_name)
    return route["queue"].name


def test_agent_runs_queue_is_distinct_from_beat_and_analytics_routing():
    """Both new tasks route to `agent_runs`; every pre-existing task does not."""
    assert _resolved_queue_name("juli_backend.run_agent_workflow") == "agent_runs"
    assert _resolved_queue_name("juli_backend.resume_agent_workflow") == "agent_runs"

    pre_existing_task_names = [
        "juli_backend.mock_analytics_hourly_reconcile",
        "juli_backend.cdp_batch_staggered_reconcile",
        "juli_backend.analytics_backfill_topup",
        "juli_backend.daily_impact_reader",
    ]
    for task_name in pre_existing_task_names:
        assert _resolved_queue_name(task_name) != "agent_runs", (
            f"{task_name} must not have been rerouted onto the agent_runs queue"
        )


def test_existing_beat_schedule_entries_survive_the_agent_queue_change():
    """Adding the queue/tasks must not touch the four pre-existing beat entries.

    A fifth entry (the #1130 reaper, `reap-abandoned-workflow-runs`) is
    expected on top of these four -- see
    `test_workflow_run_reaper.py::test_beat_schedule_has_exactly_the_five_expected_entries`
    for the entry that pins the total.
    """
    schedule = celery_app.conf.beat_schedule
    assert schedule["mock-analytics-hourly-reconcile"]["task"] == (
        "juli_backend.mock_analytics_hourly_reconcile"
    )
    assert schedule["cdp-batch-staggered-reconcile"]["task"] == (
        "juli_backend.cdp_batch_staggered_reconcile"
    )
    assert schedule["analytics-backfill-topup"]["task"] == "juli_backend.analytics_backfill_topup"
    assert schedule["daily-impact-reader"]["task"] == "juli_backend.daily_impact_reader"


# ---------------------------------------------------------------------------
# Registration + acks_late/max_retries
# ---------------------------------------------------------------------------


def test_run_and_resume_tasks_are_registered_with_juli_backend_naming():
    assert agent_workflow.run_agent_workflow.name == "juli_backend.run_agent_workflow"
    assert agent_workflow.resume_agent_workflow.name == "juli_backend.resume_agent_workflow"
    assert "juli_backend.run_agent_workflow" in celery_app.tasks
    assert "juli_backend.resume_agent_workflow" in celery_app.tasks


def test_tasks_configured_acks_late_and_max_retries_one():
    assert agent_workflow.run_agent_workflow.acks_late is True
    assert agent_workflow.run_agent_workflow.max_retries == 1
    assert agent_workflow.resume_agent_workflow.acks_late is True
    assert agent_workflow.resume_agent_workflow.max_retries == 1


# ---------------------------------------------------------------------------
# Thin shell — structural (AST) + behavioral (call order)
# ---------------------------------------------------------------------------


def _patch_session_scopes(monkeypatch, order):
    """Bind both session scopes the reconciled shell opens (#1145).

    `_ensure_session_factory` yields an `AsyncSession` stand-in whose
    `commit()` is recorded, and `_sync_ledger_session` yields a sentinel for
    the ledger's sync `Session`. Neither touches a database.
    """

    class _AsyncSessionStub:
        async def commit(self):
            order.append(("commit", None))

    @contextlib.asynccontextmanager
    async def _factory_cm():
        yield _AsyncSessionStub()

    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: _factory_cm)

    @contextlib.contextmanager
    def _fake_sync_session():
        yield "sync-session-sentinel"

    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _fake_sync_session)


def _function_node(func) -> ast.AsyncFunctionDef:
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    node = tree.body[0]
    assert isinstance(node, ast.AsyncFunctionDef), f"{func} must be an async function"
    return node


@pytest.mark.parametrize(
    "func",
    [agent_workflow._run_agent_workflow_async, agent_workflow._resume_agent_workflow_async],
)
def test_task_body_has_no_loop_or_branch_logic(func):
    """The loop/state-machine belongs to WorkflowRunner, never the task body.

    A `for`/`while`/`if`/`try` anywhere in the body would be exactly the
    ADR-073 d.1 rejected alternative: "loop inline in the Celery task".
    """
    node = _function_node(func)
    forbidden = (ast.For, ast.While, ast.If, ast.Try)
    for child in ast.walk(node):
        assert not isinstance(child, forbidden), (
            f"{func.__name__} contains {type(child).__name__} — loop/branch logic must live "
            "in the runner module (services/agent/runner/), not the task shell"
        )


@pytest.mark.parametrize(
    "func",
    [agent_workflow._run_agent_workflow_async, agent_workflow._resume_agent_workflow_async],
)
def test_task_body_is_a_session_scoped_thin_shell(func):
    """load-context, construct-runner, run/resume, commit -- nothing else.

    #1129 asserted exactly three top-level statements, which was the right
    shape while `_load_context` owned its own session and the runner was a
    placeholder needing no resources. The real `WorkflowRunner` (#1119/#1123)
    shares one `AsyncSession` with `JsonbConversationStore` and needs a
    separate sync `Session` for `ToolExecutionLedger` (#1121), so the shell
    now binds both scopes and commits. Reconciled by #1145: the invariant
    that matters -- no loop or state-machine logic in the task body -- is
    unchanged and still enforced by
    `test_task_body_has_no_loop_or_branch_logic` above.
    """
    node = _function_node(func)
    assert len(node.body) == 2, (
        f"{func.__name__} has {len(node.body)} top-level statements; expected "
        "the session factory binding plus one `async with` scope"
    )
    async_with = node.body[1]
    assert isinstance(async_with, ast.AsyncWith), "the second statement opens the async session"
    sync_with = async_with.body[0]
    assert isinstance(sync_with, ast.With), "the ledger's sync session is bound inside it"
    assert len(sync_with.body) == 4, (
        f"{func.__name__}'s inner block has {len(sync_with.body)} statements; a thin shell "
        "is exactly load-context, construct-runner, run/resume, commit"
    )


async def test_run_agent_workflow_async_calls_load_context_then_construct_runner_then_run(
    monkeypatch,
):
    order: list[tuple[str, object]] = []
    run_id = uuid.uuid4()
    run_obj = SimpleNamespace(id=run_id)
    product_obj = SimpleNamespace(tiktok_product_id="tt-123")

    async def fake_load_context(session, rid):
        order.append(("load_context", rid))
        return run_obj, product_obj

    def fake_construct_runner(session, sync_session, run, product):
        order.append(("construct_runner", (run, product)))
        runner = AsyncMock()

        async def _run(wid, *, product_ref):
            order.append(("run", (wid, product_ref)))

        runner.run = _run
        return runner

    _patch_session_scopes(monkeypatch, order)
    monkeypatch.setattr(agent_workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(agent_workflow, "_construct_runner", fake_construct_runner)

    await agent_workflow._run_agent_workflow_async(str(run_id))

    assert order == [
        ("load_context", run_id),
        ("construct_runner", (run_obj, product_obj)),
        ("run", (run_id, "tt-123")),
        ("commit", None),
    ]


async def test_resume_agent_workflow_async_calls_load_context_then_construct_runner_then_resume(
    monkeypatch,
):
    order: list[tuple[str, object]] = []
    run_id = uuid.uuid4()
    run_obj = SimpleNamespace(id=run_id)
    product_obj = SimpleNamespace(tiktok_product_id="tt-123")

    async def fake_load_context(session, rid):
        order.append(("load_context", rid))
        return run_obj, product_obj

    def fake_construct_runner(session, sync_session, run, product):
        order.append(("construct_runner", (run, product)))
        runner = AsyncMock()

        async def _resume(wid, *, approved):
            order.append(("resume", (wid, approved)))

        runner.resume = _resume
        return runner

    _patch_session_scopes(monkeypatch, order)
    monkeypatch.setattr(agent_workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(agent_workflow, "_construct_runner", fake_construct_runner)

    await agent_workflow._resume_agent_workflow_async(str(run_id), approved=True)

    assert order == [
        ("load_context", run_id),
        ("construct_runner", (run_obj, product_obj)),
        ("resume", (run_id, True)),
        ("commit", None),
    ]


# ---------------------------------------------------------------------------
# Simulated retry: reconstructs from the run-state blob, not from scratch
# ---------------------------------------------------------------------------


class _FakeContext:
    """Stands in for the `workflow_runs` row `_load_context` returns."""

    def __init__(self, run_id, state: dict):
        self.id = run_id
        self.run_id = run_id
        self.state = state


class _StubRunner:
    """Stands in for the real `WorkflowRunner` at the task-shell seam."""

    def __init__(self, context: _FakeContext, store: dict):
        self._context = context
        self._store = store

    async def run(self, workflow_run_id, *, product_ref) -> None:
        # A real WorkflowRunner would append an iteration and persist the
        # blob back to `workflow_runs.state`. Advancing from whatever is
        # CURRENTLY in the blob (not a fresh 0) is the entire point being
        # tested: a redelivered task must continue, not restart.
        current = self._context.state.get("iterations", 0)
        self._context.state["iterations"] = current + 1
        self._store[self._context.id] = dict(self._context.state)


def test_simulated_retry_reconstructs_from_run_state_blob_not_from_scratch(monkeypatch):
    run_id = uuid.uuid4()
    store: dict[uuid.UUID, dict] = {run_id: {"iterations": 0}}
    constructed_runners: list[_StubRunner] = []

    async def fake_load_context(session, rid):
        # Fresh read of the current blob every call -- no task-local caching.
        return _FakeContext(rid, dict(store[rid])), SimpleNamespace(tiktok_product_id="tt-123")

    def fake_construct_runner(session, sync_session, run, product) -> _StubRunner:
        runner = _StubRunner(run, store)
        constructed_runners.append(runner)
        return runner

    _patch_session_scopes(monkeypatch, [])
    monkeypatch.setattr(agent_workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(agent_workflow, "_construct_runner", fake_construct_runner)

    # First delivery.
    agent_workflow.run_agent_workflow_sync(str(run_id))
    # Simulated worker crash + acks_late redelivery: same run_id, invoked again.
    agent_workflow.run_agent_workflow_sync(str(run_id))

    assert len(constructed_runners) == 2, "each invocation constructs its own runner"
    assert store[run_id]["iterations"] == 2, (
        "the second invocation must continue from the blob left by the first "
        "(iterations=1 -> 2), not restart from iterations=0"
    )


# ---------------------------------------------------------------------------
# `_load_context` against the real ORM model (production code path, not a stub)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def shop(session):
    s = Shop(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        shop_name="Agent Workflow Shop 1129",
        tiktok_shop_id="tiktok_shop_1129",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def product(session, shop):
    from datetime import UTC, datetime

    p = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tiktok_product_1129",
        name="Agent Workflow Product 1129",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(p)
    await session.flush()
    return p


async def test_load_context_reads_the_current_workflow_run_row(
    session, engine, shop, product, monkeypatch
):
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state={"iterations": 3},
        status="running",
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()

    loaded_run, loaded_product = await agent_workflow._load_context(session, run.id)
    assert loaded_run.id == run.id
    assert loaded_run.state == {"iterations": 3}
    assert loaded_product.id == product.id


async def test_load_context_raises_lookup_error_for_missing_run(session, engine, monkeypatch):
    with pytest.raises(LookupError):
        await agent_workflow._load_context(session, uuid.uuid4())
