"""Verification that seller-facing reason codes do not leak internal
identifiers (tool names, playbook keys, validation-error structures)
and use Vietnamese copy (issue #1272 / W6-B/P-UI-3).

This test suite ensures that `ToolCompletedPayload.summary`, which reaches
the seller through `workflow_run_events` → Redis → SSE, never contains:
- Tool names (even in repr form)
- Playbook keys
- Raw Pydantic validation-error structures
- Hardcoded English copy

All seller-facing copy must be Vietnamese, reviewed, and drawn from
approved sources (dictionary.md, design-context.md).

Tests are integration-style: they run the actual `WorkflowRunner` against
a script and check the emitted events.
"""

from __future__ import annotations

import uuid

import pytest

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.seller_facing_copy import (
    SellerFacingCompletionReason,
    SellerFacingRefusalReason,
)
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools

# Minimal fixtures from test_agent_runner_core.py adapted for our tests


class _InMemoryConversationStore:
    def __init__(self) -> None:
        self._store = {}
        self._status = {}
        self._stop_reason = {}
        self._required_steps_completed = {}
        self._running_seconds_elapsed = {}
        self._pending_confirmations = {}
        self._durable_calls = []

    def seed(self, workflow_run_id, state=None):
        from juli_backend.services.agent.runner.state import RunState

        self._store[workflow_run_id] = state if state is not None else RunState()

    async def load(self, workflow_run_id):

        state = self._store[workflow_run_id]
        if state.prompt_version is None:
            state.prompt_version = "optimize_product.v1"
        if state.prompt_sha256 is None:
            state.prompt_sha256 = "0" * 64
        return state

    async def persist(
        self,
        workflow_run_id,
        state,
        *,
        status=None,
        stop_reason=None,
        required_steps_completed=None,
        running_seconds_elapsed=None,
        pending_confirmation=None,
        durable=False,
    ):
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


class _SpyToolExecutor:
    def __init__(self, result=None):
        self.calls = []
        self._result = result if result is not None else {"ok": True}

    def execute(self, *, tool_name, params, tool_call_id=None):
        self.calls.append((tool_name, params))
        return dict(self._result)


class _FakeProductsResource:
    def __init__(self, *, details=None):
        self._details = details or {"title": "A nice widget", "status": "LIVE"}
        self.get_details_calls = []
        self.get_seo_words_calls = []
        self.get_suggestions_calls = []

    def get_details(self, product_id):
        self.get_details_calls.append(product_id)
        return self._details

    def get_seo_words(self, *, product_ids):
        self.get_seo_words_calls.append(product_ids)
        return {"products": []}

    def get_suggestions(self, *, product_ids):
        self.get_suggestions_calls.append(product_ids)
        return {"products": []}


def _read_resources(products):
    from juli_backend.integrations.tiktok.factories import ProductionReadResources

    return ProductionReadResources(
        authorization=None,
        orders=None,
        products=products,
        returns=None,
        inventory=None,
        analytics=None,
        promotion=None,
    )


def _full_registry():
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _minimal_playbook(steps):
    from dataclasses import replace

    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=steps,
        termination_policy=replace(OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()),
    )


def _step(tool_name, *, policy=ToolPolicy.AUTO):
    return PlaybookStep(
        step_id=tool_name, intent=f"Call {tool_name}.", tools=(tool_name,), policy=policy
    )


def _turn(*blocks):
    return type(
        "Turn", (), {"blocks": tuple(blocks), "usage": Usage(input_tokens=1, output_tokens=1)}
    )()


def _runner(*, script, tool_executor, event_sink, conversation_store, playbook, registry):
    llm = FakeLLMService(script=script)

    return WorkflowRunner(
        llm_service=llm,
        tool_executor=tool_executor,
        event_sink=event_sink,
        conversation_store=conversation_store,
        playbook=playbook,
        registry=registry,
    )


class TestSellerFacingReasonCodes:
    """Verify seller-facing reason codes are safe and Vietnamese."""

    @pytest.mark.asyncio
    async def test_unregistered_tool_summary_does_not_leak_tool_name(self):
        """Tool refusal for unregistered tool must use safe copy, not internal tool name."""
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

        await runner.run(run_id, product_ref="prod-1")

        refusal_events = [
            e
            for e in sink.events
            if e.event_type == "tool.completed" and e.payload.tool_name == "delete_all_products"
        ]
        assert len(refusal_events) == 1
        summary = refusal_events[0].payload.summary

        # The summary MUST be the safe seller-facing copy
        assert summary == SellerFacingRefusalReason.TOOL_NOT_FOUND.value
        # The summary must NOT contain the internal tool name
        assert "delete_all_products" not in summary
        # The summary must NOT contain any quotes (no repr formatting)
        assert "'" not in summary and '"' not in summary

    @pytest.mark.asyncio
    async def test_playbook_blocked_tool_summary_does_not_leak_playbook_key(self):
        """Tool refusal for playbook-blocked tool must use safe copy."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        # update_product_price IS registered but not in this playbook
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

        await runner.run(run_id, product_ref="prod-1")

        refusal_events = [
            e
            for e in sink.events
            if e.event_type == "tool.completed" and e.payload.tool_name == "update_product_price"
        ]
        assert len(refusal_events) == 1
        summary = refusal_events[0].payload.summary

        # The summary MUST be the safe seller-facing copy
        assert summary == SellerFacingRefusalReason.TOOL_NOT_ALLOWED.value
        # The summary must NOT contain the playbook key
        assert "optimize_product" not in summary
        # The summary must NOT contain any quotes (no repr formatting)
        assert "'" not in summary and '"' not in summary

    @pytest.mark.asyncio
    async def test_malformed_params_summary_does_not_leak_validation_errors(self):
        """Tool refusal for malformed params must not leak Pydantic error structure."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("update_product_price"),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1",
                        tool_name="update_product_price",
                        # Missing required 'skus' field
                        arguments={},
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

        await runner.run(run_id, product_ref="prod-1")

        refusal_events = [
            e
            for e in sink.events
            if e.event_type == "tool.completed" and e.payload.tool_name == "update_product_price"
        ]
        assert len(refusal_events) == 1
        summary = refusal_events[0].payload.summary

        # The summary MUST be the safe seller-facing copy
        assert summary == SellerFacingRefusalReason.MALFORMED_PARAMS.value
        # The summary must NOT contain:
        assert "[{" not in summary  # No JSON-like error structure
        assert "ValidationError" not in summary
        assert "'type'" not in summary and "'loc'" not in summary
        assert "skus" not in summary
        assert "repr" not in summary.lower()

    @pytest.mark.asyncio
    async def test_completed_summary_is_vietnamese(self):
        """Successful tool completion must use Vietnamese copy, not hardcoded English."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        spy = _SpyToolExecutor()
        playbook = _minimal_playbook((_step("get_product_information"),))

        runner = _runner(
            script=[
                _turn(
                    ToolCallBlock(
                        call_id="c1",
                        tool_name="get_product_information",
                        arguments={"sku_refs": ["S1"]},
                    )
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

        completed_events = [
            e
            for e in sink.events
            if e.event_type == "tool.completed"
            and e.payload.tool_name == "get_product_information"
            and e.payload.ok
        ]
        assert len(completed_events) == 1
        summary = completed_events[0].payload.summary

        # Summary must be Vietnamese, not hardcoded English "completed"
        assert summary == SellerFacingCompletionReason.COMPLETED.value
        assert summary != "completed"
        assert "Hoàn tất" in summary  # Vietnamese for "completed"
