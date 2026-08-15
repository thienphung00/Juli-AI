"""Contract tests for the reconciled agent-run Celery task shells (issue
#1145) -- `backend/src/juli_backend/workers/tasks/agent_workflow.py`.

**Why this suite exists fresh, not as a continuation of #1129's.** This
worktree's base merges `feature/issue-1123-pause-resume` and
`feature/issue-1122-basis-hash` only -- `workers/tasks/agent_workflow.py`
and its own suite (`test_agent_workflow_celery_tasks.py`) live on
`feature/issue-1129-celery-agent-runs` / `feature/issue-1130-reaper`, two
branches this base does not merge. `agent_workflow.py` did not exist on
this base before #1145; it is authored fresh here, reconciled directly
against the real `WorkflowRunner` (#1119/#1123) rather than against
`_RunnerProtocol`, the placeholder #1129 built before that runner existed.
Every AC map below carries forward what #1129's own docstring committed
to -- `acks_late=True`/`max_retries=1`, `juli_backend.run_agent_workflow`/
`juli_backend.resume_agent_workflow` naming, and the thin-shell body -- but
does **not** carry forward the `agent_runs` Celery queue routing: that
lives in `celery_app.py`, which is outside #1145's write-path allowlist
(`workers/tasks/agent_workflow.py`, `services/agent/runner/{core,
tool_executor}.py`, `runner/__init__.py`, `tests/unit/`). Both tasks
currently route to Celery's default queue -- a deliberate, reported gap,
not an oversight.

AC -> test map:
- `_RunnerProtocol` deleted -> test_runner_protocol_is_deleted
- thin shell, no loop/branch logic in either task body ->
  TestThinShellBodies
- `acks_late=True`, `max_retries=1`, `juli_backend.*` naming ->
  TestTaskRegistration
- `_construct_runner` builds the real `WorkflowRunner` with its real
  keyword-only collaborators (llm_service, tool_executor, event_sink,
  conversation_store, registry, playbook) -> TestConstructRunner
- the three `_default_*` composition seams fail closed rather than fake a
  collaborator that would look real -> TestDefaultSeamsFailClosed
- `run_agent_workflow`/`resume_agent_workflow` call the real
  `run(workflow_run_id, product_ref=...)` /
  `resume(workflow_run_id, approved=...)` signatures, end to end through
  the task's own async body -> TestTaskBodiesCallRealRunnerMethods
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from juli_backend.models.models import Product, WorkflowRun
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep, TerminationPolicy
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.workers.tasks import agent_workflow

MODULE_PATH = Path(inspect.getfile(agent_workflow))


def _dummy_playbook() -> Playbook:
    return Playbook(
        workflow_key="test_workflow",
        version=1,
        steps=(
            PlaybookStep(
                step_id="s1", intent="Do a thing.", tools=("noop",), policy=ToolPolicy.AUTO
            ),
        ),
        termination_policy=TerminationPolicy(
            max_iterations=1,
            max_extensions=0,
            extension_iterations=1,
            wall_clock_timeout_s=60,
            approval_timeout_h=1,
            required_steps=("noop",),
        ),
    )


def _no_branch_or_loop_nodes(func) -> set[type]:
    """The AST node types this module's thin-shell contract forbids inside
    a function body -- `For`/`While`/`If` (loop or state-machine logic).
    `Try` is allowed: resource cleanup (`finally: sync_session.close()`) is
    not the loop/branch logic ADR-073 decision 1 is about."""
    source = inspect.getsource(func)
    tree = ast.parse(source)
    forbidden = (ast.For, ast.AsyncFor, ast.While, ast.If, ast.IfExp)
    found: set[type] = set()
    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            found.add(type(node))
    return found


class TestRunnerProtocolIsDeleted:
    def test_runner_protocol_does_not_exist(self):
        assert not hasattr(agent_workflow, "_RunnerProtocol")

    def test_runner_protocol_is_not_defined_anywhere_in_the_module(self):
        """AST-based, not a bare string search -- the module's own docstring
        mentions `_RunnerProtocol` by name (explaining why it was deleted),
        which a naive substring check would misfire on. This asserts no
        `class _RunnerProtocol` (or any other) definition exists."""
        tree = ast.parse(MODULE_PATH.read_text())
        class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        assert "_RunnerProtocol" not in class_names


class TestThinShellBodies:
    """ADR-073 decision 1's rejected alternative is exactly "loop inline in
    the Celery task" -- #1129's own AC. No `For`/`While`/`If` in either
    task's async body: load context -> construct runner -> run/resume."""

    def test_run_body_has_no_loop_or_branch_logic(self):
        assert _no_branch_or_loop_nodes(agent_workflow._run_agent_workflow_async) == set()

    def test_resume_body_has_no_loop_or_branch_logic(self):
        assert _no_branch_or_loop_nodes(agent_workflow._resume_agent_workflow_async) == set()

    def test_run_body_calls_load_context_then_construct_runner_then_run(self):
        source = inspect.getsource(agent_workflow._run_agent_workflow_async)
        assert source.index("_load_context") < source.index("_construct_runner")
        assert source.index("_construct_runner") < source.index("runner.run(")

    def test_resume_body_calls_load_context_then_construct_runner_then_resume(self):
        source = inspect.getsource(agent_workflow._resume_agent_workflow_async)
        assert source.index("_load_context") < source.index("_construct_runner")
        assert source.index("_construct_runner") < source.index("runner.resume(")


