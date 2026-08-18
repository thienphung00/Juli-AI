"""Issue #986 — Stateless OpenAI Responses adapter (ADR-071 decisions 2, 3, 5).

Exercises `OpenAIResponsesAdapter.complete` (the `LLMService` protocol from
#985) against a stubbed httpx transport carrying literal, recorded-shaped
OpenAI Responses API request/response bodies. No network call is made and no
API key is used or requested -- `OPENAI_API_KEY` is always a patched,
never-real value (matching the pattern in `test_agent_llm_contract.py`).

The `openai` PyPI package is not declared in `backend/pyproject.toml` /
`backend/constraints.txt` (verified before writing this slice), so the
adapter is built directly on `httpx` -- already a declared dependency --
targeting the Responses API's HTTP surface rather than the vendor SDK. No
`import openai` appears anywhere in this module or in the adapter it tests;
the containment concern (ADR-071 decision 1 / decision 6) is trivially
satisfied because the vendor SDK is never imported.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from juli_backend.services.agent.llm import LLMConfig, LLMService
from juli_backend.services.agent.llm.blocks import (
    FinalResponse,
    TextBlock,
    ToolCallBlock,
)
from juli_backend.services.agent.llm.config import (
    PRICE_TABLE_USD_PER_MILLION_TOKENS,
    estimate_cost_usd,
)
from juli_backend.services.agent.llm.openai_adapter import (
    LLMProviderError,
    OpenAIResponsesAdapter,
)

_LLM_ENV_VARS = (
    "OPENAI_API_KEY",
    "LLM_MODEL",
    "LLM_MAX_OUTPUT_TOKENS",
    "LLM_TEMPERATURE",
    "LLM_REQUEST_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from the ambient shell/.env -- no real key, no leaks."""
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def _with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A patched (never real) key, matching the require_env pattern used elsewhere."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")


# ---------------------------------------------------------------------------
# Recorded-shaped fixtures -- literal OpenAI Responses API payloads
# ---------------------------------------------------------------------------

RECORDED_RESPONSE_TEXT_AND_TOOL_CALL: dict[str, Any] = {
    "id": "resp_test_001",
    "object": "response",
    "created_at": 1_755_000_000,
    "model": "gpt-5.4-nano",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "id": "msg_001",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Checking current stock before touching the price.",
                    "annotations": [],
                }
            ],
        },
        {
            "type": "function_call",
            "id": "fc_001",
            "call_id": "call_abc123",
            "name": "get_inventory",
            "arguments": '{"sku": "SKU-42"}',
            "status": "completed",
        },
    ],
    "usage": {
        "input_tokens": 812,
        "output_tokens": 63,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 875,
    },
}

RECORDED_RESPONSE_TEXT_ONLY: dict[str, Any] = {
    "id": "resp_test_002",
    "object": "response",
    "created_at": 1_755_000_100,
    "model": "gpt-5.4-nano",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "id": "msg_002",
            "status": "completed",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Stock looks healthy at 214 units.",
                    "annotations": [],
                }
            ],
        }
    ],
    "usage": {"input_tokens": 240, "output_tokens": 18, "total_tokens": 258},
}

RECORDED_RESPONSE_MULTIPLE_TOOL_CALLS: dict[str, Any] = {
    "id": "resp_test_003",
    "object": "response",
    "model": "gpt-5.4-nano",
    "status": "completed",
    "output": [
        {
            "type": "function_call",
            "id": "fc_002",
            "call_id": "call_one",
            "name": "get_product_information",
            "arguments": "{}",
            "status": "completed",
        },
        {
            "type": "function_call",
            "id": "fc_003",
            "call_id": "call_two",
            "name": "get_seo_keywords",
            "arguments": '{"product_id": "p_1"}',
            "status": "completed",
        },
    ],
    "usage": {"input_tokens": 500, "output_tokens": 40, "total_tokens": 540},
}

RECORDED_RESPONSE_MALFORMED_TOOL_ARGS: dict[str, Any] = {
    "id": "resp_test_004",
    "object": "response",
    "model": "gpt-5.4-nano",
    "status": "completed",
    "output": [
        {
            "type": "function_call",
            "id": "fc_004",
            "call_id": "call_bad",
            "name": "get_inventory",
            "arguments": "{not valid json",
            "status": "completed",
        },
    ],
    "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
}


