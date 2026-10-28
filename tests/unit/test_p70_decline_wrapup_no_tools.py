"""P70 (owner, 2026-10-28): the decline wrap-up turn offers no tool, and never shows English.

The owner saw "The seller declined this change; the run is wrapping up without dispatching any
further tool calls." in the demo run panel and read it as a backend error. At the source:

- ``_closing_turn_after_decline`` asks for the one wrap-up turn with ``tool_choice="none"``
  -- the model can only answer in text;
- a ``ToolCallBlock`` there anyway (a provider ignoring ``tool_choice``) is still refused,
  never dispatched; the seller-facing ``tool.completed`` summary is Vietnamese
  (``DECLINE_WRAP_UP_REFUSED_SUMMARY``) and the English reason reaches only the model's
  conversation. (The demo additionally renders no row for it -- ``timeline.ts``.)
"""

from __future__ import annotations

import uuid

from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import FinalResponse, ToolCallBlock
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.seller_facing_copy import (
    DECLINE_WRAP_UP_REFUSED_SUMMARY,
)
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools import ToolPolicy
from tests.unit.test_agent_runner_core import (
    _full_registry,
    _InMemoryConversationStore,
    _minimal_playbook,
    _SpyToolExecutor,
    _step,
    _turn,
)

ENGLISH_REFUSAL = "The seller declined this change"


def _declined_run(
    script,
) -> tuple[
    uuid.UUID, WorkflowRunner, FakeLLMService, InMemoryEventSink, _InMemoryConversationStore
]:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(
        run_id,
        RunState(
            pending_confirmation={
                "call_id": "c1",
                "tool_name": "update_product_listing",
                "arguments": {"title": "Áo thun mới"},
            }
        ),
    )
    llm = FakeLLMService(script=script)
    sink = InMemoryEventSink()
    runner = WorkflowRunner(
        llm_service=llm,
        tool_executor=_SpyToolExecutor(),
        event_sink=sink,
        conversation_store=store,
        registry=_full_registry(),
        playbook=_minimal_playbook((_step("update_product_listing", policy=ToolPolicy.CONFIRM),)),
    )
    return run_id, runner, llm, sink, store


async def test_the_wrap_up_turn_is_requested_with_no_tool_allowed():
    run_id, runner, llm, _sink, _store = _declined_run(
        [_turn(FinalResponse(content="Juli giữ nguyên sản phẩm."))]
    )
    result = await runner.resume(run_id, approved=False)
    assert result.stop_reason == StopReason.CONFIRMATION_DECLINED
    [call] = llm.recorded_calls
    assert call.tool_choice == "none"
    assert result.final_response == "Juli giữ nguyên sản phẩm."


async def test_a_wrap_up_tool_call_is_refused_and_shows_no_english_to_the_seller():
    run_id, runner, _llm, sink, store = _declined_run(
        [
            _turn(
                ToolCallBlock(
                    call_id="c2",
                    tool_name="update_product_listing",
                    arguments={"title": "Áo thun mới"},
                )
            )
        ]
    )
    result = await runner.resume(run_id, approved=False)
    assert result.stop_reason == StopReason.CONFIRMATION_DECLINED
    assert result.final_response is None

    [refused] = [
        e
        for e in sink.events
        if e.event_type == "tool.completed" and e.payload.tool_call_id == "c2"
    ]
    assert refused.payload.ok is False
    assert refused.payload.summary == DECLINE_WRAP_UP_REFUSED_SUMMARY
    # No seller-facing event carries the model-facing English.
    for event in sink.events:
        assert ENGLISH_REFUSAL not in event.payload.model_dump_json()
    # The model still gets the reason, in its own conversation.
    [tool_message] = [
        m
        for m in store._store[run_id].conversation_window
        if m.get("role") == "tool" and m.get("tool_call_id") == "c2"
    ]
    assert ENGLISH_REFUSAL in tool_message["content"]["error"]["message"]
