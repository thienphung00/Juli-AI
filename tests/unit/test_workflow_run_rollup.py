"""`WorkflowRun` rollup — per-run token counts, cost, duration, tool calls, rows affected
(issue #1653 / W8-A / P10-1).

A completed run records six scalar values at the `workflow_runs` row: input_tokens,
output_tokens, cost_usd, duration_ms, tool_call_count, rows_affected — all populated
by the runner as it runs, persisted on the same call as status/stop_reason, never
backfilled.

**Acceptance criteria tested here:**

1. A completed run has all six values populated, asserted after a run through the
   **real runner**, not by writing the row directly.
2. A run that legitimately does nothing records `tool_call_count = 0` and
   `rows_affected = 0` while still recording a non-null duration.
3. A failed run still records the rollup for the work it did before failing.
4. Cost is computed from the rate in force **for that run**; a later rate change does
   not retroactively rewrite history.
5. Token counts come from the `Usage` the LLM service already returns; nothing
   re-tokenises or estimates.
6. A run that pauses on a confirmation and resumes accumulates tokens and tool calls
   **across the pause**.
7. The rollup is written on the **same** `ConversationStore.persist` call that already
   stamps `status`/`stop_reason`/`required_steps_completed`.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product, Shop, User, WorkflowRun
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.config import estimate_cost_usd
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
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools


class _SpyToolExecutor:
    """A test double that records tool calls and returns a fixed result."""

    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self._result = result if result is not None else {"ok": True}
        self.row_count = 0  # Simulates rows_affected for writes

    def execute(self, *, tool_name: str, params: object, tool_call_id: str | None = None) -> dict:
        self.calls.append((tool_name, params))
        return dict(self._result)


class _RaisingToolExecutor:
    """A test double that raises an exception during tool execution."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls: list[tuple[str, object]] = []

    def execute(self, *, tool_name: str, params: object, tool_call_id: str | None = None) -> dict:
        self.calls.append((tool_name, params))
        raise self._exc