def _stub_transport(
    *,
    response_body: dict[str, Any] | None = None,
    status_code: int = 200,
    captured_requests: list[dict[str, Any]] | None = None,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> httpx.MockTransport:
    call_count = {"n": 0}

    def _handle(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if captured_requests is not None:
            captured_requests.append(json.loads(request.content))
        if handler is not None:
            return handler(request)
        return httpx.Response(status_code, json=response_body)

    transport = httpx.MockTransport(_handle)
    transport.call_count = call_count  # type: ignore[attr-defined]
    return transport


def _config(**overrides: Any) -> LLMConfig:
    defaults = {
        "model": "gpt-5.4-nano",
        "max_output_tokens": 512,
        "temperature": 0.2,
        "request_timeout_seconds": 10.0,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestAdapterSatisfiesLLMServiceProtocol:
    def test_adapter_is_an_llm_service(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_TEXT_ONLY)
        )
        assert isinstance(adapter, LLMService)


# ---------------------------------------------------------------------------
# Response -> Juli block translation, asserted through the public interface
# ---------------------------------------------------------------------------


class TestResponseTranslatedToJuliBlocks:
    async def test_text_and_tool_call_response_yields_text_and_tool_call_blocks(
        self, _with_api_key
    ):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_TEXT_AND_TOOL_CALL)
        )

        turn = await adapter.complete(
            messages=[{"role": "user", "content": "Update the price for SKU-42."}],
            system="You are Juli's optimize-product agent.",
            tools=[
                {
                    "name": "get_inventory",
                    "description": "Look up current stock for a SKU.",
                    "parameters": {
                        "type": "object",
                        "properties": {"sku": {"type": "string"}},
                        "required": ["sku"],
                    },
                }
            ],
            config=_config(),
        )

        assert len(turn.blocks) == 2
        text_block, tool_call_block = turn.blocks

        assert isinstance(text_block, TextBlock)
        assert text_block.text == "Checking current stock before touching the price."

        assert isinstance(tool_call_block, ToolCallBlock)
        assert tool_call_block.call_id == "call_abc123"
        assert tool_call_block.tool_name == "get_inventory"
        assert tool_call_block.arguments == {"sku": "SKU-42"}

    async def test_text_only_response_yields_a_final_response_block(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_TEXT_ONLY)
        )

        turn = await adapter.complete(
            messages=[{"role": "user", "content": "Is stock healthy?"}],
            system="You are Juli's optimize-product agent.",
            tools=[],
            config=_config(),
        )

        assert len(turn.blocks) == 1
        (block,) = turn.blocks
        assert isinstance(block, FinalResponse)
        assert block.content == "Stock looks healthy at 214 units."
        assert block.structured_output is None

    async def test_multiple_tool_calls_in_one_turn_all_translate(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_MULTIPLE_TOOL_CALLS)
        )

        turn = await adapter.complete(
            messages=[{"role": "user", "content": "Run the optimize playbook."}],
            system="system prompt",
            tools=[],
            config=_config(),
        )

        assert len(turn.blocks) == 2
        assert all(isinstance(block, ToolCallBlock) for block in turn.blocks)
        assert [block.tool_name for block in turn.blocks] == [
            "get_product_information",
            "get_seo_keywords",
        ]
        assert turn.blocks[1].arguments == {"product_id": "p_1"}

    async def test_no_provider_wire_type_appears_in_returned_blocks(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_TEXT_AND_TOOL_CALL)
        )

        turn = await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        # Every returned block is one of Juli's own dataclasses, from the
        # `juli_backend.services.agent.llm.blocks` module -- never a raw dict
        # or SDK-shaped object lifted straight off the wire.
        for block in turn.blocks:
            assert type(block).__module__ == "juli_backend.services.agent.llm.blocks"


# ---------------------------------------------------------------------------
# Usage + static-price-table cost estimate
# ---------------------------------------------------------------------------


class TestUsageAndCostEstimate:
    async def test_usage_is_populated_from_the_provider_response(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_TEXT_AND_TOOL_CALL)
        )

        turn = await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert turn.usage.input_tokens == 812
        assert turn.usage.output_tokens == 63

    def test_cost_estimate_is_derived_from_the_static_price_table(self):
        price = PRICE_TABLE_USD_PER_MILLION_TOKENS["gpt-5.4-nano"]
        from juli_backend.services.agent.llm.blocks import Usage

        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = estimate_cost_usd("gpt-5.4-nano", usage)

        expected = price.input_usd_per_million_tokens + price.output_usd_per_million_tokens
        assert cost == pytest.approx(expected)

    def test_cost_estimate_for_unpriced_model_is_zero_not_an_error(self):
        from juli_backend.services.agent.llm.blocks import Usage

        usage = Usage(input_tokens=100, output_tokens=50)
        assert estimate_cost_usd("some-future-model-not-in-table", usage) == 0.0