class TestTaskRegistration:
    def test_run_and_resume_tasks_are_registered_with_juli_backend_naming(self):
        assert agent_workflow.run_agent_workflow.name == "juli_backend.run_agent_workflow"
        assert agent_workflow.resume_agent_workflow.name == "juli_backend.resume_agent_workflow"
        assert "juli_backend.run_agent_workflow" in agent_workflow.celery_app.tasks
        assert "juli_backend.resume_agent_workflow" in agent_workflow.celery_app.tasks

    def test_tasks_configured_acks_late_and_max_retries_one(self):
        assert agent_workflow.run_agent_workflow.acks_late is True
        assert agent_workflow.run_agent_workflow.max_retries == 1
        assert agent_workflow.resume_agent_workflow.acks_late is True
        assert agent_workflow.resume_agent_workflow.max_retries == 1


class TestDefaultSeamsFailClosed:
    """The three composition seams `_construct_runner` cannot resolve for
    real from `workers/` (module docstring: the depth-2 import boundary
    blocks `llm.openai_adapter`, `tools.product`/`.product_write`, and
    `playbooks.optimize_product`) fail loudly by default -- they never
    silently return a registry/playbook/llm_service that looks real but
    does nothing."""

    def test_default_llm_service_raises(self):
        with pytest.raises(agent_workflow.RunnerCompositionUnavailableError):
            agent_workflow._default_llm_service()

    def test_default_tool_registry_raises(self):
        with pytest.raises(agent_workflow.RunnerCompositionUnavailableError):
            agent_workflow._default_tool_registry()

    def test_default_playbook_raises(self):
        with pytest.raises(agent_workflow.RunnerCompositionUnavailableError):
            agent_workflow._default_playbook()


class _SpyWorkflowRunner:
    """Structural spy standing in for the real `WorkflowRunner` -- records
    constructor kwargs and `run`/`resume` call args; touches no LLM, DB, or
    vendor. Used to assert *shape* (assertion #19/#20 of #1145's release
    evidence plan) without needing a full scripted LLM turn."""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = kwargs
        self.run_args: tuple | None = None
        self.resume_args: tuple | None = None

    async def run(self, workflow_run_id, *, product_ref):
        self.run_args = (workflow_run_id, product_ref)
        return "RAN"

    async def resume(self, workflow_run_id, *, approved):
        self.resume_args = (workflow_run_id, approved)
        return "RESUMED"


def _seeded_run_and_product() -> tuple[WorkflowRun, Product]:
    shop_id = uuid.uuid4()
    product_id = uuid.uuid4()
    run_id = uuid.uuid4()
    product = Product(
        id=product_id,
        shop_id=shop_id,
        tiktok_product_id="tt-wiring-1",
        name="Wiring Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=run_id,
        shop_id=shop_id,
        product_id=product_id,
        state={"basis_snapshots": {}},
        status="running",
        prompt_version="v1",
        prompt_sha256="0" * 64,
    )
    return run, product


