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
import inspect
import textwrap
import uuid
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
    """Adding the queue/tasks must not touch the four pre-existing beat entries."""
    schedule = celery_app.conf.beat_schedule
    assert schedule["mock-analytics-hourly-reconcile"]["task"] == (
        "juli_backend.mock_analytics_hourly_reconcile"
    )
    assert schedule["cdp-batch-staggered-reconcile"]["task"] == (
        "juli_backend.cdp_batch_staggered_reconcile"
    )
    assert schedule["analytics-backfill-topup"]["task"] == "juli_backend.analytics_backfill_topup"
    assert schedule["daily-impact-reader"]["task"] == "juli_backend.daily_impact_reader"
    assert len(schedule) == 4, "no new beat entries should have been added by this change"


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
def test_task_body_is_exactly_three_statements(func):
    """load-context, construct-runner, run/resume — nothing else."""
    node = _function_node(func)
    assert len(node.body) == 3, (
        f"{func.__name__} has {len(node.body)} statements; a thin shell has exactly 3"
    )


async def test_run_agent_workflow_async_calls_load_context_then_construct_runner_then_run(
    monkeypatch,
):
    order: list[tuple[str, object]] = []

    async def fake_load_context(run_id):
        order.append(("load_context", run_id))
        return "context-sentinel"

    def fake_construct_runner(context):
        order.append(("construct_runner", context))
        runner = AsyncMock()

        async def _run():
            order.append(("run", None))

        runner.run = _run
        return runner

    monkeypatch.setattr(agent_workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(agent_workflow, "_construct_runner", fake_construct_runner)

    await agent_workflow._run_agent_workflow_async("run-1")

    assert order == [
        ("load_context", "run-1"),
        ("construct_runner", "context-sentinel"),
        ("run", None),
    ]


async def test_resume_agent_workflow_async_calls_load_context_then_construct_runner_then_resume(
    monkeypatch,
):
    order: list[tuple[str, object]] = []

    async def fake_load_context(run_id):
        order.append(("load_context", run_id))
        return "context-sentinel"

    def fake_construct_runner(context):
        order.append(("construct_runner", context))
        runner = AsyncMock()

        async def _resume(tool_call_id, decision):
            order.append(("resume", (tool_call_id, decision)))

        runner.resume = _resume
        return runner

    monkeypatch.setattr(agent_workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(agent_workflow, "_construct_runner", fake_construct_runner)

    await agent_workflow._resume_agent_workflow_async("run-1", "call-1", "approve")

    assert order == [
        ("load_context", "run-1"),
        ("construct_runner", "context-sentinel"),
        ("resume", ("call-1", "approve")),
    ]


# ---------------------------------------------------------------------------
# Simulated retry: reconstructs from the run-state blob, not from scratch
# ---------------------------------------------------------------------------


class _FakeContext:
    """Stands in for the `workflow_runs` row `_load_context` would return."""

    def __init__(self, run_id: str, state: dict):
        self.run_id = run_id
        self.state = state


class _StubRunner:
    """The narrow `_RunnerProtocol` stub the issue calls sufficient (#1119 unmerged)."""

    def __init__(self, context: _FakeContext, store: dict):
        self._context = context
        self._store = store

    async def run(self) -> None:
        # A real WorkflowRunner would append an iteration and persist the
        # blob back to `workflow_runs.state`. Advancing from whatever is
        # CURRENTLY in the blob (not a fresh 0) is the entire point being
        # tested: a redelivered task must continue, not restart.
        current = self._context.state.get("iterations", 0)
        self._context.state["iterations"] = current + 1
        self._store[self._context.run_id] = dict(self._context.state)


def test_simulated_retry_reconstructs_from_run_state_blob_not_from_scratch(monkeypatch):
    run_id = str(uuid.uuid4())
    store: dict[str, dict] = {run_id: {"iterations": 0}}
    constructed_runners: list[_StubRunner] = []

    async def fake_load_context(rid: str) -> _FakeContext:
        # Fresh read of the current blob every call -- no task-local caching.
        return _FakeContext(rid, dict(store[rid]))

    def fake_construct_runner(context: _FakeContext) -> _StubRunner:
        runner = _StubRunner(context, store)
        constructed_runners.append(runner)
        return runner

    monkeypatch.setattr(agent_workflow, "_load_context", fake_load_context)
    monkeypatch.setattr(agent_workflow, "_construct_runner", fake_construct_runner)

    # First delivery.
    agent_workflow.run_agent_workflow_sync(run_id)
    # Simulated worker crash + acks_late redelivery: same run_id, invoked again.
    agent_workflow.run_agent_workflow_sync(run_id)

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
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: factory)

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

    loaded = await agent_workflow._load_context(str(run.id))
    assert loaded.id == run.id
    assert loaded.state == {"iterations": 3}


async def test_load_context_raises_lookup_error_for_missing_run(session, engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: factory)

    with pytest.raises(LookupError):
        await agent_workflow._load_context(str(uuid.uuid4()))
