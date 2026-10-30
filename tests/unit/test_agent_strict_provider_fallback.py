"""The adapter's safety net for strict schemas OpenAI rejects (P76-1, D78).

Nobody has seen live OpenAI accept Juli's strict wire on ``gpt-5.4-nano``. If it
answered 400 for a schema, every agent run would fail. So a 400 that names a schema
is retried once non-strict, the culprit is remembered for the process, and
``AGENT_STRICT_SCHEMAS`` turns strict off wholesale. Driven over `httpx.MockTransport`
with OpenAI's documented error shape; no network.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from juli_backend.services.agent.llm import LLMConfig
from juli_backend.services.agent.llm.blocks import FinalResponse
from juli_backend.services.agent.llm.config import (
    AGENT_STRICT_SCHEMAS_ENV_VAR,
    LLM_STREAMING_ENV_VAR,
    agent_strict_schemas_enabled,
)
from juli_backend.services.agent.llm.openai_adapter import (
    JsonSchemaFormat,
    LLMProviderError,
    OpenAIResponsesAdapter,
    reset_strict_circuit,
)
from juli_backend.services.agent.llm.service import ToolDefinition
from tests.support.consent import granted_gate

_TOOLS: list[ToolDefinition] = [
    {
        "name": "update_product_listing",
        "description": "Write the listing.",
        "input_schema": {
            "type": "object",
            "properties": {"attach_staged_image": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "get_product_information",
        "description": "Read the product.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
_FORMAT = JsonSchemaFormat(
    name="content_analysis",
    schema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
)
_OK_BODY: dict[str, Any] = {
    "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "Xong."}]},
    ],
    "usage": {"input_tokens": 10, "output_tokens": 2},
}
_SCHEMA_400 = {
    "error": {
        "message": (
            "Invalid schema for function 'update_product_listing': In context=(), "
            "'additionalProperties' is required to be supplied and to be false."
        ),
        "type": "invalid_request_error",
        "param": "tools[0].parameters",
        "code": "invalid_function_parameters",
    }
}
_FORMAT_400 = {
    "error": {
        "message": "Invalid schema for response_format 'content_analysis'.",
        "type": "invalid_request_error",
        "param": "text.format.schema",
        "code": "invalid_json_schema",
    }
}
_CONTEXT_400 = {
    "error": {
        "message": "Your input exceeds the context window of this model.",
        "type": "invalid_request_error",
        "param": "input",
        "code": "context_length_exceeded",
    }
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")
    monkeypatch.delenv(AGENT_STRICT_SCHEMAS_ENV_VAR, raising=False)
    monkeypatch.delenv(LLM_STREAMING_ENV_VAR, raising=False)
    reset_strict_circuit()
    yield
    reset_strict_circuit()


class _Provider:
    """Answers with the queued (status, body) pairs and records every request body."""

    def __init__(self, *answers: tuple[int, dict[str, Any]], stream: bool = False) -> None:
        self._answers = list(answers)
        self._stream = stream
        self.requests: list[dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(request.content))
            status, body = self._answers.pop(0)
            if status == 200 and self._stream:
                return httpx.Response(200, content=_sse_completed(body))
            return httpx.Response(status, json=body)

        return httpx.MockTransport(handler)


def _sse_completed(body: dict[str, Any]) -> bytes:
    event = {"type": "response.completed", "response": body}
    return f"data: {json.dumps(event)}\n\n".encode()


async def _complete(provider: _Provider, *, response_format=None, on_text_delta=None):
    adapter = OpenAIResponsesAdapter(gate=granted_gate(), transport=provider.transport())
    return await adapter.complete(
        messages=[{"role": "user", "content": "hi"}],
        system="system",
        tools=_TOOLS,
        config=LLMConfig(),
        response_format=response_format,
        on_text_delta=on_text_delta,
    )


def _strict_flags(request: dict[str, Any]) -> dict[str, bool]:
    return {tool["name"]: tool["strict"] for tool in request["tools"]}


async def test_schema_rejection_is_retried_once_non_strict_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _Provider((400, _SCHEMA_400), (200, _OK_BODY))
    with caplog.at_level(logging.ERROR):
        turn = await _complete(provider)

    assert turn.blocks == (FinalResponse(content="Xong."),)
    assert len(provider.requests) == 2
    assert _strict_flags(provider.requests[0]) == {
        "update_product_listing": True,
        "get_product_information": True,
    }
    assert _strict_flags(provider.requests[1]) == {
        "update_product_listing": False,
        "get_product_information": False,
    }
    # The retry sends the schema as declared, not the strict rewrite.
    assert provider.requests[1]["tools"][0]["parameters"] == _TOOLS[0]["input_schema"]
    record = next(r for r in caplog.records if r.message == "strict_schema_rejected_by_provider")
    assert record.__dict__["rejected"] == ["tool:update_product_listing"]
    assert record.__dict__["param"] == "tools[0].parameters"
    assert record.__dict__["error_code"] == "invalid_function_parameters"


async def test_a_rejected_tool_goes_non_strict_directly_on_the_next_call() -> None:
    await _complete(_Provider((400, _SCHEMA_400), (200, _OK_BODY)))

    provider = _Provider((200, _OK_BODY))
    await _complete(provider)

    assert len(provider.requests) == 1
    assert _strict_flags(provider.requests[0]) == {
        "update_product_listing": False,
        "get_product_information": True,
    }


async def test_a_rejected_output_format_is_remembered_by_name() -> None:
    first = _Provider((400, _FORMAT_400), (200, _OK_BODY))
    await _complete(first, response_format=_FORMAT)
    assert first.requests[0]["text"]["format"]["strict"] is True
    assert first.requests[1]["text"]["format"]["strict"] is False

    second = _Provider((200, _OK_BODY))
    await _complete(second, response_format=_FORMAT)
    assert second.requests[0]["text"]["format"]["strict"] is False
    assert all(_strict_flags(second.requests[0]).values())


async def test_an_unrelated_400_is_not_retried() -> None:
    provider = _Provider((400, _CONTEXT_400), (200, _OK_BODY))
    with pytest.raises(LLMProviderError, match="HTTP 400"):
        await _complete(provider)
    assert len(provider.requests) == 1


async def test_a_failed_retry_raises_the_provider_error() -> None:
    provider = _Provider((400, _SCHEMA_400), (500, {"error": {"message": "boom"}}))
    with pytest.raises(LLMProviderError, match="HTTP 500"):
        await _complete(provider)
    assert len(provider.requests) == 2


@pytest.mark.parametrize("raw", ["0", "false", "OFF"])
async def test_kill_switch_sends_nothing_strict(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(AGENT_STRICT_SCHEMAS_ENV_VAR, raw)
    provider = _Provider((200, _OK_BODY))
    await _complete(provider, response_format=_FORMAT)

    request = provider.requests[0]
    assert not any(_strict_flags(request).values())
    assert request["text"]["format"]["strict"] is False
    assert request["tools"][0]["parameters"] == _TOOLS[0]["input_schema"]


@pytest.mark.parametrize(("raw", "expected"), [("", True), ("1", True), ("no", False)])
def test_kill_switch_parsing(monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
    monkeypatch.setenv(AGENT_STRICT_SCHEMAS_ENV_VAR, raw)
    assert agent_strict_schemas_enabled() is expected


async def test_streamed_call_retries_a_schema_rejection_too() -> None:
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    provider = _Provider((400, _SCHEMA_400), (200, _OK_BODY), stream=True)
    turn = await _complete(provider, on_text_delta=on_delta)

    assert turn.blocks == (FinalResponse(content="Xong."),)
    assert [request["stream"] for request in provider.requests] == [True, True]
    assert _strict_flags(provider.requests[1]) == {
        "update_product_listing": False,
        "get_product_information": False,
    }


async def test_streamed_unrelated_400_is_not_retried() -> None:
    async def on_delta(text: str) -> None:
        return None

    provider = _Provider((400, _CONTEXT_400), (200, _OK_BODY), stream=True)
    with pytest.raises(LLMProviderError, match="HTTP 400"):
        await _complete(provider, on_text_delta=on_delta)
    assert len(provider.requests) == 1