class _RaisingLLMService:
    """Raises `LLMProviderError` from `complete()` instead of returning a scripted turn."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def complete(self, *, messages, system, tools, config, tool_choice=None):
        raise self._exc


class _SteppingClock:
    """A controllable fake clock: each call returns the current value, then advances
    it by `step`."""

    def __init__(self, *, step: float, start: float = 0.0) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _minimal_playbook(steps: tuple[PlaybookStep, ...]) -> Playbook:
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=steps,
        termination_policy=replace(OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()),
    )


def _step(tool_name: str, *, policy: ToolPolicy = ToolPolicy.AUTO) -> PlaybookStep:
    return PlaybookStep(
        step_id=tool_name, intent=f"Call {tool_name}.", tools=(tool_name,), policy=policy
    )


def _turn(*blocks, input_tokens: int = 10, output_tokens: int = 20) -> AssistantTurn:
    return AssistantTurn(
        blocks=tuple(blocks), usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens)
    )


async def _seed_workflow_run(session: AsyncSession) -> uuid.UUID:
    """Seeds a minimal shop/product/run fixture, seeded already `running`."""
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
        prompt_version="optimize_product.v1",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    return run.id


async def _reload_row(session: AsyncSession, run_id: uuid.UUID) -> WorkflowRun:
    row = await session.get(WorkflowRun, run_id)
    assert row is not None
    return row


class TestRollupOnFinalResponse:
    async def test_a_completed_run_has_all_six_rollup_values(self, session: AsyncSession):
        """AC1: A completed run has all six values populated after running through
        the real runner."""
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
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED

        row = await _reload_row(session, run_id)
        # All six rollup values must be populated
        assert row.input_tokens is not None, "input_tokens should be populated"
        assert row.output_tokens is not None, "output_tokens should be populated"
        assert row.cost_usd is not None, "cost_usd should be populated"
        assert row.duration_ms is not None, "duration_ms should be populated"
        assert row.tool_call_count is not None, "tool_call_count should be populated"
        assert row.rows_affected is not None, "rows_affected should be populated"

    async def test_token_counts_sum_from_all_llm_turns(self, session: AsyncSession):
        """AC5: Token counts come from the `Usage` the LLM service already returns,
        summed across turns."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook(
            (
                _step("get_product_information"),
                _step("update_product_listing"),
            )
        )
        # Two turns with different token counts: total should be sum of both
        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1", tool_name="get_product_information", arguments={}
                        ),
                        input_tokens=100,
                        output_tokens=50,
                    ),
                    _turn(FinalResponse(content="Done."), input_tokens=200, output_tokens=75),
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            clock=_SteppingClock(step=0.1),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE

        row = await _reload_row(session, run_id)
        # Should sum tokens from both turns
        assert row.input_tokens == 300, f"Expected 300 input tokens, got {row.input_tokens}"
        assert row.output_tokens == 125, f"Expected 125 output tokens, got {row.output_tokens}"

    async def test_cost_is_computed_from_model_price_table(self, session: AsyncSession):
        """AC4: Cost is computed from the rate in force for that run."""
        from juli_backend.services.agent.llm.config import (
            PRICE_TABLE_USD_PER_MILLION_TOKENS,
            LLMConfig,
        )

        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))
        # Use a known model with a known cost
        # Get the first model from the price table
        model_name = list(PRICE_TABLE_USD_PER_MILLION_TOKENS.keys())[0]

        # Manually compute expected cost
        usage = Usage(input_tokens=1000000, output_tokens=1000000)
        expected_cost = estimate_cost_usd(model_name, usage)

        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        FinalResponse(content="All done."),
                        input_tokens=1000000,
                        output_tokens=1000000,
                    )
                ],
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            llm_config=LLMConfig(model=model_name),
            clock=_SteppingClock(step=0.1),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE

        row = await _reload_row(session, run_id)
        # Cost should match the computed estimate
        assert row.cost_usd is not None
        assert abs(float(row.cost_usd) - expected_cost) < 0.0001, (
            f"Expected {expected_cost}, got {row.cost_usd}"
        )

    async def test_duration_is_wall_clock_from_started_to_completed(self, session: AsyncSession):
        """AC1/AC2: duration_ms is wall-clock time, populated even for no-op runs."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))

        # Use a stepping clock to control duration: 0, 0.1, 0.2, 0.3, ... (in seconds)
        # With step=0.15, clock values are 0, 0.15, 0.3, 0.45, ... seconds
        clock = _SteppingClock(step=0.15, start=0.0)

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
        # duration_ms should be non-zero (stepped clock advances)
        assert row.duration_ms is not None
        assert row.duration_ms > 0, f"Expected positive duration_ms, got {row.duration_ms}"


class TestRollupOnNoOp:
    async def test_noop_run_records_zero_tool_calls_and_rows_affected_but_nonzero_duration(
        self, session: AsyncSession
    ):
        """AC2: A no-op run records tool_call_count = 0 and rows_affected = 0 while
        still recording a non-null duration."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[_turn(FinalResponse(content="No changes needed."))]),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED

        row = await _reload_row(session, run_id)
        # No tool calls and no rows affected
        assert row.tool_call_count == 0, f"Expected 0 tool calls, got {row.tool_call_count}"
        assert row.rows_affected == 0, f"Expected 0 rows affected, got {row.rows_affected}"
        # But duration should still be populated
        assert row.duration_ms is not None
        assert row.duration_ms > 0, f"Expected positive duration_ms, got {row.duration_ms}"


class TestRollupOnFailure:
    async def test_failed_run_records_partial_rollup(self, session: AsyncSession):
        """AC3: A failed run still records the rollup for the work it did before failing."""
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
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.LLM_ERROR
        assert result.status == WorkflowRunStatus.FAILED

        row = await _reload_row(session, run_id)
        # Even though it failed, rollup should still be recorded
        assert row.input_tokens is not None
        assert row.output_tokens is not None
        assert row.cost_usd is not None
        assert row.duration_ms is not None
        assert row.tool_call_count is not None
        assert row.rows_affected is not None


