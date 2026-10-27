"""P70: no second confirmation after a successful write (production run ceec586e).

Run ``ceec586e-8455-4fec-940b-2d0825af1b2f`` (reviewer sandbox, 2026-10-27): the seller
confirmed a title + description edit, the write went through ("Ghi lên TikTok Shop ·
Xong", Seller Center showed the new title), and 11 s later the run asked "Xác nhận một
lần" AGAIN with an empty proposal panel. The seller declined it; the run ended
``confirmation_declined`` -- "Không thay đổi", "Không có gì được ghi lên TikTok Shop" --
and Đo lường / Hoàn tác never saw the write.

Cause: optimize-product's ``required_steps`` are the listing edit AND the price edit. After
the listing write the model's closing FinalResponse found ``required_steps_completed``
False and the ADR-088 forced retry re-invoked it with ``tool_choice="required"`` -- which
coerced another CONFIRM proposal on a run that had already done its job.

These tests drive the real ``WorkflowRunner`` with a fake LLM and a spy executor.
"""

from __future__ import annotations

import uuid
from typing import Any

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.termination import (
    performed_any,
    performed_call_arguments,
)
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools

LISTING = {
    "title": "Nồi Lẩu Điện Mini 1.5L Có Nắp Kính Tay Cầm Tiện Dụng Nấu Lẩu Mì Súp",
    "description": "<p>Nồi lẩu điện mini 1.5L, nắp kính, tay cầm tiện dụng.</p>",
}
PRICE = {"skus": [{"sku_ref": "sku-1", "amount": "199000", "currency": "VND"}]}


class _Store:
    """In-memory `ConversationStore` double (same shape as the forced-retry suite's)."""

    def __init__(self) -> None:
        self.states: dict[uuid.UUID, RunState] = {}
        self.status: dict[uuid.UUID, WorkflowRunStatus] = {}
        self.stop_reason: dict[uuid.UUID, StopReason | None] = {}
        self.confirmations: list[Any] = []

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self.states[workflow_run_id]
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
        pending_confirmation: Any = None,
        **_: Any,
    ) -> None:
        self.states[workflow_run_id] = state
        if pending_confirmation is not None:
            self.confirmations.append(pending_confirmation)
        if status is not None:
            self.status[workflow_run_id] = status
            self.stop_reason[workflow_run_id] = stop_reason


class _SpyExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, *, tool_name: str, params: Any, tool_call_id: str | None = None) -> dict:
        self.calls.append(tool_name)
        if tool_name == "update_product_listing":
            return {"ok": True, "title": LISTING["title"], "description": LISTING["description"]}
        return {"ok": True}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(0, 0))


def _runner(store: _Store, sink: InMemoryEventSink, spy: _SpyExecutor, script: list) -> tuple:
    llm = FakeLLMService(script=script)
    registry = _registry()
    runner = WorkflowRunner(
        llm_service=llm,
        tool_executor=spy,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=OPTIMIZE_PRODUCT_PLAYBOOK,
        clock=lambda: 0.0,
    )
    return runner, llm


def _approvals(sink: InMemoryEventSink) -> list[Any]:
    return [e for e in sink.events if e.event_type == "workflow.approval_required"]


async def _paused_at_listing(store: _Store, sink: InMemoryEventSink, spy: _SpyExecutor):
    run_id = uuid.uuid4()
    store.states[run_id] = RunState()
    runner, _ = _runner(
        store,
        sink,
        spy,
        [_turn(ToolCallBlock(call_id="c1", tool_name="update_product_listing", arguments=LISTING))],
    )
    result = await runner.run(run_id, product_ref="prod-1")
    assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
    assert len(_approvals(sink)) == 1
    return run_id