# ---------------------------------------------------------------------------
# Statelessness: no provider-side thread state on the outbound request
# ---------------------------------------------------------------------------


class TestOutboundRequestCarriesNoThreadState:
    async def test_request_body_never_carries_previous_response_id(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert len(captured) == 1
        assert "previous_response_id" not in captured[0]

    async def test_request_body_explicitly_disables_server_side_storage(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert captured[0]["store"] is False

    async def test_full_message_window_is_rebuilt_every_call(self, _with_api_key):
        """Statelessness in the affirmative: the whole window rides on the wire."""
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[
                {"role": "user", "content": "First message."},
                {"role": "assistant", "content": "First reply."},
                {"role": "user", "content": "Second message."},
            ],
            system="system prompt",
            tools=[],
            config=_config(),
        )

        body = captured[0]
        assert body["instructions"] == "system prompt"
        assert len(body["input"]) == 3


# ---------------------------------------------------------------------------
# Non-streamed: one complete turn, never token deltas
# ---------------------------------------------------------------------------


class TestNonStreamed:
    async def test_request_disables_streaming(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert captured[0]["stream"] is False

    async def test_complete_makes_exactly_one_http_call(self, _with_api_key):
        transport = _stub_transport(response_body=RECORDED_RESPONSE_TEXT_ONLY)
        adapter = OpenAIResponsesAdapter(transport=transport)

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert transport.call_count["n"] == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Request translation: system, tools, config surface onto the wire body
# ---------------------------------------------------------------------------


class TestRequestTranslation:
    async def test_model_and_generation_config_are_forwarded(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system prompt",
            tools=[],
            config=_config(model="gpt-5.4-nano", max_output_tokens=777, temperature=0.55),
        )

        body = captured[0]
        assert body["model"] == "gpt-5.4-nano"
        assert body["max_output_tokens"] == 777
        assert body["temperature"] == pytest.approx(0.55)

    async def test_tool_schemas_translate_into_function_tools(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[
                {
                    "name": "get_inventory",
                    "description": "Look up current stock for a SKU.",
                    "parameters": {
                        "type": "object",
                        "properties": {"sku": {"type": "string"}},
                        "required": ["sku"],
                    },
                }
            ],
            config=_config(),
        )

        (tool,) = captured[0]["tools"]
        assert tool["type"] == "function"
        assert tool["name"] == "get_inventory"
        assert tool["description"] == "Look up current stock for a SKU."
        assert tool["parameters"]["properties"]["sku"]["type"] == "string"

    async def test_no_tools_translates_to_an_empty_tools_list(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert captured[0]["tools"] == []

    async def test_a_tool_result_message_translates_to_function_call_output(self, _with_api_key):
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        await adapter.complete(
            messages=[
                {"role": "user", "content": "Check stock for SKU-42."},
                {
                    "role": "tool",
                    "call_id": "call_abc123",
                    "content": '{"sku": "SKU-42", "quantity": 214}',
                },
            ],
            system="system",
            tools=[],
            config=_config(),
        )

        tool_result_item = captured[0]["input"][1]
        assert tool_result_item["type"] == "function_call_output"
        assert tool_result_item["call_id"] == "call_abc123"
        assert tool_result_item["output"] == '{"sku": "SKU-42", "quantity": 214}'

    async def test_a_runner_appended_tool_message_translates_with_the_correct_call_id(
        self, _with_api_key
    ):
        """Issue #1177 -- pins the REAL key contract the runner writes.

        `WorkflowRunner` in `services/agent/runner/core.py` never appends a
        tool message shaped like this test file's other fixtures (which
        predate this issue and use ``"call_id"``). It appends the literal
        dict shape below at three call sites -- `resume()` (lines 383-390 and
        442-449) and `_execute_tool_call` (lines 676-683) -- keyed
        ``"tool_call_id"``, not ``"call_id"``:

            {
                "role": "tool",
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "content": dict(sanitized),
            }

        Before this issue's fix, `_translate_message` read
        ``message.get("call_id", "")`` for role:tool messages, so every
        second round-trip (any real run that calls a tool) reached OpenAI
        with an empty ``call_id`` on the `function_call_output` item. This
        test builds the message exactly as the runner does (no shortcuts)
        and asserts the translated wire payload carries the real id through.
        """
        captured: list[dict[str, Any]] = []
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body=RECORDED_RESPONSE_TEXT_ONLY, captured_requests=captured
            )
        )

        # Exact literal shape of `state.conversation_window.append({...})`
        # in `services/agent/runner/core.py` (e.g. lines 676-683).
        runner_appended_tool_message = {
            "role": "tool",
            "tool_call_id": "call_abc123",
            "tool_name": "get_inventory",
            "content": {"sku": "SKU-42", "quantity": 214},
        }

        await adapter.complete(
            messages=[
                {"role": "user", "content": "Check stock for SKU-42."},
                runner_appended_tool_message,
            ],
            system="system",
            tools=[],
            config=_config(),
        )

        tool_result_item = captured[0]["input"][1]
        assert tool_result_item["type"] == "function_call_output"
        assert tool_result_item["call_id"] == "call_abc123"

    async def test_authorization_header_carries_the_api_key(self, _with_api_key):
        captured_headers: list[httpx.Headers] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(request.headers)
            return httpx.Response(200, json=RECORDED_RESPONSE_TEXT_ONLY)

        adapter = OpenAIResponsesAdapter(transport=_stub_transport(handler=_handler))

        await adapter.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="system",
            tools=[],
            config=_config(),
        )

        assert captured_headers[0]["authorization"] == "Bearer sk-test-patched-not-real"


