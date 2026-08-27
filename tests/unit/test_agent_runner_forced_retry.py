"""Forced retry logic for incomplete required_steps (ADR-088 decision 1, 2, 4).

Tests the bounded forced-retry mechanism that ensures a text-only turn with
incomplete required_steps is not terminal, and the model is re-invoked once
with `tool_choice="required"` to provide either a required tool call or the
terminal `conclude_without_changes` tool.

These are the deterministic tests newly possible once the runner owns the
invariant (ADR-088 decision 4): per-PR, fake LLM, no API key/network/sandbox.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from juli_backend.integrations.tiktok.factories import ProductionReadResources
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import (
    AssistantTurn,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools

# --- shared fixtures / doubles ------------------------------------------------


class _InMemoryConversationStore:
    """A minimal `ConversationStore` double for testing."""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, RunState] = {}
        self._status: dict[uuid.UUID, WorkflowRunStatus] = {}
        self._stop_reason: dict[uuid.UUID, StopReason] = {}
        self._required_steps_completed: dict[uuid.UUID, bool | None] = {}
        self._running_seconds_elapsed: dict[uuid.UUID, int | None] = {}
        self._pending_confirmations: dict[uuid.UUID, list] = {}
        self._durable_calls: list[uuid.UUID] = []

    def seed(self, workflow_run_id: uuid.UUID, state: RunState | None = None) -> None:
        self._store[workflow_run_id] = state if state is not None else RunState()

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self._store[workflow_run_id]
        if state.prompt_version is None:
            state.prompt_version = "optimize_product.v1"
        if state.prompt_sha256 is None:
            state.prompt_sha256 = "0" * 64
        return state

    async def persist(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        *,
        status: WorkflowRunStatus | None = None,
        stop_reason: StopReason | None = None,
        required_steps_completed: bool | None = None,
        running_seconds_elapsed: int | None = None,
        pending_confirmation=None,
        durable: bool = False,
    ) -> None:
        self._store[workflow_run_id] = state
        if running_seconds_elapsed is not None:
            self._running_seconds_elapsed[workflow_run_id] = running_seconds_elapsed
        if status is not None:
            self._status[workflow_run_id] = status
            self._stop_reason[workflow_run_id] = stop_reason
            self._required_steps_completed[workflow_run_id] = required_steps_completed


def _full_registry_with_terminal() -> ToolRegistry:
    """Registry with all product tools plus the terminal tool."""
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


@pytest.fixture
def conversation_store():
    return _InMemoryConversationStore()


@pytest.fixture
def event_sink():
    return InMemoryEventSink()


@pytest.fixture
def fake_resources():
    """Stubbed ProductionReadResources for testing."""
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=None,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


# --- tests -------------------------------------------------------------------


class TestTextOnlyWithIncompleteRequiredSteps:
    """Text-only turn with incomplete required_steps and remaining budget
    does not terminate; exactly one forced re-invocation occurs with
    tool_choice="required"."""

    async def test_text_only_triggers_forced_retry(
        self, conversation_store, event_sink, fake_resources
    ):
        """A text-only turn (no FinalResponse, no tool call) with incomplete
        required_steps should not terminate the run. Instead, the runner
        should make exactly one re-invocation with tool_choice="required"."""
        workflow_run_id = uuid.uuid4()
        conversation_store.seed(workflow_run_id)

        # Script: first turn is text-only, second turn has conclude_without_changes
        fake_llm = FakeLLMService(
            script=[
                # First turn: just text (no terminal block, no tool call)
                AssistantTurn(
                    blocks=(FinalResponse(content="Analyzing the product..."),),
                    usage=Usage(0, 0),
                ),
                # Second turn: conclude_without_changes (forced retry)
                AssistantTurn(
                    blocks=(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="conclude_without_changes",
                            arguments={"reason": "Product is already well optimized"},
                        ),
                    ),
                    usage=Usage(0, 0),
                ),
            ]
        )

        registry = _full_registry_with_terminal()
        runner = WorkflowRunner(
            llm_service=fake_llm,
            tool_executor=ProductToolExecutor(
                registry=registry,
                read_resources=fake_resources,
                product_id="test_product",
            ),
            event_sink=event_sink,
            conversation_store=conversation_store,
            registry=registry,
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            clock=lambda: 0.0,
        )

        result = await runner.run(workflow_run_id, product_ref="test_product")

        # Verify the run terminated with concluded_without_changes
        assert result.stop_reason == StopReason.CONCLUDED_WITHOUT_CHANGES
        assert result.status == WorkflowRunStatus.COMPLETED

        # Verify exactly 2 calls were made (original + forced retry)
        assert len(fake_llm.recorded_calls) == 2

        # Verify the second call (forced retry) had tool_choice="required"
        second_call = fake_llm.recorded_calls[1]
        assert second_call.tool_choice == "required"

    async def test_text_only_with_no_budget_doesnt_retry(
        self, conversation_store, event_sink, fake_resources
    ):
        """If a text-only turn with incomplete required_steps occurs when
        iteration budget is exhausted (including all extensions), it should NOT
        trigger a retry. The loop should terminate with iteration_cap_exceeded."""
        workflow_run_id = uuid.uuid4()
        state = RunState()
        # Set iteration count to reach the hard cap (6 + 1*2 = 8 after extension)
        # extensions_granted maxed out means no more extensions available
        state.iteration_count = 8
        state.extensions_granted = 1  # max_extensions for optimize_product
        conversation_store.seed(workflow_run_id, state)

        # Script: just text-only response
        fake_llm = FakeLLMService(
            script=[
                # No turns needed - iteration gate stops before complete() is called
            ]
        )

        registry = _full_registry_with_terminal()
        runner = WorkflowRunner(
            llm_service=fake_llm,
            tool_executor=ProductToolExecutor(
                registry=registry,
                read_resources=fake_resources,
                product_id="test_product",
            ),
            event_sink=event_sink,
            conversation_store=conversation_store,
            registry=registry,
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            clock=lambda: 0.0,
        )

        result = await runner.run(workflow_run_id, product_ref="test_product")

        # Verify the run terminated with iteration_cap_exceeded
        # (the iteration gate stops at the top of the next iteration)
        assert result.stop_reason == StopReason.ITERATION_CAP_EXCEEDED
        assert result.status == WorkflowRunStatus.TIMED_OUT

        # No LLM calls (iteration gate stops before any call)
        assert len(fake_llm.recorded_calls) == 0


class TestConcludeWithoutChangesOutcome:
    """conclude_without_changes call terminates with proper stop_reason and
    performs no write of any kind."""

    async def test_conclude_without_changes_stop_reason(
        self, conversation_store, event_sink, fake_resources
    ):
        """A conclude_without_changes tool call results in
        stop_reason=concluded_without_changes."""
        workflow_run_id = uuid.uuid4()
        conversation_store.seed(workflow_run_id)

        fake_llm = FakeLLMService(
            script=[
                AssistantTurn(
                    blocks=(
                        ToolCallBlock(
                            call_id="c1",
                            tool_name="conclude_without_changes",
                            arguments={"reason": "Already optimized"},
                        ),
                    ),
                    usage=Usage(0, 0),
                ),
            ]
        )

        registry = _full_registry_with_terminal()
        runner = WorkflowRunner(
            llm_service=fake_llm,
            tool_executor=ProductToolExecutor(
                registry=registry,
                read_resources=fake_resources,
                product_id="test_product",
            ),
            event_sink=event_sink,
            conversation_store=conversation_store,
            registry=registry,
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            clock=lambda: 0.0,
        )

        result = await runner.run(workflow_run_id, product_ref="test_product")

        assert result.stop_reason == StopReason.CONCLUDED_WITHOUT_CHANGES
        assert result.status == WorkflowRunStatus.COMPLETED


class TestNoRetryWhenRequiredStepsComplete:
    """Required steps already complete -> no retry fires (guard against
    breaking healthy runs)."""

    async def test_complete_required_steps_no_retry(
        self, conversation_store, event_sink, fake_resources
    ):
        """When required_steps are already complete, a text-only turn should
        still be terminal, without triggering a retry."""
        workflow_run_id = uuid.uuid4()
        state = RunState()
        # Simulate required steps already completed:
        # Add tool result entries for both required tools
        state.conversation_window = [
            {"role": "user", "content": "Optimize this product"},
            {
                "role": "assistant",
                "content": "I'll help optimize this product.",
            },
            {
                "role": "assistant",
                "tool_call": {
                    "call_id": "tc1",
                    "tool_name": "update_product_listing",
                    "arguments": {"title": "New title"},
                },
            },
            {
                "role": "tool",
                "tool_name": "update_product_listing",
                "content": {"success": True},
            },
            {
                "role": "assistant",
                "tool_call": {
                    "call_id": "tc2",
                    "tool_name": "update_product_price",
                    "arguments": {"price": 100},
                },
            },
            {
                "role": "tool",
                "tool_name": "update_product_price",
                "content": {"success": True},
            },
        ]
        conversation_store.seed(workflow_run_id, state)

        # Only one turn needed - no retry because required steps are complete
        fake_llm = FakeLLMService(
            script=[
                # Text-only response with final response, required steps are complete
                AssistantTurn(
                    blocks=(
                        TextBlock(text="Done!"),
                        FinalResponse(content="Optimization complete!"),
                    ),
                    usage=Usage(0, 0),
                ),
            ]
        )

        registry = _full_registry_with_terminal()
        runner = WorkflowRunner(
            llm_service=fake_llm,
            tool_executor=ProductToolExecutor(
                registry=registry,
                read_resources=fake_resources,
                product_id="test_product",
            ),
            event_sink=event_sink,
            conversation_store=conversation_store,
            registry=registry,
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            clock=lambda: 0.0,
        )

        result = await runner.run(workflow_run_id, product_ref="test_product")

        # Verify it terminated as final_response (not forced retry)
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED

        # Only one LLM call (no retry)
        assert len(fake_llm.recorded_calls) == 1
        # No tool_choice in first call
        assert fake_llm.recorded_calls[0].tool_choice is None


class TestNoCallAfterForcedRetry:
    """Never calls anything -> stop_reason=required_steps_unfulfilled,
    never final_response."""

    async def test_no_call_after_forced_retry(self, conversation_store, event_sink, fake_resources):
        """When the model produces no call (neither tool nor conclude_without_changes)
        across both the original and forced-retry turns, the run should terminate
        with required_steps_unfulfilled."""
        workflow_run_id = uuid.uuid4()
        conversation_store.seed(workflow_run_id)

        # Script: text-only on both turns (original + retry)
        fake_llm = FakeLLMService(
            script=[
                # First turn: just text
                AssistantTurn(
                    blocks=(FinalResponse(content="Hmm, let me think..."),),
                    usage=Usage(0, 0),
                ),
                # Second turn (forced retry): still just text, no call
                AssistantTurn(
                    blocks=(FinalResponse(content="I need more time to analyze..."),),
                    usage=Usage(0, 0),
                ),
            ]
        )

        registry = _full_registry_with_terminal()
        runner = WorkflowRunner(
            llm_service=fake_llm,
            tool_executor=ProductToolExecutor(
                registry=registry,
                read_resources=fake_resources,
                product_id="test_product",
            ),
            event_sink=event_sink,
            conversation_store=conversation_store,
            registry=registry,
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
            clock=lambda: 0.0,
        )

        result = await runner.run(workflow_run_id, product_ref="test_product")

        # Verify termination with required_steps_unfulfilled, never final_response
        assert result.stop_reason == StopReason.REQUIRED_STEPS_UNFULFILLED
        assert result.status == WorkflowRunStatus.FAILED

        # Both turns should have been invoked
        assert len(fake_llm.recorded_calls) == 2
        # Second call should have tool_choice="required"
        assert fake_llm.recorded_calls[1].tool_choice == "required"


class TestAdapterShapeMatchesTheRetryTrigger:
    """The coupling that broke ADR-088 in production.

    The forced retry must trigger on the block shape the REAL adapter emits
    when the model declines to act. An earlier revision gated it on a
    TextBlock-only turn, which `_parse_output_blocks` never produces in that
    case — with no `function_call` items it emits a `FinalResponse`. The retry
    was therefore unreachable in production while every test here passed,
    because the fake LLM emits whatever block the test constructs.

    Run `2c961380-3218-464a-90d1-cd5940abea83` terminated `final_response`
    with `required_steps_completed=false` and no retry attempted.

    These two tests pin the two halves of the coupling so it cannot silently
    come apart again: what the adapter emits, and what the runner reacts to.
    """

    def test_adapter_emits_final_response_when_the_model_calls_no_tool(self):
        from juli_backend.services.agent.llm.openai_adapter import _parse_output_blocks

        blocks = _parse_output_blocks(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "I'll prepare an update."}],
                    }
                ]
            }
        )

        assert len(blocks) == 1
        assert isinstance(blocks[0], FinalResponse), (
            "the runner arms its forced retry on FinalResponse; if the adapter "
            "starts emitting a bare TextBlock here instead, the retry goes dead "
            "in production while the fake-LLM tests keep passing"
        )

    def test_adapter_emits_text_plus_tool_call_when_the_model_does_act(self):
        from juli_backend.services.agent.llm.openai_adapter import _parse_output_blocks

        blocks = _parse_output_blocks(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Updating now."}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "get_product_information",
                        "arguments": "{}",
                    },
                ]
            }
        )

        assert [type(b).__name__ for b in blocks] == ["TextBlock", "ToolCallBlock"], (
            "narration accompanying a tool call must stay a TextBlock — it is "
            "interim commentary, not a decision to stop, and must not arm the retry"
        )


class TestPartialProgressTerminatesFinalResponse:
    """#1383: a run that acted on SOME required steps and then narrated ends
    `final_response`, not `required_steps_unfulfilled`.

    ADR-073 d.2 protects that outcome by name. Gate #1226 walk run 675bb11e
    did the listing change, declined the price change because inventory is 0 —
    a correct judgement — and was recorded `failed`.

    The playbook here declares a single AUTO required step so the scenario can
    complete one without a CONFIRM pause; the classification logic under test
    is identical either way, and the two-write production policy is covered by
    the unit-level scan tests in
    `test_agent_partial_progress_is_not_failure.py`.
    """

    async def _run(self, conversation_store, event_sink, fake_resources, *, required):
        workflow_run_id = uuid.uuid4()
        conversation_store.seed(workflow_run_id)
        registry = _full_registry_with_terminal()

        class _Products:
            """Minimal stub — the shared fixture leaves products None, and
            this scenario must actually complete a required read."""

            def get_details(self, product_id):
                return {
                    "id": product_id,
                    "title": "Nồi lẩu điện mini 1.5L",
                    "description": "<p>mô tả</p>",
                    "status": "ACTIVATE",
                    "skus": [],
                    "main_images": [],
                }

        resources = replace(fake_resources, products=_Products())
        playbook = replace(
            OPTIMIZE_PRODUCT_PLAYBOOK,
            termination_policy=replace(
                OPTIMIZE_PRODUCT_TERMINATION_POLICY, required_steps=required
            ),
        )
        fake_llm = FakeLLMService(
            script=[
                # Perform the required step.
                AssistantTurn(
                    blocks=(
                        ToolCallBlock(
                            call_id="c1", tool_name="get_product_information", arguments={}
                        ),
                    ),
                    usage=Usage(0, 0),
                ),
                # Then narrate — arms the one forced retry.
                AssistantTurn(
                    blocks=(FinalResponse(content="Đã cập nhật xong."),), usage=Usage(0, 0)
                ),
                # And narrate again after it.
                AssistantTurn(
                    blocks=(FinalResponse(content="Không còn gì để đề xuất."),), usage=Usage(0, 0)
                ),
            ]
        )
        runner = WorkflowRunner(
            llm_service=fake_llm,
            tool_executor=ProductToolExecutor(
                registry=registry, read_resources=resources, product_id="test_product"
            ),
            event_sink=event_sink,
            conversation_store=conversation_store,
            registry=registry,
            playbook=playbook,
            clock=lambda: 0.0,
        )
        return await runner.run(workflow_run_id, product_ref="test_product")

    async def test_some_progress_then_narration_is_final_response(
        self, conversation_store, event_sink, fake_resources
    ):
        result = await self._run(
            conversation_store,
            event_sink,
            fake_resources,
            required=("get_product_information", "update_product_price"),
        )

        assert result.stop_reason == StopReason.FINAL_RESPONSE, (
            "one of two required steps done and the rest honestly declined is "
            "ADR-073 d.2's honest outcome, not a failure"
        )
        assert result.status == WorkflowRunStatus.COMPLETED

    async def test_zero_progress_then_narration_still_fails(
        self, conversation_store, event_sink, fake_resources
    ):
        """Non-vacuity: ADR-088's defect signal must survive #1383."""
        result = await self._run(
            conversation_store,
            event_sink,
            fake_resources,
            required=("update_product_listing", "update_product_price"),
        )

        assert result.stop_reason == StopReason.REQUIRED_STEPS_UNFULFILLED