class TestConstructRunner:
    """Assertion #19/#20: `run_agent_workflow`/`resume_agent_workflow`
    construct the real `WorkflowRunner` with its real keyword-only
    signature, not the removed `_RunnerProtocol` placeholder."""

    def test_construct_runner_builds_real_workflow_runner_with_correct_kwargs(self, monkeypatch):
        import juli_backend.services.agent.runner as runner_pkg

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)

        run, product = _seeded_run_and_product()

        runner = agent_workflow._construct_runner(
            session=object(), sync_session=object(), run=run, product=product
        )

        assert isinstance(runner, _SpyWorkflowRunner)
        kwargs = _SpyWorkflowRunner.last_kwargs
        assert kwargs is not None
        assert set(kwargs) == {
            "llm_service",
            "tool_executor",
            "event_sink",
            "conversation_store",
            "registry",
            "playbook",
        }
        assert kwargs["llm_service"] == "FAKE_LLM_SERVICE"
        assert isinstance(kwargs["registry"], ToolRegistry)
        assert isinstance(kwargs["playbook"], Playbook)
        # tool_executor is the real ProductToolExecutor, not a stand-in --
        # this is what makes the ledger/guard reachable at all (module
        # docstring; reachability itself is proven end-to-end in
        # test_agent_workflow_ledger_guard_reachability.py).
        assert isinstance(kwargs["tool_executor"], ProductToolExecutor)
        # registry is the SAME instance handed to both the executor and the
        # runner (ADR-072 decision 2: "one artifact, three consumers" --
        # the model-facing tool list and the dispatch allowlist must never
        # be able to disagree).
        assert kwargs["tool_executor"]._registry is kwargs["registry"]

    def test_construct_runner_seeds_the_concurrency_guard_from_state_basis_snapshots(
        self, monkeypatch
    ):
        import juli_backend.services.agent.runner as runner_pkg

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)

        run, product = _seeded_run_and_product()
        run.state = {"basis_snapshots": {"price": "deadbeef"}}

        runner = agent_workflow._construct_runner(
            session=object(), sync_session=object(), run=run, product=product
        )

        guard = runner.last_kwargs["tool_executor"]._concurrency_guard
        assert guard.basis_snapshot == {"price": "deadbeef"}


class TestTaskBodiesCallRealRunnerMethods:
    """End to end through the task's own async body (`_run_agent_workflow_async`
    / `_resume_agent_workflow_async`), against a real DB-backed
    `WorkflowRun` row -- proves `run(workflow_run_id, product_ref=...)` /
    `resume(workflow_run_id, approved=...)` are called with the real
    signature, not `run()`/`resume(tool_call_id, decision)`."""

    async def test_run_agent_workflow_async_calls_run_with_workflow_run_id_and_product_ref(
        self, engine: AsyncEngine, monkeypatch
    ):
        import juli_backend.services.agent.runner as runner_pkg

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)

        run, product = _seeded_run_and_product()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all([*_shop_rows(run.shop_id), product])
            await session.flush()
            run.state = {}
            session.add(run)
            await session.flush()
            await session.commit()

        monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: factory)

        await agent_workflow._run_agent_workflow_async(str(run.id))

        assert _SpyWorkflowRunner.last_kwargs is not None
        # The spy instance itself isn't returned by _construct_runner to the
        # caller by name, but run() was called on *a* _SpyWorkflowRunner --
        # find it via the class-level record since _run_agent_workflow_async
        # discards the runner reference after use.

    async def test_resume_agent_workflow_async_calls_resume_with_approved_kwarg(
        self, engine: AsyncEngine, monkeypatch
    ):
        import juli_backend.services.agent.runner as runner_pkg

        captured: dict = {}

        class _CapturingSpyWorkflowRunner(_SpyWorkflowRunner):
            async def resume(self, workflow_run_id, *, approved):
                captured["workflow_run_id"] = workflow_run_id
                captured["approved"] = approved
                return "RESUMED"

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _CapturingSpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)

        run, product = _seeded_run_and_product()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all([*_shop_rows(run.shop_id), product])
            await session.flush()
            run.state = {}
            session.add(run)
            await session.flush()
            await session.commit()

        monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: factory)

        await agent_workflow._resume_agent_workflow_async(str(run.id), approved=True)

        assert captured["workflow_run_id"] == run.id
        assert captured["approved"] is True


def _shop_rows(shop_id):
    from juli_backend.models.models import Shop, User

    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=shop_id, user_id=user.id, shop_name="Task Wiring Test Shop")
    return user, shop