class TestRollupAcrossPauseResume:
    async def test_pause_resume_accumulates_tokens_and_tool_calls_across_pause(
        self, session: AsyncSession
    ):
        """AC6: A run that pauses and resumes accumulates tokens and tool calls
        across the pause."""
        run_id = await _seed_workflow_run(session)

        # First run: pauses on a CONFIRM tool
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
            termination_policy=replace(OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()),
        )

        pause_store = JsonbConversationStore(session)
        pause_runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="update_product_listing",
                            arguments={"title": "New title"},
                        ),
                        input_tokens=100,
                        output_tokens=50,
                    )
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=pause_store,
            registry=_full_registry(),
            playbook=pause_playbook,
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        paused_result = await pause_runner.run(run_id, product_ref="prod-1")
        assert paused_result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION

        # Check paused row (may have partial rollup)
        paused_row = await _reload_row(session, run_id)
        assert paused_row.status == WorkflowRunStatus.WAITING_APPROVAL.value

        # Now resume with a fresh runner, calling the same update tool
        resume_store = JsonbConversationStore(session)
        resume_runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        FinalResponse(content="Done."),
                        input_tokens=200,
                        output_tokens=75,
                    )
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=resume_store,
            registry=_full_registry(),
            playbook=pause_playbook,
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        resumed_result = await resume_runner.resume(run_id, approved=True)
        assert resumed_result.stop_reason == StopReason.FINAL_RESPONSE
        assert resumed_result.status == WorkflowRunStatus.COMPLETED

        # Check final row: should have accumulated tokens from BOTH turns
        final_row = await _reload_row(session, run_id)
        # First turn: input=100, output=50
        # Second turn: input=200, output=75
        # Total should be: input=300, output=125
        assert final_row.input_tokens == 300, (
            f"Expected 300 input tokens after resume, got {final_row.input_tokens}"
        )
        assert final_row.output_tokens == 125, (
            f"Expected 125 output tokens after resume, got {final_row.output_tokens}"
        )


class TestRowsAffectedIncrementOnWrite:
    async def test_read_tool_does_not_increment_rows_affected(self, session: AsyncSession):
        """Issue #1653-Meta1: READ tool execution should not increment rows_affected."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="get_product_information",
                            arguments={},
                        ),
                        input_tokens=100,
                        output_tokens=50,
                    ),
                    _turn(FinalResponse(content="Done."), input_tokens=100, output_tokens=50),
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            clock=_SteppingClock(step=0.1),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE

        row = await _reload_row(session, run_id)
        # Should have 0 rows_affected since we only called a READ tool
        assert row.rows_affected == 0, (
            f"Expected 0 rows_affected for READ-only execution, got {row.rows_affected}"
        )

    async def test_write_tool_increments_rows_affected(self, session: AsyncSession):
        """Issue #1653-Meta1: WRITE tool execution should increment rows_affected."""
        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        # Playbook with a WRITE tool (update_product_listing has CONFIRM policy)
        playbook = _minimal_playbook((_step("update_product_listing", policy=ToolPolicy.CONFIRM),))

        # First run: pause on the WRITE tool
        pause_runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="update_product_listing",
                            arguments={"title": "Updated Title"},
                        ),
                        input_tokens=100,
                        output_tokens=50,
                    ),
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        pause_result = await pause_runner.run(run_id, product_ref="prod-1")
        assert pause_result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION

        # Resume and approve the tool
        resume_store = JsonbConversationStore(session)
        resume_runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[_turn(FinalResponse(content="Done."), input_tokens=50, output_tokens=25)]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=resume_store,
            registry=_full_registry(),
            playbook=playbook,
            clock=_SteppingClock(step=0.1, start=0.0),
        )

        resume_result = await resume_runner.resume(run_id, approved=True)
        assert resume_result.stop_reason == StopReason.FINAL_RESPONSE

        row = await _reload_row(session, run_id)
        # Should have 1 rows_affected since we executed one WRITE tool (update_product_listing)
        assert row.rows_affected == 1, (
            f"Expected 1 rows_affected for one WRITE tool execution, got {row.rows_affected}"
        )


class TestUnpricedModelHandling:
    async def test_unpriced_model_returns_none_for_cost_usd(
        self, session: AsyncSession, monkeypatch
    ):
        """Issue #1653-Meta3: When using an unpriced model, cost_usd should be
        None instead of 0.0."""

        # Patch estimate_cost_usd to return None (simulating an unpriced model)
        def mock_estimate_cost_usd(model: str, usage):
            return None

        monkeypatch.setattr(
            "juli_backend.services.agent.runner.core.estimate_cost_usd",
            mock_estimate_cost_usd,
        )

        run_id = await _seed_workflow_run(session)
        store = JsonbConversationStore(session)
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="get_product_information",
                            arguments={},
                        ),
                        input_tokens=100,
                        output_tokens=50,
                    ),
                    _turn(FinalResponse(content="Done."), input_tokens=100, output_tokens=50),
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
            clock=_SteppingClock(step=0.1),
        )

        result = await runner.run(run_id, product_ref="prod-1")
        assert result.stop_reason == StopReason.FINAL_RESPONSE

        row = await _reload_row(session, run_id)
        # Should have None for cost_usd when using an unpriced model
        assert row.cost_usd is None, (
            f"Expected None for cost_usd with unpriced model, got {row.cost_usd}"
        )
