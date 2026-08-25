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
- the `_default_llm_service`/`_default_tool_registry`/`_default_playbook`
  composition seams build the real collaborators (issue #1173), with
  `_default_llm_service` failing closed on a missing `OPENAI_API_KEY`
  rather than faking a collaborator that would look real ->
  TestDefaultSeamsComposeRealCollaborators
- `_default_read_resources`/`_default_write_resources` build the real
  guarded `ProductionReadResources`/`SandboxWriteResources` (issue #1173
  review-round-1 rework, closing the uncaught-crash-on-first-tool-call gap
  Review found), failing closed on missing `TIKTOK_APP_KEY`/
  `TIKTOK_APP_SECRET` or an unprovisioned credential row ->
  TestDefaultResourceSeamsComposeRealMarketplaceResources
- `run_agent_workflow`/`resume_agent_workflow` call the real
  `run(workflow_run_id, product_ref=...)` /
  `resume(workflow_run_id, approved=...)` signatures, end to end through
  the task's own async body -> TestTaskBodiesCallRealRunnerMethods
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime, timedelta
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


class TestDefaultSeamsComposeRealCollaborators:
    """Issue #1173: `services/agent/composition.py` closes the import-
    boundary gap the three `_construct_runner` seams previously could not
    cross from `workers/` -- `RunnerCompositionUnavailableError` (retired,
    kept only for backward compatibility -- see its docstring) is no longer
    raised by any of them. `_default_tool_registry` and `_default_playbook`
    need no credentials at all and always succeed; `_default_llm_service`
    fails closed on a missing `OPENAI_API_KEY` with a precise, ordinary
    `RuntimeError` (`require_env`'s own message), never the retired
    composition-unavailable error and never a silent fake."""

    def test_default_tool_registry_builds_the_real_populated_registry(self):
        from juli_backend.services.agent.tools import ToolRegistry

        registry = agent_workflow._default_tool_registry()

        assert isinstance(registry, ToolRegistry)
        names = {spec.name for spec in registry.list_all()}
        assert names == {
            "get_product_information",
            "get_seo_keywords",
            "check_product_status",
            # #1208: the image step is a READ inspection now; upload stays
            # registered for the future generation capability.
            "inspect_product_image",
            "upload_product_image",
            "update_product_listing",
            "update_product_price",
        }

    def test_default_playbook_returns_the_real_optimize_product_playbook(self):
        from juli_backend.services.agent.playbooks import OPTIMIZE_PRODUCT_PLAYBOOK
        from juli_backend.services.agent.playbooks.base import Playbook

        playbook = agent_workflow._default_playbook()

        assert isinstance(playbook, Playbook)
        assert playbook is OPTIMIZE_PRODUCT_PLAYBOOK

    def test_default_llm_service_builds_the_real_openai_adapter_when_key_present(self, monkeypatch):
        from juli_backend.services.agent.llm import LLMService
        from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")

        llm_service = agent_workflow._default_llm_service()

        assert isinstance(llm_service, OpenAIResponsesAdapter)
        assert isinstance(llm_service, LLMService)

    def test_default_llm_service_fails_closed_with_precise_error_when_key_absent(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            agent_workflow._default_llm_service()

    def test_default_llm_service_fails_closed_when_key_is_blank(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "   ")

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            agent_workflow._default_llm_service()

    def test_default_llm_service_never_raises_the_retired_composition_error(self, monkeypatch):
        """The retired `RunnerCompositionUnavailableError` must never appear
        again on this path -- a missing credential is a different failure
        mode than "unreachable from workers/" (see the class's own
        docstring)."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            agent_workflow._default_llm_service()

        assert not isinstance(exc_info.value, agent_workflow.RunnerCompositionUnavailableError)

    def test_default_tool_registry_and_default_playbook_never_need_openai_key(self, monkeypatch):
        """Neither of these seams touches marketplace or LLM credentials --
        both must succeed even with no relevant environment configured."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        agent_workflow._default_tool_registry()
        agent_workflow._default_playbook()


class TestDefaultResourceSeamsComposeRealMarketplaceResources:
    """Issue #1173 review-round-1 rework. Review's finding: `_construct_runner`
    passed `read_resources=write_resources=None` into `ProductToolExecutor`,
    so a real composed run crashed uncaught on its first tool call
    (`ToolExecutionError`, `runner/tool_executor.py`). `_default_read_resources`/
    `_default_write_resources` close that gap. Credential-seeding mirrors
    `test_fujiwa_polling_orchestration.py`'s own `fujiwa_credential` fixture
    -- `TikTokCredentialRepo(session).create(...)` against a real (in-memory)
    async session, the same DB-fake idiom that suite uses to exercise
    `resolve_production_read_credential`, not a mock."""

    async def test_default_read_resources_builds_real_production_read_resources(
        self, session, monkeypatch
    ):
        from juli_backend.integrations.tiktok import (
            PRODUCTION_AUTH_ID,
            ProductionReadResources,
            TikTokCapability,
        )
        from juli_backend.repositories.repos import TikTokCredentialRepo

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        shop_id = uuid.uuid4()
        session.add_all(_shop_rows(shop_id))
        await session.flush()
        await TikTokCredentialRepo(session).create(
            shop_id=shop_id,
            access_token="fujiwa-access",
            refresh_token="fujiwa-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            shop_cipher="ROW_test_cipher",
        )

        resources = await agent_workflow._default_read_resources(session)

        assert isinstance(resources, ProductionReadResources)

    async def test_default_write_resources_builds_real_sandbox_write_resources(
        self, session, monkeypatch
    ):
        from juli_backend.integrations.tiktok import (
            SANDBOX_AUTH_ID,
            SandboxWriteResources,
            TikTokCapability,
        )
        from juli_backend.repositories.repos import TikTokCredentialRepo

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        shop_id = uuid.uuid4()
        session.add_all(_shop_rows(shop_id))
        await session.flush()
        await TikTokCredentialRepo(session).create(
            shop_id=shop_id,
            access_token="sandbox-access",
            refresh_token="sandbox-refresh",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            shop_cipher="ROW_sandbox_cipher",
        )

        resources = await agent_workflow._default_write_resources(session)

        assert isinstance(resources, SandboxWriteResources)

    async def test_default_read_resources_fails_closed_when_app_key_absent(
        self, session, monkeypatch
    ):
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        with pytest.raises(RuntimeError, match="TIKTOK_APP_KEY"):
            await agent_workflow._default_read_resources(session)

    async def test_default_write_resources_fails_closed_when_app_secret_absent(
        self, session, monkeypatch
    ):
        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)

        with pytest.raises(RuntimeError, match="TIKTOK_APP_SECRET"):
            await agent_workflow._default_write_resources(session)

    async def test_default_read_resources_fails_closed_when_credential_row_missing(
        self, session, monkeypatch
    ):
        from juli_backend.database.exceptions import NotFound

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        with pytest.raises(NotFound):
            await agent_workflow._default_read_resources(session)

    async def test_default_write_resources_fails_closed_when_credential_row_missing(
        self, session, monkeypatch
    ):
        from juli_backend.database.exceptions import NotFound

        monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
        monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")

        with pytest.raises(NotFound):
            await agent_workflow._default_write_resources(session)


async def _fake_read_resources(session, shop_id=None):
    """Injection double for `_default_read_resources` -- every
    `_construct_runner` test below is a wiring test, not a marketplace-
    credential test (that is `TestDefaultResourceSeamsComposeRealMarketplaceResources`
    above), so it monkeypatches this the same way the pre-existing three
    seams are already monkeypatched, keeping `session=object()` valid.

    Issue #1302 amendment: accepts optional shop_id parameter to support
    shop-aware read routing tests, but never uses it in the fake."""
    return "FAKE_READ_RESOURCES"


async def _fake_write_resources(session):
    """Injection double for `_default_write_resources` -- see
    `_fake_read_resources` above."""
    return "FAKE_WRITE_RESOURCES"


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

    async def test_construct_runner_builds_real_workflow_runner_with_correct_kwargs(
        self, monkeypatch
    ):
        import juli_backend.services.agent.runner as runner_pkg

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)
        monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
        monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)

        run, product = _seeded_run_and_product()

        runner = await agent_workflow._construct_runner(
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
            "cancel_check",
        }
        assert callable(kwargs["cancel_check"])
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
        # read_resources/write_resources are wired (issue #1173
        # review-round-1 rework) -- no longer left None, the gap that made
        # a real composed run's first tool call crash uncaught.
        assert kwargs["tool_executor"]._read_resources == "FAKE_READ_RESOURCES"
        assert kwargs["tool_executor"]._write_resources == "FAKE_WRITE_RESOURCES"

    async def test_construct_runner_seeds_the_concurrency_guard_from_state_basis_snapshots(
        self, monkeypatch
    ):
        import juli_backend.services.agent.runner as runner_pkg

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)
        monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
        monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)

        run, product = _seeded_run_and_product()
        run.state = {"basis_snapshots": {"price": "deadbeef"}}

        runner = await agent_workflow._construct_runner(
            session=object(), sync_session=object(), run=run, product=product
        )

        guard = runner.last_kwargs["tool_executor"]._concurrency_guard
        assert guard.basis_snapshot == {"price": "deadbeef"}


