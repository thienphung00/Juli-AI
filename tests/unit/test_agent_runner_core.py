"""`WorkflowRunner` block-dispatch loop — issue #1119 / AGT-W3A (ADR-073
decision 1).

Pure-unit scenario suite against `FakeLLMService` (ADR-071 decision 6) — no
database, no network. Covers every #1119 acceptance criterion: constructor
injection of the four named protocols, per-block event/append counts, the
playbook allowlist's two distinct refusal cases, malformed-params
self-correction (one retry, then give up), the two banned-pattern
chokepoints bracketing the loop, `ProductToolContext` built from bound run
identity only, `compose()`/prompt stamping called exactly once per run, and
the get_product_information -> get_seo_keywords -> FinalResponse happy path.

Marketplace access for the happy path and the `ProductToolContext` test is
via a stubbed `ProductionReadResources` (mirrors
`test_agent_tools_product_read.py`'s fake-resource pattern) — no live calls.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from juli_backend.integrations.tiktok.factories import ProductionReadResources
from juli_backend.services.agent.events import EventSink, InMemoryEventSink
from juli_backend.services.agent.llm import (
    AssistantTurn,
    FinalResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.llm.openai_adapter import LLMProviderError
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.prompts.composer import prompt_sha256, prompt_version
from juli_backend.services.agent.runner.concurrency import ConcurrencyExhaustedError
from juli_backend.services.agent.runner.conversation_store import PendingConfirmationWrite
from juli_backend.services.agent.runner.core import RunResult, WorkflowRunner
from juli_backend.services.agent.runner.ledger import ToolExecutionUnrecoverableError
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/services/agent/runner/core.py"


# --- shared fixtures / doubles ------------------------------------------------


class _InMemoryConversationStore:
    """A minimal `ConversationStore` double — no database, matching the
    protocol shape `test_conversation_store.py`'s own stub uses.

    `persist`'s `status`/`stop_reason` keyword-only parameters (issue #1178)
    are accepted and recorded on `self._status`/`self._stop_reason` — this
    double is exercised by real `WorkflowRunner.run()`/`resume()` calls,
    which pass them at every terminal exit, so a signature that only takes
    `(workflow_run_id, state)` would raise `TypeError` the first time this
    module's own tests reach a terminal `stop_reason`.

    `required_steps_completed` (issue #1220) is accepted and recorded the
    same way, for the same reason: `WorkflowRunner` now passes it at every
    one of those same terminal exits.

    `running_seconds_elapsed` (issue #1216) is accepted and recorded the
    same way -- unlike the three fields above, `WorkflowRunner` now passes
    it on *every* persist call, terminal or not, so a signature omitting it
    would raise `TypeError` on this double's very first `persist` call in
    any scenario, not just one that reaches a terminal `stop_reason`.

    `pending_confirmation` (issue #1221) is accepted and recorded the same
    way -- `WorkflowRunner` now makes a dedicated `persist` call carrying
    it at every CONFIRM pause (`_pause_pending_confirmation`), so a
    signature omitting it would raise `TypeError` the first time this
    module's own tests reach a CONFIRM pause (most of `TestConfirmPause`
    and friends).

    `durable` (issue #1181 / AGT-W5A review round 2) is accepted and
    recorded on `self._durable_calls` for the same reason -- `resume()`'s
    entry-transition persist now passes `durable=True`, so a signature
    omitting it would raise `TypeError` the first time this module's own
    tests reach `resume()` (three `TestConcurrencyConflictTranslation`/
    `TestToolErrorUnrecoverableViaLedgerTranslation`/`TestRequiredSteps
    CompletedPersistence` scenarios do). There is no session for this
    in-memory double to roll back, so the flag has no observable effect on
    `self._store` beyond the write already happening unconditionally --
    `JsonbConversationStore` is what `test_agent_runner_pause_resume.py`
    exercises for the actual durability guarantee."""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, RunState] = {}
        self._status: dict[uuid.UUID, WorkflowRunStatus] = {}
        self._stop_reason: dict[uuid.UUID, StopReason] = {}
        self._required_steps_completed: dict[uuid.UUID, bool | None] = {}
        self._running_seconds_elapsed: dict[uuid.UUID, int | None] = {}
        self._pending_confirmations: dict[uuid.UUID, list[PendingConfirmationWrite]] = {}
        self._durable_calls: list[uuid.UUID] = []

    def seed(self, workflow_run_id: uuid.UUID, state: RunState | None = None) -> None:
        self._store[workflow_run_id] = state if state is not None else RunState()

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self._store[workflow_run_id]
        # Simulate JsonbConversationStore.load() populating prompt_version/
        # prompt_sha256 from the row (issue #1359). In-memory tests don't have
        # a database row, so default to reasonable values if not already set.
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
        pending_confirmation: PendingConfirmationWrite | None = None,
        durable: bool = False,
    ) -> None:
        self._store[workflow_run_id] = state
        if running_seconds_elapsed is not None:
            self._running_seconds_elapsed[workflow_run_id] = running_seconds_elapsed
        if status is not None:
            self._status[workflow_run_id] = status
            self._stop_reason[workflow_run_id] = stop_reason
            self._required_steps_completed[workflow_run_id] = required_steps_completed
        if pending_confirmation is not None:
            self._pending_confirmations.setdefault(workflow_run_id, []).append(pending_confirmation)
        if durable:
            self._durable_calls.append(workflow_run_id)

    def required_steps_completed_for(self, workflow_run_id: uuid.UUID) -> bool | None:
        return self._required_steps_completed[workflow_run_id]

    def running_seconds_elapsed_for(self, workflow_run_id: uuid.UUID) -> int | None:
        return self._running_seconds_elapsed[workflow_run_id]

    def pending_confirmations_for(
        self, workflow_run_id: uuid.UUID
    ) -> list[PendingConfirmationWrite]:
        return self._pending_confirmations.get(workflow_run_id, [])


class _SpyToolExecutor:
    """Records every `execute` call it receives; returns a fixed result."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        # tool_call_id accepted-but-ignored (#1145): core.py now always
        # passes it; this spy's `.calls` assertions stay tool_name/params
        # shaped, unchanged from before #1145.
        self.calls.append((tool_name, params))
        return dict(self._result)


class _RaisingLLMService:
    """`LLMService` double that raises a caller-supplied exception from
    `complete()` instead of returning a scripted turn — issue #1172's fake
    for proving `WorkflowRunner` translates the provider's own typed
    exception surface (or lets an unrelated exception, e.g.
    `asyncio.CancelledError`, propagate untouched) rather than crashing raw
    or swallowing something it must not."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.call_count = 0

    async def complete(self, *, messages: Any, system: str, tools: Any, config: Any) -> Any:
        self.call_count += 1
        raise self._exc


class _RaisingToolExecutor:
    """`ToolExecutor` double that raises a caller-supplied exception from
    `execute()` instead of returning a result — issue #1172's fake for
    proving `WorkflowRunner` translates `ConcurrencyExhaustedError` /
    `ToolExecutionUnrecoverableError` at both dispatch sites
    (`_dispatch_tool_call` and `resume`), and does not swallow an unrelated
    exception such as `asyncio.CancelledError`."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls: list[tuple[str, Any]] = []

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((tool_name, params))
        raise self._exc


class _FakeProductsResource:
    def __init__(self, *, details: dict | None = None) -> None:
        self._details = details or {"title": "A nice widget", "status": "LIVE"}
        self.get_details_calls: list[str] = []
        self.get_seo_words_calls: list[list[str]] = []
        self.get_suggestions_calls: list[list[str]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return self._details

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        self.get_seo_words_calls.append(product_ids)
        return {"products": []}

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        self.get_suggestions_calls.append(product_ids)
        return {"products": []}


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _minimal_playbook(steps: tuple[PlaybookStep, ...]) -> Playbook:
    """A `Playbook` sharing the real `optimize_product_2` workflow_key/version
    (so `compose()` still resolves a real prose binding) but with a
    caller-chosen, deliberately narrower step list — used by the allowlist
    tests to prove a registered-but-unlisted tool is refused."""
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


def _runner(
    *,
    script: list[AssistantTurn],
    tool_executor: Any,
    event_sink: EventSink,
    conversation_store: _InMemoryConversationStore,
    playbook: Playbook,
    registry: ToolRegistry,
) -> WorkflowRunner:
    return WorkflowRunner(
        llm_service=FakeLLMService(script=script),
        tool_executor=tool_executor,
        event_sink=event_sink,
        conversation_store=conversation_store,
        registry=registry,
        playbook=playbook,
    )


# --- AC: constructor injection -------------------------------------------------


class TestConstructorInjection:
    async def test_two_independently_constructed_runners_behave_independently(self):
        run_id_a, run_id_b = uuid.uuid4(), uuid.uuid4()
        store_a, store_b = _InMemoryConversationStore(), _InMemoryConversationStore()
        store_a.seed(run_id_a)
        store_b.seed(run_id_b)
        sink_a, sink_b = InMemoryEventSink(), InMemoryEventSink()
        registry = _full_registry()
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner_a = _runner(
            script=[_turn(FinalResponse(content="Result A"))],
            tool_executor=_SpyToolExecutor(),
            event_sink=sink_a,
            conversation_store=store_a,
            playbook=playbook,
            registry=registry,
        )
        runner_b = _runner(
            script=[_turn(FinalResponse(content="Result B"))],
            tool_executor=_SpyToolExecutor(),
            event_sink=sink_b,
            conversation_store=store_b,
            playbook=playbook,
            registry=registry,
        )

        result_a = await runner_a.run(run_id_a, product_ref="prod-a")
        result_b = await runner_b.run(run_id_b, product_ref="prod-b")

        assert result_a.final_response == "Result A"
        assert result_b.final_response == "Result B"
        assert len(sink_a.events) == len(sink_b.events)  # both ran the same shape
        assert sink_a.events is not sink_b.events


# --- AC: TextBlock -> exactly one event + one conversation append -------------


class TestTextBlockDispatch:
    async def test_text_block_emits_one_event_and_appends_one_message(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(TextBlock(text="Let me check the listing first.")),
                _turn(FinalResponse(content="All done.")),
            ],
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        await runner.run(run_id, product_ref="prod-1")

        text_events = [e for e in sink.events if e.event_type == "assistant.text"]
        assert len(text_events) == 1
        assert text_events[0].payload.text == "Let me check the listing first."

        text_messages = [
            m
            for m in store._store[run_id].conversation_window
            if m.get("role") == "assistant"
            and m.get("content") == "Let me check the listing first."
        ]
        assert len(text_messages) == 1


# --- AC: malformed params never reach ToolExecutor.execute; self-correction ---


class TestSelfCorrection:
    async def test_malformed_params_never_reach_tool_executor(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1", tool_name="update_product_price", arguments={"skus": "nope"}
                    )
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c2",
                        tool_name="update_product_price",
                        arguments={"skus": "still-nope"},
                    )
                ),
            ],
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert spy.calls == []
        assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
        assert result.status == WorkflowRunStatus.FAILED

    async def test_second_consecutive_malformed_attempt_ends_the_run_not_a_third_retry(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        llm = FakeLLMService(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1", tool_name="update_product_price", arguments={"skus": "nope"}
                    )
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c2", tool_name="update_product_price", arguments={"skus": "nope-2"}
                    )
                ),
                # A third scripted turn exists but must never be consumed --
                # the run ends after the second malformed attempt.
                _turn(FinalResponse(content="should never be reached")),
            ]
        )
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        runner = WorkflowRunner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
        assert len(llm.recorded_calls) == 2  # never asked for the 3rd, unscripted, retry

    async def test_one_malformed_attempt_gets_one_corrected_retry_then_pauses(
        self,
    ):
        """`update_product_price`'s own `ToolSpec.policy` is CONFIRM
        (`product_write.py`) — once the corrected retry clears
        `input_model` validation, issue #1123's pause behavior takes over:
        the call is never dispatched to `ToolExecutor`, it is recorded as
        this run's pending confirmation instead. Self-correction and
        CONFIRM-pausing are independent mechanisms; this pins that a
        successful correction of a CONFIRM tool's malformed params still
        routes through the pause path, not straight to execution."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        spy = _SpyToolExecutor(result={"updated_skus": []})
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1", tool_name="update_product_price", arguments={"skus": "nope"}
                    )
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c2",
                        tool_name="update_product_price",
                        arguments={"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                    )
                ),
            ],
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        assert result.status == WorkflowRunStatus.WAITING_APPROVAL
        assert spy.calls == []  # never dispatched -- pending confirmation, not executed
        assert store._store[run_id].pending_confirmation == {
            "call_id": "c2",
            "tool_name": "update_product_price",
            "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
        }


# --- AC: inbound chokepoint bracketing every tool result -----------------------


class TestInboundGuard:
    async def test_tool_result_is_swapped_for_the_error_envelope_on_a_banned_pattern_hit(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor(result={"note": "reach us via the internal endpoint"})
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                ),
                _turn(FinalResponse(content="Done.")),
            ],
            tool_executor=spy,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        await runner.run(run_id, product_ref="prod-1")

        assert len(spy.calls) == 1  # a well-formed call *does* reach the executor
        tool_messages = [
            m for m in store._store[run_id].conversation_window if m.get("role") == "tool"
        ]
        assert len(tool_messages) == 1
        content = tool_messages[0]["content"]
        assert "error" in content
        assert content != {"note": "reach us via the internal endpoint"}
        assert "endpoint" not in str(content)  # the leaked text never reaches the conversation

        completed = [e for e in sink.events if e.event_type == "tool.completed"]
        assert len(completed) == 1
        assert completed[0].payload.ok is False


# --- AC: outbound chokepoint bracketing FinalResponse ---------------------------


class TestOutboundGuard:
    """#1210 changed this contract deliberately.

    A guard hit used to propagate out of `run()`. In production that left the
    row non-terminal, so the reaper stamped `worker_lost` -- false, and it sends
    an operator after infrastructure -- and skipped the state persist, throwing
    away the conversation and with it the text that tripped the guard.

    It now terminates as `output_validation_failed`. What must NOT change: the
    blocked content still never reaches the conversation or a completion event.
    """

    async def test_final_response_with_banned_pattern_terminates_and_never_completes(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[_turn(FinalResponse(content="We call an internal endpoint for this."))],
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        # Terminal, accurate, and written by the runner -- not left for the
        # reaper to mislabel.
        assert result.stop_reason is StopReason.OUTPUT_VALIDATION_FAILED
        assert result.status is WorkflowRunStatus.FAILED

        completed = [e for e in sink.events if e.event_type == "workflow.completed"]
        assert completed == []
        assert not any(
            m.get("content") == "We call an internal endpoint for this."
            for m in store._store[run_id].conversation_window
        )


# --- AC: playbook allowlist ------------------------------------------------------


class TestPlaybookAllowlist:
    async def test_unregistered_tool_is_refused_and_never_dispatched(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(ToolCallBlock(call_id="c1", tool_name="delete_all_products", arguments={})),
                _turn(FinalResponse(content="Never mind.")),
            ],
            tool_executor=spy,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert spy.calls == []
        assert (
            result.stop_reason == StopReason.FINAL_RESPONSE
        )  # the refusal alone didn't end the run
        refusal_events = [
            e
            for e in sink.events
            if e.event_type == "tool.completed" and e.payload.tool_name == "delete_all_products"
        ]
        assert len(refusal_events) == 1
        assert "not a registered agent capability" in refusal_events[0].payload.summary

    async def test_registered_but_not_in_playbook_tool_is_refused_and_never_dispatched(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        # update_product_price IS registered (full registry below) but this
        # playbook only allows get_product_information.
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1",
                        tool_name="update_product_price",
                        arguments={"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                    )
                ),
                _turn(FinalResponse(content="Never mind.")),
            ],
            tool_executor=spy,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert spy.calls == []
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        refusal_events = [
            e
            for e in sink.events
            if e.event_type == "tool.completed" and e.payload.tool_name == "update_product_price"
        ]
        assert len(refusal_events) == 1
        assert "not part of the active" in refusal_events[0].payload.summary

    async def test_the_three_refusal_reasons_are_pairwise_distinguishable(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))

        runner = _runner(
            script=[
                _turn(ToolCallBlock(call_id="c1", tool_name="not_a_real_tool", arguments={})),
                _turn(
                    ToolCallBlock(call_id="c2", tool_name="get_product_information", arguments={})
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c3", tool_name="update_product_price", arguments={"skus": "nope"}
                    )
                ),
                _turn(FinalResponse(content="stop")),
            ],
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        await runner.run(run_id, product_ref="prod-1")

        completed = [e for e in sink.events if e.event_type == "tool.completed"]
        summaries = [e.payload.summary for e in completed]
        assert len(summaries) == 3
        assert len(set(summaries)) == 3  # unregistered / not-in-playbook / malformed all distinct


# --- AC: ProductToolContext built from run state only, end to end --------------


class TestProductToolContextBoundIdentity:
    async def test_spoofed_product_id_in_arguments_does_not_change_the_bound_context(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="bound-product-id",
        )
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1",
                        tool_name="get_product_information",
                        arguments={"product_id": "attacker-supplied-id"},
                    )
                ),
                _turn(FinalResponse(content="Done.")),
            ],
            tool_executor=executor,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        await runner.run(run_id, product_ref="prod-1")

        assert products.get_details_calls == ["bound-product-id"]


# --- AC: compose() once per run; prompt_version/sha stable across iterations ---


class TestPromptStamping:
    async def test_compose_called_exactly_once_and_prompt_identity_is_stable(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="p1",
        )
        llm = FakeLLMService(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                ),
                _turn(ToolCallBlock(call_id="c2", tool_name="get_seo_keywords", arguments={})),
                _turn(FinalResponse(content="Done.")),
            ]
        )
        runner = WorkflowRunner(
            llm_service=llm,
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            registry=_full_registry(),
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        )

        with patch(
            "juli_backend.services.agent.runner.core.compose",
            wraps=__import__(
                "juli_backend.services.agent.prompts.composer", fromlist=["compose"]
            ).compose,
        ) as mock_compose:
            result = await runner.run(run_id, product_ref="prod-1")

        assert mock_compose.call_count == 1
        assert len(llm.recorded_calls) == 3
        systems = {call.system for call in llm.recorded_calls}
        assert len(systems) == 1  # identical system prompt on every iteration

        # The prompt version should be derived from production_version(), not
        # from OPTIMIZE_PRODUCT_PLAYBOOK.version (issue #1359). The playbook's
        # version describes its steps and policies, not which prompt executes.
        from juli_backend.services.agent.prompts.composer import production_version

        prod_version = production_version(OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key)
        expected_version = prompt_version(OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key, prod_version)
        expected_sha = prompt_sha256(OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key, prod_version)
        assert result.prompt_version == expected_version
        assert result.prompt_sha256 == expected_sha

        started = [e for e in sink.events if e.event_type == "workflow.started"]
        assert len(started) == 1
        assert started[0].payload.prompt_version == expected_version


# --- Guard: recorded pin and executed version never diverge (issue #1359) ------


class TestPromptVersionConsistency:
    """Guard test ensuring the stamped prompt pin and the executed prompt
    version never diverge for any registered playbook (issue #1359,
    ADR-072 decision 4).

    Parametrized so new playbooks are automatically covered. Includes a
    non-vacuity check that the registry is not empty.
    """

    @pytest.mark.parametrize("playbook", [OPTIMIZE_PRODUCT_PLAYBOOK])
    def test_approval_stamp_matches_runner_composition(self, playbook: Playbook) -> None:
        """What approval.py::_resolve_prompt_pin stamps on the row should
        equal what WorkflowRunner composes and executes (issue #1359).

        A mismatch means the recorded pin says one thing while another prompt
        executes — defeating ADR-072 d.4's "what runs is what was reviewed".
        """
        from juli_backend.services.agent.prompts.composer import (
            production_version,
            prompt_sha256,
            prompt_version,
        )

        # Non-vacuity guard: this list should not be empty.
        assert [OPTIMIZE_PRODUCT_PLAYBOOK], (
            "This test must have at least one playbook to validate; "
            "if all playbooks were removed, this test would pass vacuously."
        )

        # What approval.py::_resolve_prompt_pin produces (the row stamp).
        workflow_key = playbook.workflow_key
        prod_version = production_version(workflow_key)
        stamped_version = prompt_version(workflow_key, prod_version)
        stamped_sha = prompt_sha256(workflow_key, prod_version)

        # What WorkflowRunner._compose_prompt() produces (the execution).
        # The runner should derive both from production_version, never from
        # playbook.version (the bug that #1359 fixes).
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[]),
            tool_executor=_DummyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=_InMemoryConversationStore(),
            registry=_full_registry(),
            playbook=playbook,
        )
        composed_prompt, composed_version, composed_sha = runner._compose_prompt()

        # The assertion: both must agree.
        assert composed_version == stamped_version, (
            f"Stamped version {stamped_version!r} != composed version {composed_version!r} "
            f"for playbook {playbook.workflow_key!r} — #1359 regression"
        )
        assert composed_sha == stamped_sha, (
            f"Stamped SHA {stamped_sha!r} != composed SHA {composed_sha!r} "
            f"for playbook {playbook.workflow_key!r} — #1359 regression"
        )


class _DummyToolExecutor:
    """Minimal tool executor for guard test — never called."""

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        raise NotImplementedError("DummyToolExecutor should not be called in this test")


# --- AC: happy path, end to end -------------------------------------------------


class TestHappyPath:
    async def test_get_product_information_then_get_seo_keywords_then_final_response(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        products = _FakeProductsResource()
        executor = ProductToolExecutor(
            registry=_full_registry(),
            read_resources=_read_resources(products),
            product_id="p1",
        )

        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1", tool_name="get_product_information", arguments={}
                        )
                    ),
                    _turn(ToolCallBlock(call_id="c2", tool_name="get_seo_keywords", arguments={})),
                    _turn(FinalResponse(content="Here is what I found and updated.")),
                ]
            ),
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            registry=_full_registry(),
            playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert isinstance(result, RunResult)
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED
        assert result.final_response == "Here is what I found and updated."
        assert products.get_details_calls == ["p1"]
        assert products.get_seo_words_calls == [["p1"]]

        completed = [e for e in sink.events if e.event_type == "workflow.completed"]
        assert len(completed) == 1
        assert completed[0].payload.stop_reason == StopReason.FINAL_RESPONSE


# --- AC: exception translation for llm_error / concurrency_conflict /
# tool_error_unrecoverable (issue #1172) ------------------------------------


class TestLLMErrorTranslation:
    async def test_llm_provider_error_ends_the_run_with_llm_error_stop_reason(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))
        llm = _RaisingLLMService(LLMProviderError("OpenAI Responses API returned HTTP 500"))

        runner = WorkflowRunner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert llm.call_count == 1
        assert result.stop_reason == StopReason.LLM_ERROR
        assert result.status == WorkflowRunStatus.FAILED
        assert result.final_response is None

        failed = [e for e in sink.events if e.event_type == "workflow.failed"]
        assert len(failed) == 1
        assert failed[0].payload.stop_reason == StopReason.LLM_ERROR
        assert failed[0].payload.status == WorkflowRunStatus.FAILED

        # No iteration was completed -- the failed attempt never advances
        # iteration_count, mirroring the checkpoint-terminate branches.
        assert store._store[run_id].iteration_count == 0


class TestConcurrencyConflictTranslation:
    async def test_concurrency_exhausted_error_ends_the_run_via_dispatch_tool_call(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))
        executor = _RaisingToolExecutor(
            ConcurrencyExhaustedError(operation="get_product_information")
        )

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                )
            ],
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert len(executor.calls) == 1  # execute() was genuinely reached, then raised
        assert result.stop_reason == StopReason.CONCURRENCY_CONFLICT
        assert result.status == WorkflowRunStatus.FAILED

        failed = [e for e in sink.events if e.event_type == "workflow.failed"]
        assert len(failed) == 1
        assert failed[0].payload.stop_reason == StopReason.CONCURRENCY_CONFLICT
        assert failed[0].payload.status == WorkflowRunStatus.FAILED

    async def test_concurrency_exhausted_error_ends_the_run_via_resume(self):
        """The second of the two dispatch sites (issue #1172's `resume`
        call site) — a paused CONFIRM tool call resumed straight into a
        `ConcurrencyExhaustedError` from `execute()`."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                pending_confirmation={
                    "call_id": "c1",
                    "tool_name": "update_product_price",
                    "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                }
            ),
        )
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        executor = _RaisingToolExecutor(ConcurrencyExhaustedError(operation="update_product_price"))

        runner = _runner(
            script=[],
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.resume(run_id, approved=True)

        assert len(executor.calls) == 1
        assert result.stop_reason == StopReason.CONCURRENCY_CONFLICT
        assert result.status == WorkflowRunStatus.FAILED
        failed = [e for e in sink.events if e.event_type == "workflow.failed"]
        assert len(failed) == 1
        assert failed[0].payload.stop_reason == StopReason.CONCURRENCY_CONFLICT


class TestToolErrorUnrecoverableViaLedgerTranslation:
    """`tool_error_unrecoverable` already had one producer before this issue
    (self-correction give-up, `TestSelfCorrection`) — this class proves the
    *second*, newly-reachable producer: `ledger.py`'s fail-closed
    `ToolExecutionUnrecoverableError`, caught at both `ToolExecutor.execute`
    call sites and translated exactly like `ConcurrencyExhaustedError`."""

    async def test_ledger_unrecoverable_error_ends_the_run_via_dispatch_tool_call(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))
        executor = _RaisingToolExecutor(
            ToolExecutionUnrecoverableError(
                workflow_run_id=run_id,
                tool_call_id="c1",
                operation="get_product_information",
            )
        )

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                )
            ],
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert len(executor.calls) == 1
        assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
        assert result.status == WorkflowRunStatus.FAILED
        failed = [e for e in sink.events if e.event_type == "workflow.failed"]
        assert len(failed) == 1
        assert failed[0].payload.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE

    async def test_ledger_unrecoverable_error_ends_the_run_via_resume(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                pending_confirmation={
                    "call_id": "c1",
                    "tool_name": "update_product_price",
                    "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                }
            ),
        )
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        executor = _RaisingToolExecutor(
            ToolExecutionUnrecoverableError(
                workflow_run_id=run_id,
                tool_call_id="c1",
                operation="update_product_price",
            )
        )

        runner = _runner(
            script=[],
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.resume(run_id, approved=True)

        assert len(executor.calls) == 1
        assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
        assert result.status == WorkflowRunStatus.FAILED


class TestNewHandlersDoNotSwallowCancellation:
    """Issue #1172's explicit non-goal: the new `except ConcurrencyExhaustedError
    | ToolExecutionUnrecoverableError | LLMProviderError` handlers must stay
    exactly that specific — `asyncio.CancelledError` (checkpoint/task
    cancellation semantics) must keep propagating straight out of `run()`,
    never converted into a graceful terminal `RunResult`."""

    async def test_cancelled_error_from_the_llm_call_propagates_out_of_run(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        playbook = _minimal_playbook((_step("get_product_information"),))
        runner = WorkflowRunner(
            llm_service=_RaisingLLMService(asyncio.CancelledError()),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            registry=_full_registry(),
            playbook=playbook,
        )

        with pytest.raises(asyncio.CancelledError):
            await runner.run(run_id, product_ref="prod-1")

    async def test_cancelled_error_from_the_tool_executor_propagates_out_of_run(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        playbook = _minimal_playbook((_step("get_product_information"),))
        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                )
            ],
            tool_executor=_RaisingToolExecutor(asyncio.CancelledError()),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        with pytest.raises(asyncio.CancelledError):
            await runner.run(run_id, product_ref="prod-1")


# --- AC: EventSink imported, not redefined --------------------------------------


class TestImportsEventSinkRatherThanRedefiningIt:
    def test_core_module_defines_no_second_event_sink_protocol(self):
        tree = ast.parse(CORE_MODULE_PATH.read_text(encoding="utf-8"))
        class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        assert "EventSink" not in class_names

    def test_core_module_imports_event_sink_from_the_events_package(self):
        tree = ast.parse(CORE_MODULE_PATH.read_text(encoding="utf-8"))
        imported_names: set[str] = set()
        source_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name == "EventSink":
                        imported_names.add(alias.name)
                        source_modules.add(node.module)
        assert "EventSink" in imported_names
        assert source_modules == {"juli_backend.services.agent.events"}


# --- What the live write-path smoke found (2026-08-20) -------------------------


class TestRefusalsAreHonestOnTheWireAndInTheConversation:
    """Two defects the first real write-path run surfaced, neither visible to
    any scripted scenario because both are about what the *model* does with a
    refusal, and a fake LLM does whatever its script says.

    Observed: the model proposed `update_product_price` with `{}`, the params
    refusal came back tagged `retryable: false` while its own prose said
    "Correct the parameters and try again", and the model finalized without
    retrying. The run recorded `completed` / `final_response` having written
    nothing. Separately, the refusal put a `tool.completed` on the stream with
    no matching `tool.started`.
    """

    async def _refusal_run(self, sink, store, run_id):
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        runner = _runner(
            script=[
                _turn(ToolCallBlock(call_id="c1", tool_name="not_a_real_tool", arguments={})),
                _turn(
                    ToolCallBlock(call_id="c2", tool_name="get_product_information", arguments={})
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c3", tool_name="update_product_price", arguments={"skus": "nope"}
                    )
                ),
                _turn(FinalResponse(content="stop")),
            ],
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )
        await runner.run(run_id, product_ref="prod-1")
        return [m for m in store._store[run_id].conversation_window if m.get("role") == "tool"]

    async def test_a_malformed_params_refusal_invites_the_retry_it_asks_for(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)

        tool_messages = await self._refusal_run(InMemoryEventSink(), store, run_id)

        malformed = [m for m in tool_messages if m["tool_call_id"] == "c3"]
        assert len(malformed) == 1
        error = malformed[0]["content"]["error"]
        assert "try again" in error["message"]
        assert error["retryable"] is True, (
            "a params refusal whose message asks the model to correct and retry must "
            "not also tell it the failure is not retryable -- live, the model believed "
            "the flag and gave up on the write"
        )

    async def test_the_two_allowlist_refusals_stay_non_retryable(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)

        tool_messages = await self._refusal_run(InMemoryEventSink(), store, run_id)

        for call_id in ("c1", "c2"):
            message = next(m for m in tool_messages if m["tool_call_id"] == call_id)
            assert message["content"]["error"]["retryable"] is False, (
                f"refusal {call_id} names a tool this run can never call -- re-proposing "
                "it cannot succeed however it is phrased"
            )

    async def test_every_tool_completed_has_a_matching_tool_started(self):
        """The pairing invariant a stream consumer relies on: it opens a
        running-tool card on `tool.started` and closes it on
        `tool.completed`. All three refusal paths used to emit only the
        close."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()

        await self._refusal_run(sink, store, run_id)

        started = [e for e in sink.events if e.event_type == "tool.started"]
        completed = [e for e in sink.events if e.event_type == "tool.completed"]
        assert len(completed) == 3
        assert [e.payload.tool_call_id for e in started] == [
            e.payload.tool_call_id for e in completed
        ]

    async def test_tool_started_precedes_its_completion_in_sequence_order(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()

        await self._refusal_run(sink, store, run_id)

        first_seen: dict[str, str] = {}
        for event in sorted(sink.events, key=lambda e: e.sequence_number):
            payload_call_id = getattr(event.payload, "tool_call_id", None)
            if payload_call_id is None:
                continue
            first_seen.setdefault(payload_call_id, event.event_type)
        assert set(first_seen) == {"c1", "c2", "c3"}
        assert set(first_seen.values()) == {"tool.started"}


# --- AC: `required_steps_completed` -- the "did the job" outcome fact
# (issue #1220, ADR-073 decision 2) -----------------------------------------


class TestRequiredStepsCompletedPersistence:
    """`OPTIMIZE_PRODUCT_TERMINATION_POLICY.required_steps` is
    `("update_product_listing", "update_product_price")` — `_minimal_playbook`
    always carries the real termination policy, so every scenario below is
    scored against those two tool names regardless of which steps its own
    playbook lists.

    Critical regression guard (`test_zero_required_writes_still_terminates_
    completed_final_response`): `stop_reason`/`status` must never change
    because of this fact. A run that writes nothing still ends
    `final_response`/`completed` — `required_steps_completed=False` is
    recorded *alongside* that, never instead of it.
    """

    async def test_completing_every_required_step_records_true(self):
        """AC1. Seeds a conversation window where `update_product_listing`
        already completed successfully, then resumes an approved
        `update_product_price` pending confirmation -- the second and last
        required step -- straight through to `final_response`."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                conversation_window=[
                    {
                        "role": "assistant",
                        "tool_call": {
                            "call_id": "c0",
                            "tool_name": "update_product_listing",
                            "arguments": {"title": "New Title"},
                        },
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "c0",
                        "tool_name": "update_product_listing",
                        "content": {
                            "title": "New Title",
                            "description": None,
                            "image_attached": False,
                        },
                    },
                ],
                pending_confirmation={
                    "call_id": "c1",
                    "tool_name": "update_product_price",
                    "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                },
            ),
        )
        playbook = _minimal_playbook(
            (
                _step("update_product_listing", policy=ToolPolicy.CONFIRM),
                _step("update_product_price", policy=ToolPolicy.CONFIRM),
            )
        )
        runner = _runner(
            script=[_turn(FinalResponse(content="Both changes are live."))],
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.resume(run_id, approved=True)

        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED
        assert store.required_steps_completed_for(run_id) is True

    async def test_completing_some_required_steps_records_false(self):
        """AC2. Only `update_product_listing` ever completed;
        `update_product_price` is never even proposed."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                conversation_window=[
                    {
                        "role": "assistant",
                        "tool_call": {
                            "call_id": "c0",
                            "tool_name": "update_product_listing",
                            "arguments": {"title": "New Title"},
                        },
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "c0",
                        "tool_name": "update_product_listing",
                        "content": {
                            "title": "New Title",
                            "description": None,
                            "image_attached": False,
                        },
                    },
                ]
            ),
        )
        playbook = _minimal_playbook(
            (
                _step("update_product_listing", policy=ToolPolicy.CONFIRM),
                _step("update_product_price", policy=ToolPolicy.CONFIRM),
            )
        )
        runner = _runner(
            script=[_turn(FinalResponse(content="Only the listing changed."))],
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED
        assert store.required_steps_completed_for(run_id) is False

    async def test_completing_no_required_steps_records_false(self):
        """AC3. A READ-only run (`get_product_information`) never touches
        either required WRITE step."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        playbook = _minimal_playbook((_step("get_product_information"),))
        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                ),
                _turn(FinalResponse(content="Here's what the listing looks like today.")),
            ],
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert store.required_steps_completed_for(run_id) is False

    async def test_zero_required_writes_still_terminates_completed_final_response(self):
        """AC4, the regression guard. No tool call at all -- the model
        finalizes immediately. `required_steps_completed=False` must be
        recorded *alongside* an entirely ordinary `final_response`/
        `completed` termination, never as a reason to invent a different
        one. If a future change makes this test's `stop_reason`/`status`
        assertions fail, that change turned an outcome fact into a
        synthetic termination rule -- exactly what ADR-073 decision 2
        forbids."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        playbook = _minimal_playbook(
            (
                _step("update_product_listing", policy=ToolPolicy.CONFIRM),
                _step("update_product_price", policy=ToolPolicy.CONFIRM),
            )
        )
        runner = _runner(
            script=[_turn(FinalResponse(content="Nothing needed changing."))],
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.FINAL_RESPONSE, (
            "a run with no required writes must still end final_response, not a "
            "synthetic failure invented because required_steps_completed is False"
        )
        assert result.status == WorkflowRunStatus.COMPLETED
        assert store.required_steps_completed_for(run_id) is False

    async def test_refused_and_malformed_calls_do_not_count_as_completed(self):
        """AC6. `update_product_price` is proposed twice with malformed
        params (never reaches `ToolExecutor`) and the run gives up --
        `tool_error_unrecoverable`. Neither attempt counts as completed."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1", tool_name="update_product_price", arguments={"skus": "nope"}
                    )
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c2",
                        tool_name="update_product_price",
                        arguments={"skus": "still-nope"},
                    )
                ),
            ],
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert spy.calls == []
        assert result.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
        assert store.required_steps_completed_for(run_id) is False

    async def test_an_unregistered_tool_refusal_does_not_count_as_completed(self):
        """AC6, the allowlist-refusal variant: a tool name that happens to
        collide with a required step name but is refused before
        `ToolExecutor` is ever reached must not count."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        spy = _SpyToolExecutor()
        # A playbook that does NOT list update_product_price -- the
        # allowlist refusal path -- while the real termination policy
        # (carried by _minimal_playbook) still requires it.
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(ToolCallBlock(call_id="c1", tool_name="update_product_price", arguments={})),
                _turn(FinalResponse(content="Can't touch the price from here.")),
            ],
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.run(run_id, product_ref="prod-1")

        assert spy.calls == []
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert store.required_steps_completed_for(run_id) is False

    async def test_declined_confirmation_records_false_without_the_run_being_a_failure(self):
        """AC7 -- the #1220 regression guard for the decline branch
        specifically (issue #1225 / AGT-W5A, ADR-075 decision 2). The two
        facts must be recorded TOGETHER, in the same test, or one can drift
        without the other catching it: `required_steps_completed` reads
        `False` (the declined `update_product_price` never actually ran --
        `termination.required_steps_completed`'s own docstring says a
        `{"confirmation": {"decision": "declined"}}` tool-result entry never
        counts as completed) while `stop_reason`/`status` land on the
        seller's honest choice (`confirmation_declined`/`completed`), never
        a synthetic `failed`/`cancelled` invented because the required
        write didn't happen."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                pending_confirmation={
                    "call_id": "c1",
                    "tool_name": "update_product_price",
                    "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                }
            ),
        )
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        spy = _SpyToolExecutor()
        runner = _runner(
            script=[_turn(FinalResponse(content="No worries -- keeping the current price."))],
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.resume(run_id, approved=False)

        assert spy.calls == []  # the declined price change never dispatched
        assert result.stop_reason == StopReason.CONFIRMATION_DECLINED
        assert result.status == WorkflowRunStatus.COMPLETED, (
            "a declined confirmation must never be recorded as a failure -- "
            "ADR-075 decision 2: decline is a conversation, not a kill"
        )
        assert store.required_steps_completed_for(run_id) is False, (
            "the declined write never happened -- required_steps_completed must "
            "say so, independently of the non-failure status above"
        )


# --- AC: the decline closing turn's outbound guard, review round 2 ---------------
# (issue #1225, CRITICAL finding) -----------------------------------------------


class TestDeclineClosingTurnOutboundGuard:
    """`_closing_turn_after_decline`'s `guard_outbound_agent_output` call is a
    second call site to the exact guard `_finalize` already wraps in
    `try`/`except BannedPatternGuardFailure` (issue #1210). This slice added
    the second call site but not the matching handling -- Review round 2
    caught it: `resume()` has already durably committed `status=RUNNING`
    (#1181's entry-transition persist, `durable=True`, before either branch
    runs) by the time this guard call happens, and
    `workers/tasks/agent_workflow.py::_resume_agent_workflow_async` has no
    `try`/`except` around `await runner.resume(...)` — it commits only after
    `resume()` returns. So an uncaught guard hit here leaves the row stuck at
    `RUNNING`: the Celery task exhausts `max_retries=1`, and
    `_reap_stale_running_and_queued` reaps it as `worker_lost` five minutes
    later — the exact mislabel #1210 already fixed for `_finalize`,
    reintroduced through this slice's own new call site to the same guard.
    """

    async def test_a_banned_pattern_in_the_closing_response_terminates_instead_of_propagating(
        self,
    ):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                pending_confirmation={
                    "call_id": "c1",
                    "tool_name": "update_product_price",
                    "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                }
            ),
        )
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        runner = _runner(
            # Same banned-pattern text `TestOutboundGuard` above uses to trip
            # `guard_outbound_agent_output` -- not a new fixture.
            script=[_turn(FinalResponse(content="We call an internal endpoint for this."))],
            tool_executor=spy,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        # Must return a terminal RunResult -- must NOT raise
        # BannedPatternGuardFailure out of resume(). Before the fix, this
        # call raises straight through this test (pytest reports it as an
        # error, not an assertion failure) -- the proof that the guard hit
        # currently escapes `resume()` uncaught.
        result = await runner.resume(run_id, approved=False)

        assert spy.calls == []  # still never dispatched -- the declined call
        # Reuses the SAME StopReason `_finalize` already uses for this exact
        # guard (#1210) -- never a new vocabulary member for one failure class.
        assert result.stop_reason is StopReason.OUTPUT_VALIDATION_FAILED
        assert result.status is WorkflowRunStatus.FAILED

        # The blocked content never reaches a completion event or the
        # conversation -- mirrors TestOutboundGuard's own assertions exactly.
        completed = [e for e in sink.events if e.event_type == "workflow.completed"]
        assert completed == []
        assert not any(
            m.get("content") == "We call an internal endpoint for this."
            for m in store._store[run_id].conversation_window
        )


class TestDeclineClosingTurnRefusesToolCalls:
    """The invariant that a declined run cannot execute the work the seller
    just refused, even if the model proposes a tool call in its one closing
    turn (`_closing_turn_after_decline`'s `ToolCallBlock` branch, refused via
    `_refuse` exactly like an unlisted-tool refusal) -- Review round 2's
    WARNING: this path is correct but had zero regression coverage."""

    async def test_a_tool_call_in_the_closing_turn_is_refused_never_dispatched(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(
            run_id,
            RunState(
                pending_confirmation={
                    "call_id": "c1",
                    "tool_name": "update_product_price",
                    "arguments": {"skus": [{"sku_ref": "S1", "amount": "1000"}]},
                }
            ),
        )
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
        runner = _runner(
            # The model tries to propose the very price change the seller
            # just declined, in its one closing turn.
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c2",
                        tool_name="update_product_price",
                        arguments={"skus": [{"sku_ref": "S1", "amount": "999"}]},
                    )
                )
            ],
            tool_executor=spy,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )

        result = await runner.resume(run_id, approved=False)

        # The whole guarantee under test: zero tool calls happened.
        assert spy.calls == []
        assert result.stop_reason == StopReason.CONFIRMATION_DECLINED
        assert result.status == WorkflowRunStatus.COMPLETED
        assert result.final_response is None  # refused, not a closing FinalResponse

        # The refusal is recorded like any other refusal: proposal + error
        # result, never a bare drop.
        tool_messages = [
            m for m in store._store[run_id].conversation_window if m.get("role") == "tool"
        ]
        refusal_messages = [m for m in tool_messages if m.get("tool_call_id") == "c2"]
        assert len(refusal_messages) == 1
        assert "error" in refusal_messages[0]["content"]

        completed_events = [e for e in sink.events if e.event_type == "tool.completed"]
        refused_completion = [e for e in completed_events if e.payload.tool_call_id == "c2"]
        assert len(refused_completion) == 1
        assert refused_completion[0].payload.ok is False
