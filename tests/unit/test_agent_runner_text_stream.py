"""P61-C (D71.3) -- `TextDeltaRelay` and the runner's `assistant.text.delta` leg.

The relay: coalescing (min chars / interval on an injected clock), the guard
hold-back (nothing within `STREAM_GUARD_HOLDBACK_CHARS` of the received end
is released; a banned phrase stops the stream before any of it leaves),
chunk numbering. The runner: deltas precede the authoritative `assistant.text`
of the same turn, a streamed `FinalResponse` is committed by an
`assistant.text` before `workflow.completed`, a refused or failed turn leaves
only uncommitted (guard-clean) deltas, and `stream_text=False` emits exactly
the pre-P61-C event list.
"""

from __future__ import annotations

import uuid
from typing import Any

from juli_backend.services.agent.events import AssistantTextDeltaPayload, InMemoryEventSink
from juli_backend.services.agent.llm import FinalResponse, TextBlock, ToolCallBlock
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.llm.openai_adapter import LLMProviderError
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.text_stream import (
    STREAM_DELTA_FLUSH_INTERVAL_SECONDS,
    STREAM_DELTA_FLUSH_MIN_CHARS,
    STREAM_GUARD_HOLDBACK_CHARS,
    TextDeltaRelay,
)
from juli_backend.services.agent.status import StopReason
from tests.unit.test_agent_runner_core import (
    _full_registry,
    _InMemoryConversationStore,
    _minimal_playbook,
    _SpyToolExecutor,
    _step,
    _turn,
)

BANNED = "We call an internal endpoint for this."


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _relay(clock: _Clock | None = None) -> tuple[TextDeltaRelay, list[AssistantTextDeltaPayload]]:
    out: list[AssistantTextDeltaPayload] = []

    async def emit(payload: AssistantTextDeltaPayload) -> None:
        out.append(payload)

    return TextDeltaRelay(emit_chunk=emit, clock=clock or _Clock(), block_id="b1"), out


# --- relay -------------------------------------------------------------------


async def test_nothing_is_released_inside_the_holdback():
    relay, out = _relay()
    await relay.on_delta("x" * STREAM_GUARD_HOLDBACK_CHARS)
    assert out == []
    assert relay.emitted is False


async def test_min_chars_flush_releases_everything_but_the_holdback():
    relay, out = _relay()
    total = STREAM_GUARD_HOLDBACK_CHARS + STREAM_DELTA_FLUSH_MIN_CHARS
    await relay.on_delta("a" * total)
    assert [p.text for p in out] == ["a" * STREAM_DELTA_FLUSH_MIN_CHARS]
    assert out[0].block_id == "b1" and out[0].chunk_index == 0


async def test_small_ready_text_waits_for_the_interval():
    clock = _Clock()
    relay, out = _relay(clock)
    await relay.on_delta("a" * (STREAM_GUARD_HOLDBACK_CHARS + 5))
    assert out == []  # 5 ready chars, interval not elapsed
    clock.now += STREAM_DELTA_FLUSH_INTERVAL_SECONDS
    await relay.on_delta("b")
    assert [p.text for p in out] == ["a" * 6]


async def test_chunks_concatenate_to_a_prefix_of_the_received_text():
    clock = _Clock()
    relay, out = _relay(clock)
    text = "".join(f"Từ khoá {i} rất tốt. " for i in range(40))
    for start in range(0, len(text), 7):
        clock.now += 0.03
        await relay.on_delta(text[start : start + 7])
    assert len(out) > 2
    assert [p.chunk_index for p in out] == list(range(len(out)))
    streamed = "".join(p.text for p in out)
    assert text.startswith(streamed)
    assert len(text) - len(streamed) >= STREAM_GUARD_HOLDBACK_CHARS


async def test_banned_phrase_stops_the_stream_before_any_of_it_leaves():
    clock = _Clock()
    relay, out = _relay(clock)
    clean = "Mình đã đọc thông tin sản phẩm và từ khoá liên quan rồi nhé. " * 3
    text = clean + BANNED + " " + "thêm nội dung " * 20
    for start in range(0, len(text), 5):
        clock.now += 0.05
        await relay.on_delta(text[start : start + 5])
    streamed = "".join(p.text for p in out)
    assert "internal" not in streamed
    assert relay.stopped is True
    assert clean.startswith(streamed) or streamed.startswith(clean[: len(streamed)])


# --- runner -------------------------------------------------------------------

