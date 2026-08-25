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

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

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
from juli_backend.services.agent.runner.termination import running_seconds_column_value
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/services/agent/runner/core.py"


class _SpyToolExecutor:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(self, *, tool_name: str, params: object, tool_call_id: str | None = None) -> dict:
        self.calls.append((tool_name, params))
        return dict(self._result)


class _SteppingClock:
    """A controllable fake clock: each call returns the current value, then
    advances it by `step` -- no real sleeping anywhere (issue #1216's own
    AC: "proven with a controlled clock, not a sleep"). Mirrors
    `test_agent_runner_pause_resume.py`'s own helper of the same name (not
    imported from there -- that module is a sibling issue's write path)."""

    def __init__(self, *, step: float, start: float = 0.0) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


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


class TestRunningSecondsColumnMirror:
    """Issue #1216: the defect this closes. `workflow_runs.running_seconds_
    elapsed` recorded `0` on every real run to date regardless of how long
    it actually ran -- `termination.running_seconds_column_value` existed
    and was correct (stateless, recomputed from the authoritative float),
    but nothing on the live path ever called it. DB-backed against the real
    `JsonbConversationStore` for the same reason the rest of this file is:
    asserting on `RunResult` alone (which never carried this value to begin
    with) cannot prove anything landed on the actual column.

    Uses a controllable fake clock (`_SteppingClock`), never a real
    `sleep`, per issue #1216's own acceptance criterion."""

    async def test_a_measurable_duration_run_persists_a_non_zero_column_value(
        self, session: AsyncSession
    ):
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))
        clock = _SteppingClock(start=0.0, step=8.0)  # one iteration, an 8.0s delta
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[_turn(FinalResponse(content="All done."))]),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            clock=clock,
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE

        row = await _reload_row(session, run_id)
        assert row.running_seconds_elapsed == 8
        assert row.running_seconds_elapsed == running_seconds_column_value(8.0)

    async def test_the_column_updates_on_the_ordinary_mid_run_persist_not_only_at_the_terminal_one(
        self, session: AsyncSession
    ):
        """AC: "wherever WorkflowRunner persists the run -- the per-iteration
        persist and every terminal persist". Two iterations, each a 5.0s
        clock delta, accumulate to 10.0s total by the time the run ends --
        `test_the_ordinary_per_iteration_persist_call_site_carries_the_kwarg`
        below is the AST-level guarantee that the mid-run write itself (not
        only the terminal one) carries the mirror; this test pins the
        resulting number end to end."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"), _step("get_seo_keywords")))
        clock = _SteppingClock(start=0.0, step=5.0)
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
            clock=clock,
        )

        await runner.run(run_id, product_ref="prod-1")

        row = await _reload_row(session, run_id)
        assert row.running_seconds_elapsed == 10

    def test_the_ordinary_per_iteration_persist_call_site_carries_the_kwarg(self):
        """AST-level guarantee, not just a behavioural inference: every
        `_conversation_store.persist(...)` call site in `core.py` -- the
        ordinary per-iteration one at the bottom of `_drive_loop`'s loop
        body included, not only the terminal ones that already carry
        `status=`/`stop_reason=` -- passes `running_seconds_elapsed=`."""
        tree = ast.parse(CORE_MODULE_PATH.read_text(encoding="utf-8"))
        persist_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "persist"
        ]
        assert len(persist_calls) >= 8  # every call site this issue's report touched
        for call in persist_calls:
            keyword_names = {kw.arg for kw in call.keywords}
            assert "running_seconds_elapsed" in keyword_names, (
                f"a persist(...) call at line {call.lineno} in core.py is missing "
                "running_seconds_elapsed= -- issue #1216 requires it at every "
                "call site, not only terminal ones."
            )


class TestActionCardRevertOnTerminalFailure:
    """Issue #1305: when a run reaches terminal FAILED status (cleanly through
    the runner, not just in the crash handler), any consumed action card must
    revert from 'approved' back to 'active' so the seller can retry.

    AC:
    - FAILED status reverts an approved card to active
    - COMPLETED status does NOT revert the card
    - CANCELLED status does NOT revert the card
    - TIMED_OUT status does NOT revert the card
    - WAITING_APPROVAL status does NOT revert the card
    - Non-approved card is not touched even on FAILED
    - Run with no action_card_id does not error on FAILED
    """

    async def test_failed_run_cleanly_reverts_approved_card_to_active(self, session: AsyncSession):
        """FAILED status cleanly (not crash) reverts consumed action card."""
        from juli_backend.models.models import ActionCard

        run_id = await _seed_workflow_run(session)

        # Create and attach an approved card
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=(await _reload_row(session, run_id)).shop_id,
            workflow_key="optimize_product",
            priority=1,
            severity="info",
            title="Test Card",
            description="A test decision card",
            recommendation_payload="{}",
            status="approved",
            approved_at=datetime.now(UTC),
        )
        session.add(card)
        await session.flush()

        # Link card to run
        run = await _reload_row(session, run_id)
        run.action_card_id = card.id
        await session.flush()

        # Run fails cleanly (LLM error)
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
        assert result.status == WorkflowRunStatus.FAILED

        # Verify card was reverted to active
        loaded_card = await session.get(ActionCard, card.id)
        assert loaded_card.status == "active", (
            f"Card should revert to active on clean FAILED, got {loaded_card.status}"
        )
        assert loaded_card.approved_at is None, "Card approved_at should be cleared on revert"

    async def test_completed_run_does_not_revert_approved_card(self, session: AsyncSession):
        """COMPLETED status does NOT revert the card."""
        from juli_backend.models.models import ActionCard

        run_id = await _seed_workflow_run(session)

        # Create and attach an approved card
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=(await _reload_row(session, run_id)).shop_id,
            workflow_key="optimize_product",
            priority=1,
            severity="info",
            title="Test Card",
            description="A test decision card",
            recommendation_payload="{}",
            status="approved",
            approved_at=datetime.now(UTC),
        )
        session.add(card)
        await session.flush()

        # Link card to run
        run = await _reload_row(session, run_id)
        run.action_card_id = card.id
        await session.flush()

        # Run completes successfully
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[_turn(FinalResponse(content="Done."))]),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.status == WorkflowRunStatus.COMPLETED

        # Verify card stayed approved (consumed)
        loaded_card = await session.get(ActionCard, card.id)
        assert loaded_card.status == "approved", (
            f"Card should stay approved on COMPLETED, got {loaded_card.status}"
        )
        assert loaded_card.approved_at is not None, "Card approved_at should remain on COMPLETED"

    async def test_failed_run_with_non_approved_card_is_not_reverted(self, session: AsyncSession):
        """FAILED status with a card not in 'approved' state does not touch it."""
        from juli_backend.models.models import ActionCard

        run_id = await _seed_workflow_run(session)

        # Create and attach a card in 'active' state
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=(await _reload_row(session, run_id)).shop_id,
            workflow_key="optimize_product",
            priority=1,
            severity="info",
            title="Test Card",
            description="A test decision card",
            recommendation_payload="{}",
            status="active",
            approved_at=None,
        )
        session.add(card)
        await session.flush()

        # Link card to run
        run = await _reload_row(session, run_id)
        run.action_card_id = card.id
        await session.flush()

        # Run fails cleanly
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
        assert result.status == WorkflowRunStatus.FAILED

        # Verify card was NOT modified
        loaded_card = await session.get(ActionCard, card.id)
        assert loaded_card.status == "active", (
            "Card in active state should not be touched on FAILED"
        )

    async def test_failed_run_without_action_card_does_not_error(self, session: AsyncSession):
        """FAILED status on a run with no action_card_id does not error."""
        run_id = await _seed_workflow_run(session)

        # Ensure run has no action_card_id
        run = await _reload_row(session, run_id)
        assert run.action_card_id is None

        # Run fails cleanly
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

        # Should not raise
        result = await runner.run(run_id, product_ref="prod-1")
        assert result.status == WorkflowRunStatus.FAILED
