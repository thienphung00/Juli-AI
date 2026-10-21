"""P61-C (D71.3) -- the OpenAI Responses adapter's streaming leg.

A fake streaming transport (`httpx.MockTransport` serving recorded-shaped
Responses API server-sent events) drives `OpenAIResponsesAdapter.complete`
with an `on_text_delta` callback. Never a network call; the key is a patched
placeholder. Covers: text only, text + a tool call whose arguments arrive as
deltas, the terminal body omitting `output` (local assembly), a mid-stream
transport error / `response.failed` / `error` / a stream with no terminal
event (all -> `LLMProviderError`, a clean turn failure), and the
`LLM_STREAMING` flag off (non-streamed request, callback never called).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from juli_backend.services.agent.llm import LLMConfig
from juli_backend.services.agent.llm.blocks import FinalResponse, TextBlock, ToolCallBlock, Usage
from juli_backend.services.agent.llm.config import LLM_STREAMING_ENV_VAR, llm_streaming_enabled
from juli_backend.services.agent.llm.openai_adapter import LLMProviderError, OpenAIResponsesAdapter


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")
    monkeypatch.delenv(LLM_STREAMING_ENV_VAR, raising=False)


def _sse(events: list[dict[str, Any]]) -> bytes:
    """Frames exactly as the Responses API sends them: `event:` + `data:` + blank."""
    out = []
    for seq, event in enumerate(events):
        out.append(
            f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': seq})}\n\n"
        )
    return "".join(out).encode()


def _text_events(text_parts: list[str], *, item_id: str = "msg_1", index: int = 0) -> list[dict]:
    full = "".join(text_parts)
    item = {"type": "message", "id": item_id, "role": "assistant", "status": "completed"}
    return [
        {
            "type": "response.output_item.added",
            "output_index": index,
            "item": {**item, "content": []},
        },
        *[
            {
                "type": "response.output_text.delta",
                "item_id": item_id,
                "output_index": index,
                "content_index": 0,
                "delta": part,
            }
            for part in text_parts
        ],
        {
            "type": "response.output_text.done",
            "item_id": item_id,
            "output_index": index,
            "content_index": 0,
            "text": full,
        },
        {
            "type": "response.output_item.done",
            "output_index": index,
            "item": {**item, "content": [{"type": "output_text", "text": full, "annotations": []}]},
        },
    ]


def _tool_events(arg_parts: list[str], *, index: int) -> list[dict]:
    item = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_abc",
        "name": "get_product_information",
    }
    return [
        {
            "type": "response.output_item.added",
            "output_index": index,
            "item": {**item, "arguments": ""},
        },
        *[
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": index,
                "delta": part,
            }
            for part in arg_parts
        ],
        {
            "type": "response.function_call_arguments.done",
            "item_id": "fc_1",
            "output_index": index,
            "arguments": "".join(arg_parts),
        },
    ]


def _completed(output: list[dict] | None, *, usage=(120, 30)) -> dict:
    response: dict[str, Any] = {
        "id": "resp_1",
        "status": "completed",
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }
    if output is not None:
        response["output"] = output
    return {"type": "response.completed", "response": response}


def _transport(body: bytes | AsyncIterator[bytes], captured: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    return httpx.MockTransport(handler)


async def _run(transport: httpx.MockTransport, deltas: list[str] | None):
    adapter = OpenAIResponsesAdapter(transport=transport)

    async def on_delta(text: str) -> None:
        assert deltas is not None
        deltas.append(text)

    return await adapter.complete(
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tools=[],
        config=LLMConfig(),
        on_text_delta=on_delta if deltas is not None else None,
    )


async def test_text_only_streams_deltas_and_returns_the_same_final_turn():
    parts = ["Sản phẩm ", "của bạn ", "đã ổn."]
    events = _text_events(parts)
    events.append(_completed([events[-1]["item"]]))
    captured: list[dict] = []
    deltas: list[str] = []

    turn = await _run(_transport(_sse(events), captured), deltas)

    assert captured[0]["stream"] is True
    assert captured[0]["store"] is False
    assert deltas == parts
    assert turn.blocks == (FinalResponse(content="Sản phẩm của bạn đã ổn."),)
    assert turn.usage == Usage(input_tokens=120, output_tokens=30)


async def test_text_and_tool_call_assembles_arguments_from_deltas():
    text = _text_events(["Mình kiểm tra ", "thông tin trước."])
    tool = _tool_events(['{"product', '_ref": "p-', '1"}'], index=1)
    # Terminal body WITHOUT `output`: the turn must come from local assembly.
    events = [*text, *tool, _completed(None)]
    deltas: list[str] = []

    turn = await _run(_transport(_sse(events), []), deltas)

    assert deltas == ["Mình kiểm tra ", "thông tin trước."]
    assert turn.blocks == (
        TextBlock(text="Mình kiểm tra thông tin trước."),
        ToolCallBlock(
            call_id="call_abc",
            tool_name="get_product_information",
            arguments={"product_ref": "p-1"},
        ),
    )


async def test_assembled_turn_equals_the_terminal_body_turn():
    """The same stream with and without `output` on response.completed agrees."""
    text = _text_events(["a", "b"])
    tool = _tool_events(['{"x"', ": 1}"], index=1)
    final_items = [
        text[-1]["item"],
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_abc",
            "name": "get_product_information",
            "arguments": '{"x": 1}',
        },
    ]
    with_output = await _run(_transport(_sse([*text, *tool, _completed(final_items)]), []), [])
    assembled = await _run(_transport(_sse([*text, *tool, _completed(None)]), []), [])
    assert with_output == assembled


async def _broken_body(first: bytes) -> AsyncIterator[bytes]:
    yield first
    raise httpx.ReadError("connection reset mid-stream")


async def test_transport_error_mid_stream_fails_the_turn_cleanly():
    head = _sse(_text_events(["Đang "])[:2])
    deltas: list[str] = []
    with pytest.raises(LLMProviderError, match="stream failed"):
        await _run(_transport(_broken_body(head), []), deltas)
    assert deltas == ["Đang "]  # what arrived was relayed; no turn returned


@pytest.mark.parametrize(
    "terminal",
    [
        {
            "type": "response.failed",
            "response": {"error": {"code": "server_error", "message": "boom"}},
        },
        {"type": "error", "code": "rate_limit_exceeded", "message": "slow down"},
    ],
)
async def test_failed_or_error_event_raises_provider_error(terminal):
    events = [*_text_events(["x"])[:2], terminal]
    deltas: list[str] = []
    with pytest.raises(LLMProviderError) as exc_info:
        await _run(_transport(_sse(events), []), deltas)
    assert "OpenAI Responses API stream" in str(exc_info.value)
    assert deltas == ["x"]


async def test_stream_without_terminal_event_raises_provider_error():
    deltas: list[str] = []
    with pytest.raises(LLMProviderError, match="without response.completed"):
        await _run(_transport(_sse(_text_events(["x"])), []), deltas)
    assert deltas == ["x"]


async def test_non_json_frame_raises_provider_error():
    deltas: list[str] = []
    with pytest.raises(LLMProviderError, match="non-JSON"):
        await _run(_transport(b"data: {not json\n\n", []), deltas)
    assert deltas == []


async def test_http_error_status_on_stream_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error": {}}')

    deltas: list[str] = []
    with pytest.raises(LLMProviderError, match="HTTP 429"):
        await _run(httpx.MockTransport(handler), deltas)
    assert deltas == []


async def test_incomplete_terminal_is_parsed_like_the_non_streamed_body():
    events = _text_events(["cut"])
    events.append(
        {
            "type": "response.incomplete",
            "response": {
                "status": "incomplete",
                "output": [events[-1]["item"]],
                "usage": {"input_tokens": 5, "output_tokens": 1},
            },
        }
    )
    turn = await _run(_transport(_sse(events), []), [])
    assert turn.blocks == (FinalResponse(content="cut"),)


async def test_flag_off_sends_a_non_streamed_request_and_never_calls_back(monkeypatch):
    monkeypatch.setenv(LLM_STREAMING_ENV_VAR, "off")
    assert llm_streaming_enabled() is False
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "xong"}]}
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    deltas: list[str] = []
    turn = await _run(httpx.MockTransport(handler), deltas)
    assert captured[0]["stream"] is False
    assert deltas == []
    assert turn.blocks == (FinalResponse(content="xong"),)


async def test_no_callback_never_streams_even_with_the_flag_on():
    """Card drafts / structured analysis pass no callback and stay non-streamed."""
    assert llm_streaming_enabled() is True
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"output": [], "usage": {}})

    await _run(httpx.MockTransport(handler), None)
    assert captured[0]["stream"] is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", True),
        ("1", True),
        ("true", True),
        ("on", True),
        ("0", False),
        ("FALSE", False),
        (" no ", False),
        ("off", False),
    ],
)
def test_llm_streaming_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv(LLM_STREAMING_ENV_VAR, raw)
    assert llm_streaming_enabled() is expected


async def test_callback_exceptions_propagate_unchanged():
    events = _text_events(["x"])
    events.append(_completed([events[-1]["item"]]))
    adapter = OpenAIResponsesAdapter(transport=_transport(_sse(events), []))

    class SinkDown(RuntimeError):
        pass

    async def on_delta(text: str) -> None:
        raise SinkDown("db unavailable")

    with pytest.raises(SinkDown) as exc_info:
        await adapter.complete(
            messages=[], system="s", tools=[], config=LLMConfig(), on_text_delta=on_delta
        )
    assert not isinstance(exc_info.value, LLMProviderError)