LONG_NARRATION = (
    "Mình sẽ đọc thông tin sản phẩm trước, rồi so sánh với từ khoá đang được tìm "
    "nhiều nhất để đề xuất tiêu đề tốt hơn cho bạn."
)
LONG_FINAL = (
    "Tiêu đề hiện tại đã khớp với các từ khoá chính, mô tả đủ chi tiết và ảnh rõ "
    "ràng, nên lượt này mình không đề xuất thay đổi nào cho sản phẩm."
)


def _streaming_runner(llm: Any, sink: InMemoryEventSink, store, *, stream_text: bool = True):
    return WorkflowRunner(
        llm_service=llm,
        tool_executor=_SpyToolExecutor(),
        event_sink=sink,
        conversation_store=store,
        registry=_full_registry(),
        playbook=_minimal_playbook((_step("get_product_information"),)),
        stream_text=stream_text,
    )


def _script():
    return [
        _turn(
            TextBlock(text=LONG_NARRATION),
            ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={}),
        ),
        _turn(FinalResponse(content=LONG_FINAL)),
    ]


async def test_runner_streams_deltas_then_commits_each_turn():
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    sink = InMemoryEventSink()
    llm = FakeLLMService(script=_script(), stream_chunk_chars=4)

    result = await _streaming_runner(llm, sink, store).run(run_id, product_ref="prod-1")

    assert result.stop_reason is StopReason.FINAL_RESPONSE
    types = [e.event_type for e in sink.events]
    seqs = [e.sequence_number for e in sink.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    texts = [e for e in sink.events if e.event_type == "assistant.text"]
    assert [e.payload.text for e in texts] == [LONG_NARRATION, LONG_FINAL]

    # Turn 1: its deltas sit right before its assistant.text, before tool.started.
    first_text = types.index("assistant.text")
    assert types[first_text - 1] == "assistant.text.delta"
    assert types.index("tool.started") > first_text
    # Turn 2 (FinalResponse): deltas, then the committing assistant.text, then completed.
    assert types[-1] == "workflow.completed"
    assert types[-2] == "assistant.text"
    assert types[-3] == "assistant.text.delta"

    deltas = [e for e in sink.events if e.event_type == "assistant.text.delta"]
    blocks: dict[str, list] = {}
    for event in deltas:
        blocks.setdefault(event.payload.block_id, []).append(event.payload)
    assert len(blocks) == 2
    for payloads, final in zip(blocks.values(), [LONG_NARRATION, LONG_FINAL], strict=True):
        assert [p.chunk_index for p in payloads] == list(range(len(payloads)))
        assert final.startswith("".join(p.text for p in payloads))


async def test_stream_text_off_emits_the_unchanged_event_list():
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    sink = InMemoryEventSink()
    llm = FakeLLMService(script=_script(), stream_chunk_chars=4)

    await _streaming_runner(llm, sink, store, stream_text=False).run(run_id, product_ref="p")

    types = [e.event_type for e in sink.events]
    assert "assistant.text.delta" not in types
    # The FinalResponse is not narrated when nothing streamed (pre-P61-C shape).
    assert [e.payload.text for e in sink.events if e.event_type == "assistant.text"] == [
        LONG_NARRATION
    ]


async def test_banned_final_response_streams_only_clean_text_and_never_commits():
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    sink = InMemoryEventSink()
    final = LONG_FINAL + " " + BANNED
    llm = FakeLLMService(script=[_turn(FinalResponse(content=final))], stream_chunk_chars=4)

    result = await _streaming_runner(llm, sink, store).run(run_id, product_ref="p")

    assert result.stop_reason is StopReason.OUTPUT_VALIDATION_FAILED
    types = [e.event_type for e in sink.events]
    assert "assistant.text" not in types
    assert types[-1] == "workflow.failed"
    streamed = "".join(
        e.payload.text for e in sink.events if e.event_type == "assistant.text.delta"
    )
    assert "internal" not in streamed


class _FailsMidStream:
    """Streams some text, then the provider fails (the adapter's contract)."""

    async def complete(self, *, on_text_delta=None, **kwargs: Any):
        assert on_text_delta is not None
        for start in range(0, len(LONG_NARRATION), 4):
            await on_text_delta(LONG_NARRATION[start : start + 4])
        raise LLMProviderError("OpenAI Responses API stream failed: reset")


async def test_provider_error_mid_stream_fails_the_run_after_uncommitted_deltas():
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    sink = InMemoryEventSink()

    result = await _streaming_runner(_FailsMidStream(), sink, store).run(run_id, product_ref="p")

    assert result.stop_reason is StopReason.LLM_ERROR
    types = [e.event_type for e in sink.events]
    assert "assistant.text.delta" in types
    assert "assistant.text" not in types
    assert types[-1] == "workflow.failed"
