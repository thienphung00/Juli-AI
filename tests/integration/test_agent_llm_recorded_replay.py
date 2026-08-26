"""Replay-backed tool-calling round-trip for the LLM adapter — issue #989 (W1-B).

AC1 -> a replay harness records and replays provider HTTP exchanges, mirroring
       `tests/integration/tiktok_recorded_replay.py` (`llm_recorded_replay.py`).
AC2 -> one full tool-calling round-trip: request built from the real ADR-069
       registry, response parsed into Juli blocks with a tool call, usage
       populated (`TestRecordedToolCallRoundTrip`).
AC3 -> the live variant carries the `live` marker and is skipped without a key
       (`test_agent_llm_live_roundtrip.py`; deliberately not this file).
AC4 -> CI passes with no key present (`TestNoProviderKeyRequired`).

Unmarked on purpose: the issue-tier `test` job runs
`pytest tests/ -m "not live and not demo_contract and not migration_heavy and
not phase_scaffold"`, so this file runs on every PR — which is what "same test
green in CI via recorded replay" (PLAN.md P11 gate) requires.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from juli_backend.services.agent.llm import FinalResponse, TextBlock, ToolCallBlock
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.openai_adapter import OpenAIResponsesAdapter
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from tests.integration.llm_recorded_replay import (
    load_recorded_exchange,
    recorded_llm_transport,
)

REPLAY_API_KEY = "test-key-never-leaves-the-replay-transport"


def _registry_tool_definitions():
    """The real six ADR-069 capabilities in the neutral ToolDefinition shape."""
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return [
        {
            "name": spec.name,
            "description": spec.description,
            # The key `ToolDefinition` declares and `WorkflowRunner`
            # produces. This said `parameters` -- the adapter's own internal
            # wire key -- so even the recorded round-trip, the test closest
            # to a real provider call, agreed with the consumer instead of
            # the producer and never caught the mismatch.
            "input_schema": spec.render_input_schema(),
        }
        for spec in sorted(registry.list_all(), key=lambda spec: spec.name)
    ]


async def _complete_through_replay(captured=None):
    exchange = load_recorded_exchange()
    transport = recorded_llm_transport(exchange, captured=captured)
    adapter = OpenAIResponsesAdapter(transport=transport)
    with patch.dict(os.environ, {"OPENAI_API_KEY": REPLAY_API_KEY}):
        return await adapter.complete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Start optimizing this listing. Look up the product information first."
                    ),
                }
            ],
            system=(
                "You are Juli, optimizing a TikTok Shop listing. The product is already "
                "bound to this run - tools take no identifier arguments."
            ),
            tools=_registry_tool_definitions(),
            config=LLMConfig(),
        )


class TestRecordedToolCallRoundTrip:
    """One full round-trip: request built, response parsed, usage populated."""

    @pytest.mark.asyncio
    async def test_response_parses_into_a_tool_call_block(self):
        turn = await _complete_through_replay()
        tool_calls = [block for block in turn.blocks if isinstance(block, ToolCallBlock)]
        assert len(tool_calls) == 1, f"expected exactly one tool call, got {turn.blocks!r}"
        assert tool_calls[0].tool_name == "get_product_information"
        assert tool_calls[0].call_id
        assert isinstance(tool_calls[0].arguments, dict)

    @pytest.mark.asyncio
    async def test_a_tool_calling_turn_is_not_a_final_response(self):
        """A turn proposing a tool call must not close the loop (ADR-071)."""
        turn = await _complete_through_replay()
        assert not [block for block in turn.blocks if isinstance(block, FinalResponse)]

    @pytest.mark.asyncio
    async def test_usage_is_populated_from_the_recorded_response(self):
        turn = await _complete_through_replay()
        assert turn.usage.input_tokens > 0
        assert turn.usage.output_tokens > 0

    @pytest.mark.asyncio
    async def test_request_carries_every_registry_tool(self):
        """The request half of the contract — a response-only fixture would miss this."""
        captured: dict = {}
        await _complete_through_replay(captured)
        sent_tools = [tool["name"] for tool in captured["body"]["tools"]]
        assert sorted(sent_tools) == [
            "check_product_status",
            # ADR-088: the terminal tool is offered alongside the playbook's own
            # tools so the model always has a legitimate way to end a run it has
            # nothing to propose for — which is what makes tool_choice="required"
            # safe on the forced retry.
            "conclude_without_changes",
            "get_product_information",
            "get_seo_keywords",
            # #1208: the image step became a READ inspection. upload stays
            # registered for the future generation capability.
            "inspect_product_image",
            "update_product_listing",
            "update_product_price",
            "upload_product_image",
        ]
        assert all(tool["type"] == "function" for tool in captured["body"]["tools"])

    @pytest.mark.asyncio
    async def test_request_is_stateless_and_non_streaming(self):
        """ADR-071 decision 2: never provider-side state, never streamed."""
        captured: dict = {}
        await _complete_through_replay(captured)
        body = captured["body"]
        assert "previous_response_id" not in body
        assert body["store"] is False
        assert body["stream"] is False

    @pytest.mark.asyncio
    async def test_request_reaches_the_responses_endpoint_with_authorization(self):
        captured: dict = {}
        await _complete_through_replay(captured)
        assert captured["method"] == "POST"
        assert captured["url"].endswith("/v1/responses")
        assert captured["has_authorization"] is True


class TestNoProviderKeyRequired:
    """CI must pass with no key present — the replay never reaches the network."""

    @pytest.mark.asyncio
    async def test_round_trip_works_without_a_real_provider_key(self):
        turn = await _complete_through_replay()
        assert turn.blocks

    def test_no_real_key_is_committed_in_the_fixture(self):
        """The fixture records the request body only — never headers."""
        raw = json.dumps(load_recorded_exchange())
        assert "Authorization" not in raw
        assert "sk-" not in raw

    def test_fixture_records_no_provider_headers_at_all(self):
        exchange = load_recorded_exchange()
        assert "headers" not in exchange
        assert "headers" not in exchange["request"]


class TestFixtureShape:
    """Guards the fixture contract the live re-record must keep satisfying."""

    def test_fixture_declares_its_provenance_and_model(self):
        exchange = load_recorded_exchange()
        assert exchange["provenance"]
        assert exchange["model"]

    def test_recorded_response_is_a_tool_calling_turn(self):
        exchange = load_recorded_exchange()
        types = [item.get("type") for item in exchange["response"]["output"]]
        assert "function_call" in types, (
            "the recorded response must be a tool-calling turn; re-record with a "
            "prompt that forces a tool call"
        )

    def test_text_only_turn_would_parse_as_a_final_response(self):
        """Sanity-check the other branch of the parser against a synthetic body."""
        exchange = {
            "response": {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 1},
            }
        }
        transport = recorded_llm_transport(exchange)
        adapter = OpenAIResponsesAdapter(transport=transport)

        async def run():
            with patch.dict(os.environ, {"OPENAI_API_KEY": REPLAY_API_KEY}):
                return await adapter.complete(
                    messages=[{"role": "user", "content": "hi"}],
                    system="s",
                    tools=[],
                    config=LLMConfig(),
                )

        import asyncio

        turn = asyncio.run(run())
        assert [type(block) for block in turn.blocks] == [FinalResponse]
        assert not [block for block in turn.blocks if isinstance(block, TextBlock)]