class TestNoSecondConfirmationAfterTheWrite:
    async def test_closing_turn_after_the_write_finishes_the_run_written(self):
        """The ceec586e sequence: confirm -> write -> the model closes. No forced
        retry, no second approval, the run ends ``final_response``."""
        store, sink, spy = _Store(), InMemoryEventSink(), _SpyExecutor()
        run_id = await _paused_at_listing(store, sink, spy)

        runner, llm = _runner(
            store, sink, spy, [_turn(FinalResponse(content="Đã cập nhật tiêu đề và mô tả."))]
        )
        result = await runner.resume(run_id, approved=True)

        assert spy.calls == ["update_product_listing"]
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED
        assert len(_approvals(sink)) == 1, "no second 'Xác nhận một lần'"
        assert [call.tool_choice for call in llm.recorded_calls] == [None], (
            "no forced tool_choice='required' turn after a successful write"
        )

    async def test_an_identical_re_proposal_is_already_applied_not_asked_again(self):
        """The model re-proposes the exact change it just wrote: no approval, no
        second vendor write; the run continues to read-back and finishes written."""
        store, sink, spy = _Store(), InMemoryEventSink(), _SpyExecutor()
        run_id = await _paused_at_listing(store, sink, spy)

        runner, _ = _runner(
            store,
            sink,
            spy,
            [
                _turn(
                    ToolCallBlock(
                        call_id="c2", tool_name="update_product_listing", arguments=dict(LISTING)
                    )
                ),
                _turn(ToolCallBlock(call_id="c3", tool_name="check_product_status", arguments={})),
                _turn(FinalResponse(content="Xong.")),
            ],
        )
        result = await runner.resume(run_id, approved=True)

        assert spy.calls == ["update_product_listing", "check_product_status"]
        assert len(_approvals(sink)) == 1
        assert len(store.confirmations) == 1, "no second run_confirmations row"
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED
        repeated = [
            m
            for m in store.states[run_id].conversation_window
            if m.get("role") == "tool" and m.get("tool_call_id") == "c2"
        ]
        assert repeated and repeated[0]["content"]["already_applied"] is True

    async def test_a_different_listing_change_still_asks_with_its_own_diff(self):
        store, sink, spy = _Store(), InMemoryEventSink(), _SpyExecutor()
        run_id = await _paused_at_listing(store, sink, spy)
        other = {**LISTING, "title": "Nồi Lẩu Điện Mini 1.5L Nắp Kính"}

        runner, _ = _runner(
            store,
            sink,
            spy,
            [
                _turn(
                    ToolCallBlock(call_id="c2", tool_name="update_product_listing", arguments=other)
                )
            ],
        )
        result = await runner.resume(run_id, approved=True)

        assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        approvals = _approvals(sink)
        assert len(approvals) == 2
        assert approvals[-1].payload.proposed_change == other


class TestALaterDeclineKeepsTheWrite:
    async def test_declining_a_later_proposal_after_the_write_ends_written(self):
        """The model voluntarily proposes a price change after the listing write; the
        seller declines it. The run still ends ``final_response`` (completed): the
        listing change exists on TikTok and is measured / revertible."""
        store, sink, spy = _Store(), InMemoryEventSink(), _SpyExecutor()
        run_id = await _paused_at_listing(store, sink, spy)

        runner, _ = _runner(
            store,
            sink,
            spy,
            [_turn(ToolCallBlock(call_id="c2", tool_name="update_product_price", arguments=PRICE))],
        )
        paused = await runner.resume(run_id, approved=True)
        assert paused.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION

        runner, _ = _runner(store, sink, spy, [_turn(FinalResponse(content="Giữ giá cũ."))])
        result = await runner.resume(run_id, approved=False)

        assert spy.calls == ["update_product_listing"], "the declined price was never sent"
        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert result.status == WorkflowRunStatus.COMPLETED
        assert store.stop_reason[run_id] == StopReason.FINAL_RESPONSE
        completed = [e for e in sink.events if e.event_type == "workflow.completed"]
        assert completed[-1].payload.stop_reason == StopReason.FINAL_RESPONSE

    async def test_declining_the_only_proposal_is_still_a_decline(self):
        """Non-vacuity: with no write before it, a decline stays ``confirmation_declined``."""
        store, sink, spy = _Store(), InMemoryEventSink(), _SpyExecutor()
        run_id = await _paused_at_listing(store, sink, spy)

        runner, _ = _runner(store, sink, spy, [_turn(FinalResponse(content="Không đổi."))])
        result = await runner.resume(run_id, approved=False)

        assert spy.calls == []
        assert result.stop_reason == StopReason.CONFIRMATION_DECLINED


class TestPerformedHelpers:
    def test_only_performed_calls_count(self):
        window = [
            {
                "role": "assistant",
                "tool_call": {"call_id": "a", "tool_name": "t", "arguments": {"x": 1}},
            },
            {"role": "tool", "tool_call_id": "a", "tool_name": "t", "content": {"ok": True}},
            {
                "role": "assistant",
                "tool_call": {"call_id": "b", "tool_name": "t", "arguments": {"x": 2}},
            },
            {"role": "tool", "tool_call_id": "b", "tool_name": "t", "content": {"ok": False}},
            {
                "role": "assistant",
                "tool_call": {"call_id": "c", "tool_name": "t", "arguments": {"x": 3}},
            },
            {
                "role": "tool",
                "tool_call_id": "c",
                "tool_name": "t",
                "content": {"confirmation": {"decision": "declined"}},
            },
        ]
        assert performed_call_arguments(window, "t") == [{"x": 1}]
        assert performed_any(window, {"t"})
        assert not performed_any(window[2:], {"t"})