# ---------------------------------------------------------------------------
# Fail-closed API key + provider error translation
# ---------------------------------------------------------------------------


class TestProviderErrorsSurfaceAsJuliLevelErrors:
    async def test_missing_api_key_raises_before_any_network_call(self):
        """No _with_api_key fixture here -- the key is absent, matching the
        require_env fail-closed pattern from #985's LLMConfig resolution."""
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_TEXT_ONLY)
        )

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            await adapter.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="system",
                tools=[],
                config=_config(),
            )

    async def test_http_error_status_surfaces_as_llm_provider_error(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(
                response_body={"error": {"message": "invalid_api_key"}}, status_code=401
            )
        )

        with pytest.raises(LLMProviderError):
            await adapter.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="system",
                tools=[],
                config=_config(),
            )

    async def test_server_error_surfaces_as_llm_provider_error_not_raw_httpx(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body={"error": {"message": "boom"}}, status_code=500)
        )

        with pytest.raises(LLMProviderError) as excinfo:
            await adapter.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="system",
                tools=[],
                config=_config(),
            )

        assert not isinstance(excinfo.value, httpx.HTTPError)

    async def test_malformed_tool_call_arguments_surface_as_llm_provider_error(self, _with_api_key):
        adapter = OpenAIResponsesAdapter(
            transport=_stub_transport(response_body=RECORDED_RESPONSE_MALFORMED_TOOL_ARGS)
        )

        with pytest.raises(LLMProviderError):
            await adapter.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="system",
                tools=[],
                config=_config(),
            )

    async def test_transport_level_failure_surfaces_as_llm_provider_error(self, _with_api_key):
        def _raise(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = OpenAIResponsesAdapter(transport=httpx.MockTransport(_raise))

        with pytest.raises(LLMProviderError) as excinfo:
            await adapter.complete(
                messages=[{"role": "user", "content": "hi"}],
                system="system",
                tools=[],
                config=_config(),
            )

        assert not isinstance(excinfo.value, httpx.HTTPError)


# ---------------------------------------------------------------------------
# No provider SDK import anywhere in this test module or the adapter it tests
# ---------------------------------------------------------------------------


class TestNoProviderSdkImport:
    def test_adapter_module_does_not_import_the_openai_package(self):
        import ast
        from pathlib import Path

        adapter_path = (
            Path(__file__).resolve().parents[2]
            / "backend/src/juli_backend/services/agent/llm/openai_adapter.py"
        )
        tree = ast.parse(adapter_path.read_text(), filename=str(adapter_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                assert name.split(".")[0].lower() != "openai", (
                    "adapter must not import the openai package "
                    "(undeclared in backend/pyproject.toml / constraints.txt)"
                )
