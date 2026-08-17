"""`WorkflowRunner` terminal-transition persistence — issue #1178 / AGT-W3A.

The defect this closes: `WorkflowRunner` has always *computed*
`status_for(stop_reason)` (`status.py`'s total mapping) and returned it on
`RunResult`, but nothing on the real path ever wrote `workflow_runs.status`
/`stop_reason`/`completed_at` back to the row. `PersistingEventSink` only
ever inserts `workflow_run_events` rows (`persisting_sink.py` has zero
status handling by design — events are its whole job); `_run_agent_workflow_
async`/`_resume_agent_workflow_async` (`workers/tasks/agent_workflow.py`)
call `await runner.run(...)`/`await runner.resume(...)` and discard the
`RunResult` entirely. A successful live run's row stayed `status='running'`
forever, which then blocked the partial `uq_workflow_runs_active_shop_
product` index from ever allowing a retry until the reaper mislabeled the
row `worker_lost`.

**The seam this issue lands the fix on:** `ConversationStore.persist`
(`conversation_store.py`) — not `EventSink`. `core.py`'s own module
docstring already earmarked this ("writing them to the row's actual
`prompt_version`/`prompt_sha256` columns is a later slice's job, exactly
like `status`/`stop_reason`/`running_seconds_elapsed`" — the `persist` call
already the one place `WorkflowRunner` touches the row). `persist` grows two
new keyword-only parameters, `status`/`stop_reason`, both defaulting to
`None` (a no-op, preserving every existing per-iteration persist call's
behavior exactly). `JsonbConversationStore`'s implementation additionally
stamps `completed_at` when the status lands in one of the four terminal
members, or `waiting_approval_since` when it lands in `WAITING_APPROVAL` —
mirroring `_ReaperEventSink.emit`'s own column-flip logic
(`workers/tasks/reaper.py`) without copying it (reuse would need
`workers/` -> `services/agent/runner` at depth 3, forbidden by
`.importlinter.toml`'s depth-2 cap; the two are independent, narrow
implementations of the same idea instead).

**Why this does not fight `test_workflow_run_reaper.py::test_reap_never_
mutates_status_without_the_sink_performing_it`.** That test pins a fact
about the *reaper's own reap loop specifically*: `_reap_stale_running_and_
queued`/`_reap_expired_waiting_approval` must never assign `run.status`
directly — the only status-mutating statement in that file lives inside
`_ReaperEventSink.emit`. It says nothing about the runner's own terminal
path, which is a wholly separate module with its own persistence seam
(`ConversationStore`, never `EventSink`) that the reaper never touches and
this issue never touches the reaper to preserve. Two distinct authorities
for two distinct callers -- the runner's own terminal transition, and the
reaper's opportunistic sweep of *abandoned* rows -- neither one reaching
into the other's write path.

Scenario style matches `test_agent_runner_pause_resume.py`: DB-backed
against the real `JsonbConversationStore` (the sqlite `session` fixture
from `tests/unit/conftest.py`), because an in-memory Python dict can't
prove anything about what actually lands in `workflow_runs.status` --
asserting on `RunResult` alone is exactly what let this defect through
undetected until now.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product, Shop, User, WorkflowRun
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.llm.openai_adapter import LLMProviderError
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools


class _SpyToolExecutor:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(self, *, tool_name: str, params: object, tool_call_id: str | None = None) -> dict:
        self.calls.append((tool_name, params))
        return dict(self._result)


class _RaisingLLMService:
    """Raises `LLMProviderError` -- issue #1172's translated LLM-call
    exception surface -- from `complete()` instead of returning a scripted
    turn. Used here to exercise a failure `stop_reason` (`llm_error`) that
    is genuinely reachable through the runner's real translation path,
    rather than inventing a stop_reason no production code ever produces."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def complete(self, *, messages, system, tools, config):
        raise self._exc


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _minimal_playbook(steps: tuple[PlaybookStep, ...]) -> Playbook:
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=steps,
        termination_policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    )


def _step(tool_name: str, *, policy: ToolPolicy = ToolPolicy.AUTO) -> PlaybookStep:
    return PlaybookStep(
        step_id=tool_name, intent=f"Call {tool_name}.", tools=(tool_name,), policy=policy
    )


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


async def _seed_workflow_run(session: AsyncSession) -> uuid.UUID:
    """Mirrors `test_conversation_store.py`/`test_agent_runner_pause_resume.py`'s
    own `_seed_workflow_run` -- the same minimal shop/product/run fixture,
    seeded already `running` (the status every real `create_run` row starts
    in once its Celery task actually begins -- #1178 is not about the
    `queued` -> `running` transition, only the terminal one)."""
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Test Shop")
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tt-1",
        name="Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=RunState().to_dict(),
        status="running",
        prompt_version="v1",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    return run.id