class TestConstructRunnerUsesRealPersistingEventSink:
    """Issue #1171: the real task path (no injection) must construct the
    runner with `PersistingEventSink` (ADR-074 decision 3), not
    `InMemoryEventSink` -- every ADR-074 persistence/relay guarantee is
    proven at unit/integration level elsewhere (`test_agent_events_
    streaming_matrix.py`) but was never wired end to end into
    `_construct_runner` before this. A live run built `InMemoryEventSink`
    and produced zero `workflow_run_events` rows and nothing for the SSE
    endpoint to serve."""

    async def test_construct_runner_builds_a_persisting_event_sink_not_in_memory(self, monkeypatch):
        import juli_backend.services.agent.runner as runner_pkg
        from juli_backend.services.agent.events import InMemoryEventSink, PersistingEventSink

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)
        monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
        monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)

        run, product = _seeded_run_and_product()

        await agent_workflow._construct_runner(
            session=object(), sync_session=object(), run=run, product=product
        )

        kwargs = _SpyWorkflowRunner.last_kwargs
        assert kwargs is not None
        assert isinstance(kwargs["event_sink"], PersistingEventSink)
        assert not isinstance(kwargs["event_sink"], InMemoryEventSink)


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
        monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
        monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)

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
        monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
        monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)

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


# ---------------------------------------------------------------------------
# `cancel_check` (issue #1145 Gap 3): reads workflow_runs.cancel_requested
# fresh from the database on every poll -- the API process writes the flag,
# a *different* worker process reads it via `_construct_runner`'s
# `cancel_check`, so a cached/snapshotted read defeats the entire mechanism.
# ---------------------------------------------------------------------------


def _sqlite_sync_session_factory():
    """A same-thread `sqlite:///:memory:` engine -- SQLAlchemy defaults
    `:memory:` SQLite to `SingletonThreadPool`, so every `Session` this
    factory produces shares the one underlying in-memory database (same
    thread), which is what lets one session write and a second session
    observe it without a real Postgres instance."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from juli_backend.orm_base import Base

    # `models/models.py` schema-qualifies some tables (bronze/silver/gold/
    # ops); SQLite has no such schemas, so fold them onto the default
    # database -- mirrors tests/unit/conftest.py's async `engine` fixture
    # and test_agent_runner_ledger.py's own sync `sync_engine` fixture.
    engine = create_engine(
        "sqlite:///:memory:",
        execution_options={
            "schema_translate_map": {"ops": None, "bronze": None, "gold": None, "silver": None}
        },
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


class TestCancelCheckReadsFreshFromDatabase:
    def _seed_run(self, session_factory):
        from juli_backend.models.models import Product, Shop, User, WorkflowRun

        with session_factory() as setup_session:
            user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
            shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Cancel Check Shop")
            product = Product(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id="tt-cancel-check-1",
                name="Cancel Check Product",
                status="active",
                update_time=datetime.now(UTC),
            )
            run = WorkflowRun(
                id=uuid.uuid4(),
                shop_id=shop.id,
                product_id=product.id,
                state={},
                status="running",
                prompt_version="v1",
                prompt_sha256="0" * 64,
                cancel_requested=False,
            )
            setup_session.add_all([user, shop, product, run])
            setup_session.commit()
            return run.id

    async def test_construct_runner_wires_a_cancel_check_that_reads_the_column_fresh(
        self, monkeypatch
    ):
        """End-to-end through `_construct_runner` itself, not just the
        standalone helper -- proves the real seam `WorkflowRunner` receives
        observes a write made through a second, independent session after
        `_construct_runner` already ran.

        Holds `kept_alive` as an explicit strong reference to the same
        identity-mapped row `cancel_check` would load. SQLAlchemy's
        identity map is weak-referenced: a `cancel_check` closure that
        loads a row into a purely local variable lets CPython garbage
        -collect it the instant the closure returns, so a naive
        `Session.get()`-based implementation would (by GC-timing accident,
        not by design) still happen to re-query and pass this test even
        though it is the wrong implementation -- exactly the false-negative
        `test_session_get_would_have_returned_a_stale_cached_value` below
        demonstrates in isolation. Keeping one more reference alive here
        removes that accident and makes the assertion deterministic,
        mirroring a real worker process where nothing guarantees the row
        was already garbage-collected between two checkpoint polls.
        """
        import juli_backend.services.agent.runner as runner_pkg

        monkeypatch.setattr(runner_pkg, "WorkflowRunner", _SpyWorkflowRunner)
        monkeypatch.setattr(agent_workflow, "_default_llm_service", lambda: "FAKE_LLM_SERVICE")
        monkeypatch.setattr(agent_workflow, "_default_tool_registry", ToolRegistry)
        monkeypatch.setattr(agent_workflow, "_default_playbook", _dummy_playbook)
        monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
        monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)

        session_factory, engine = _sqlite_sync_session_factory()
        try:
            run_id = self._seed_run(session_factory)
            sync_session = session_factory()
            try:
                from juli_backend.models.models import WorkflowRun

                run, product = _seeded_run_and_product()
                run.id = run_id
                run.state = {"basis_snapshots": {}}

                runner = await agent_workflow._construct_runner(
                    session=object(), sync_session=sync_session, run=run, product=product
                )
                cancel_check = runner.last_kwargs["cancel_check"]

                kept_alive = sync_session.get(WorkflowRun, run_id)
                assert kept_alive.cancel_requested is False
                assert cancel_check() is False

                # A different session -- standing in for the API process,
                # which never shares a session (or a process) with the
                # worker that reads this flag.
                with session_factory() as writer_session:
                    from sqlalchemy import update

                    writer_session.execute(
                        update(WorkflowRun)
                        .where(WorkflowRun.id == run_id)
                        .values(cancel_requested=True)
                    )
                    writer_session.commit()

                # Same cancel_check callable, same sync_session, no
                # re-construction -- must observe the write made through
                # the other session, not a snapshot taken at construction.
                # `kept_alive` (still referenced above) guarantees the
                # identity map still holds the pre-write row at this point.
                assert cancel_check() is True
                assert kept_alive.cancel_requested is False
            finally:
                sync_session.close()
        finally:
            engine.dispose()

    def test_session_get_would_have_returned_a_stale_cached_value(self, monkeypatch):
        """Negative control: demonstrates *why* `cancel_check` must not be
        built on `Session.get()` -- a `Session.get()`-backed check would
        return the identity-map-cached (stale) value here, the exact trap
        `_construct_runner`'s real `cancel_check` avoids."""
        from juli_backend.models.models import WorkflowRun

        session_factory, engine = _sqlite_sync_session_factory()
        try:
            run_id = self._seed_run(session_factory)
            sync_session = session_factory()
            try:
                loaded = sync_session.get(WorkflowRun, run_id)
                assert loaded.cancel_requested is False

                with session_factory() as writer_session:
                    from sqlalchemy import update

                    writer_session.execute(
                        update(WorkflowRun)
                        .where(WorkflowRun.id == run_id)
                        .values(cancel_requested=True)
                    )
                    writer_session.commit()

                # Session.get() on an already-loaded identity returns the
                # cached Python object without hitting the database again.
                stale = sync_session.get(WorkflowRun, run_id)
                assert stale.cancel_requested is False
            finally:
                sync_session.close()
        finally:
            engine.dispose()