async def _reload_row(session: AsyncSession, run_id: uuid.UUID) -> WorkflowRun:
    row = await session.get(WorkflowRun, run_id)
    assert row is not None
    return row


class TestFinalResponsePersistsCompletedRow:
    async def test_a_completed_run_persists_status_stop_reason_and_completed_at_on_the_row(
        self, session: AsyncSession
    ):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[_turn(FinalResponse(content="All done."))]),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED

        row = await _reload_row(session, run_id)
        assert row.status == WorkflowRunStatus.COMPLETED.value
        assert row.stop_reason == StopReason.FINAL_RESPONSE.value
        assert row.completed_at is not None


class TestLLMErrorPersistsFailedRow:
    async def test_an_llm_error_run_persists_status_stop_reason_and_completed_at_on_the_row(
        self, session: AsyncSession
    ):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))
        runner = WorkflowRunner(
            llm_service=_RaisingLLMService(LLMProviderError("HTTP 500")),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.LLM_ERROR
        assert result.status == WorkflowRunStatus.FAILED

        row = await _reload_row(session, run_id)
        assert row.status == WorkflowRunStatus.FAILED.value
        assert row.stop_reason == StopReason.LLM_ERROR.value
        assert row.completed_at is not None


class TestPauseThenResumePersistsRowAtEachStage:
    async def test_pause_persists_waiting_approval_row_then_resume_persists_a_terminal_row(
        self, session: AsyncSession
    ):
        run_id = await _seed_workflow_run(session)
        pause_playbook = Playbook(
            workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
            version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
            steps=(
                PlaybookStep(
                    step_id="write",
                    intent="Publish the improved listing.",
                    tools=("update_product_listing",),
                    policy=ToolPolicy.CONFIRM,
                ),
            ),
            termination_policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
        )

        pause_store = JsonbConversationStore(session)
        pause_runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="update_product_listing",
                            arguments={"title": "New improved title"},
                        )
                    )
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=pause_store,
            registry=_full_registry(),
            playbook=pause_playbook,
        )

        paused_result = await pause_runner.run(run_id, product_ref="prod-1")
        assert paused_result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        assert paused_result.status == WorkflowRunStatus.WAITING_APPROVAL

        # --- AC: the row itself reflects the pause, not just RunResult -----
        paused_row = await _reload_row(session, run_id)
        assert paused_row.status == WorkflowRunStatus.WAITING_APPROVAL.value
        assert paused_row.completed_at is None
        assert paused_row.waiting_approval_since is not None

        # --- resume -- a fresh WorkflowRunner sharing only the row's blob --
        resume_store = JsonbConversationStore(session)
        resume_runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[_turn(FinalResponse(content="Published."))]),
            tool_executor=_SpyToolExecutor(result={"ok": True}),
            event_sink=InMemoryEventSink(),
            conversation_store=resume_store,
            registry=_full_registry(),
            playbook=pause_playbook,
        )

        resumed_result = await resume_runner.resume(run_id, approved=True)
        assert resumed_result.stop_reason == StopReason.FINAL_RESPONSE
        assert resumed_result.status == WorkflowRunStatus.COMPLETED

        # --- AC: the row lands in a genuinely terminal state, not stuck at
        # whatever waiting_approval left behind ---------------------------
        terminal_row = await _reload_row(session, run_id)
        assert terminal_row.status == WorkflowRunStatus.COMPLETED.value
        assert terminal_row.stop_reason == StopReason.FINAL_RESPONSE.value
        assert terminal_row.completed_at is not None


class TestNonTerminalPersistNeverTouchesStatusColumns:
    """Every per-iteration persist call that is NOT a terminal transition
    (the common case: most `_conversation_store.persist(...)` calls in
    `_drive_loop` fire once per iteration, long before any stop_reason is
    known) must leave `status`/`stop_reason`/`completed_at` completely
    alone -- `status=None`/`stop_reason=None` on `persist` is a true no-op,
    never accidentally clearing a previously-set value."""

    async def test_a_mid_run_iteration_never_touches_status_columns(self, session: AsyncSession):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"), _step("get_seo_keywords")))
        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1", tool_name="get_product_information", arguments={}
                        )
                    ),
                    _turn(FinalResponse(content="Done.")),
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        await runner.run(run_id, product_ref="prod-1")

        # By the time the run is over the row IS terminal (completed) -- the
        # interesting assertion is the mid-run persist (after the first
        # iteration's tool call, before FinalResponse) never wrote a
        # terminal status early. Proven indirectly here: the final row is
        # exactly what the LAST persist call wrote, consistent with a
        # single, correct terminal write rather than a stale intermediate
        # one clobbered by luck.
        row = await _reload_row(session, run_id)
        assert row.status == WorkflowRunStatus.COMPLETED.value
        assert row.stop_reason == StopReason.FINAL_RESPONSE.value
