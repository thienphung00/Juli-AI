"""Issue #987 — Fake `LLMService` with scripted turns (ADR-071 decision 6).

The fake is a **shipped artifact**, not a test-local helper: downstream suites
(the WorkflowRunner in W3-A above all) depend on it to exercise loop behavior
exhaustively without network, cost, or non-determinism. This module exercises
the fake itself, exactly as any other caller of the `LLMService` protocol
would.

No provider dependency: this file and the module it tests import nothing
beyond the `agent/llm` package and the standard library.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

import pytest

from juli_backend.services.agent.llm import (
    AssistantTurn,
    FinalResponse,
    LLMConfig,
    LLMService,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.fake import FakeLLMService, ScriptExhaustedError


def _config(**overrides) -> LLMConfig:
    defaults = {
        "model": "gpt-5.4-nano",
        "max_output_tokens": 512,
        "temperature": 0.2,
        "request_timeout_seconds": 10.0,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _text_turn(text: str) -> AssistantTurn:
    return AssistantTurn(
        blocks=(TextBlock(text=text),),
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _tool_call_turn(tool_name: str, call_id: str = "call_1") -> AssistantTurn:
    return AssistantTurn(
        blocks=(ToolCallBlock(call_id=call_id, tool_name=tool_name, arguments={"x": 1}),),
        usage=Usage(input_tokens=2, output_tokens=2),
    )


def _final_turn(content: str) -> AssistantTurn:
    return AssistantTurn(
        blocks=(FinalResponse(content=content),),
        usage=Usage(input_tokens=3, output_tokens=3),
    )


# ---------------------------------------------------------------------------
# Protocol conformance -- a caller must not be able to tell the fake from the
# real adapter by type.
# ---------------------------------------------------------------------------


class TestFakeSatisfiesLLMServiceProtocol:
    def test_fake_is_an_llm_service(self):
        fake = FakeLLMService(script=[_text_turn("hi")])
        assert isinstance(fake, LLMService)

    def test_fake_complete_signature_matches_protocol(self):
        import inspect

        signature = inspect.signature(FakeLLMService.complete)
        protocol_signature = inspect.signature(LLMService.complete)
        assert list(signature.parameters) == list(protocol_signature.parameters)

    def test_llm_service_protocol_is_still_a_protocol(self):
        # Sanity check this test file hasn't drifted from #985's contract.
        assert Protocol in LLMService.__mro__


# ---------------------------------------------------------------------------
# Scripting: plain text, tool call, final response
# ---------------------------------------------------------------------------


class TestScriptedTurnShapes:
    async def test_scripts_a_plain_text_turn(self):
        fake = FakeLLMService(script=[_text_turn("Checking inventory now.")])

        turn = await fake.complete(messages=[], system="", tools=[], config=_config())

        assert len(turn.blocks) == 1
        assert isinstance(turn.blocks[0], TextBlock)
        assert turn.blocks[0].text == "Checking inventory now."

    async def test_scripts_a_tool_call_turn(self):
        fake = FakeLLMService(script=[_tool_call_turn("get_inventory")])

        turn = await fake.complete(messages=[], system="", tools=[], config=_config())

        assert len(turn.blocks) == 1
        assert isinstance(turn.blocks[0], ToolCallBlock)
        assert turn.blocks[0].tool_name == "get_inventory"
        assert turn.blocks[0].call_id == "call_1"

    async def test_scripts_a_final_response_turn(self):
        fake = FakeLLMService(script=[_final_turn("Stock looks healthy.")])

        turn = await fake.complete(messages=[], system="", tools=[], config=_config())

        assert len(turn.blocks) == 1
        assert isinstance(turn.blocks[0], FinalResponse)
        assert turn.blocks[0].content == "Stock looks healthy."

    async def test_returns_the_exact_scripted_assistant_turn_object(self):
        scripted = _text_turn("verbatim")
        fake = FakeLLMService(script=[scripted])

        turn = await fake.complete(messages=[], system="", tools=[], config=_config())

        assert turn == scripted


# ---------------------------------------------------------------------------
# Sequencing: turns consumed in order across successive calls
# ---------------------------------------------------------------------------


class TestScriptSequencing:
    async def test_turns_are_returned_in_scripted_order(self):
        first = _text_turn("first")
        second = _tool_call_turn("get_inventory")
        third = _final_turn("done")
        fake = FakeLLMService(script=[first, second, third])

        turn_one = await fake.complete(messages=[], system="", tools=[], config=_config())
        turn_two = await fake.complete(messages=[], system="", tools=[], config=_config())
        turn_three = await fake.complete(messages=[], system="", tools=[], config=_config())

        assert turn_one is first
        assert turn_two is second
        assert turn_three is third

    async def test_a_fresh_fake_starts_from_the_beginning_of_its_own_script(self):
        # Two independently constructed fakes must not share cursor state.
        fake_a = FakeLLMService(script=[_text_turn("a1"), _text_turn("a2")])
        fake_b = FakeLLMService(script=[_text_turn("b1")])

        turn_a1 = await fake_a.complete(messages=[], system="", tools=[], config=_config())
        turn_b1 = await fake_b.complete(messages=[], system="", tools=[], config=_config())
        turn_a2 = await fake_a.complete(messages=[], system="", tools=[], config=_config())

        assert turn_a1.blocks[0].text == "a1"
        assert turn_b1.blocks[0].text == "b1"
        assert turn_a2.blocks[0].text == "a2"


# ---------------------------------------------------------------------------
# Exhaustion: running past the end of the script raises a clear error
# ---------------------------------------------------------------------------


class TestScriptExhaustion:
    async def test_calling_past_the_end_of_the_script_raises_script_exhausted_error(
        self,
    ):
        fake = FakeLLMService(script=[_text_turn("only turn")])
        await fake.complete(messages=[], system="", tools=[], config=_config())

        with pytest.raises(ScriptExhaustedError):
            await fake.complete(messages=[], system="", tools=[], config=_config())

    async def test_exhaustion_error_is_a_specific_catchable_type(self):
        # Callers must be able to catch this specifically, not a bare
        # `Exception`, and it follows the `LLMProviderError` pattern of
        # subclassing `RuntimeError` rather than a raw provider exception.
        assert issubclass(ScriptExhaustedError, RuntimeError)
        assert ScriptExhaustedError is not RuntimeError

    async def test_exhaustion_error_message_reports_script_length(self):
        fake = FakeLLMService(script=[_text_turn("only turn")])
        await fake.complete(messages=[], system="", tools=[], config=_config())

        with pytest.raises(ScriptExhaustedError, match="1"):
            await fake.complete(messages=[], system="", tools=[], config=_config())

    async def test_an_empty_script_raises_on_the_very_first_call(self):
        fake = FakeLLMService(script=[])

        with pytest.raises(ScriptExhaustedError):
            await fake.complete(messages=[], system="", tools=[], config=_config())

    async def test_repeated_calls_past_exhaustion_keep_raising(self):
        fake = FakeLLMService(script=[_text_turn("only turn")])
        await fake.complete(messages=[], system="", tools=[], config=_config())

        with pytest.raises(ScriptExhaustedError):
            await fake.complete(messages=[], system="", tools=[], config=_config())
        with pytest.raises(ScriptExhaustedError):
            await fake.complete(messages=[], system="", tools=[], config=_config())


# ---------------------------------------------------------------------------
# Call recording: messages, system, tools are inspectable after the call
# ---------------------------------------------------------------------------


class TestCallRecording:
    async def test_records_messages_system_and_tools_for_a_single_call(self):
        fake = FakeLLMService(script=[_text_turn("ok")])
        messages = [{"role": "user", "content": "Update the price for SKU-42."}]
        tools = [{"name": "get_inventory", "description": "look up stock", "parameters": {}}]

        await fake.complete(
            messages=messages,
            system="You are Juli's optimize-product agent.",
            tools=tools,
            config=_config(model="gpt-5.4-mini"),
        )

        assert len(fake.recorded_calls) == 1
        recorded = fake.recorded_calls[0]
        assert recorded.messages == tuple(messages)
        assert recorded.system == "You are Juli's optimize-product agent."
        assert recorded.tools == tuple(tools)
        assert recorded.config == _config(model="gpt-5.4-mini")

    async def test_records_calls_in_order_across_multiple_calls(self):
        fake = FakeLLMService(script=[_text_turn("a"), _text_turn("b")])

        await fake.complete(
            messages=[{"role": "user", "content": "one"}],
            system="s1",
            tools=[],
            config=_config(),
        )
        await fake.complete(
            messages=[{"role": "user", "content": "two"}],
            system="s2",
            tools=[],
            config=_config(),
        )

        assert len(fake.recorded_calls) == 2
        assert fake.recorded_calls[0].system == "s1"
        assert fake.recorded_calls[1].system == "s2"

    async def test_records_the_call_that_triggers_exhaustion_too(self):
        # A caller writing a WorkflowRunner test should be able to inspect
        # exactly what was sent on the call that blew past the script.
        fake = FakeLLMService(script=[])

        with pytest.raises(ScriptExhaustedError):
            await fake.complete(
                messages=[{"role": "user", "content": "one too many"}],
                system="s",
                tools=[],
                config=_config(),
            )

        assert len(fake.recorded_calls) == 1
        assert fake.recorded_calls[0].system == "s"

    async def test_recorded_calls_returns_an_immutable_snapshot(self):
        fake = FakeLLMService(script=[_text_turn("a")])
        await fake.complete(messages=[], system="", tools=[], config=_config())

        recorded = fake.recorded_calls
        assert isinstance(recorded, tuple)

    async def test_recorded_call_is_a_frozen_dataclass(self):
        fake = FakeLLMService(script=[_text_turn("a")])
        await fake.complete(messages=[], system="", tools=[], config=_config())

        recorded_call = fake.recorded_calls[0]
        assert dataclasses.is_dataclass(recorded_call)
        with pytest.raises(dataclasses.FrozenInstanceError):
            recorded_call.system = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Zero provider dependency
# ---------------------------------------------------------------------------


class TestNoProviderDependency:
    def test_fake_module_imports_no_provider_or_network_library(self):
        import ast
        from pathlib import Path

        module_path = (
            Path(__file__).resolve().parents[2]
            / "backend/src/juli_backend/services/agent/llm/fake.py"
        )
        tree = ast.parse(module_path.read_text())
        forbidden = (
            "openai",
            "anthropic",
            "litellm",
            "ollama",
            "langchain",
            "httpx",
            "requests",
        )

        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])

        assert not (imported_roots & set(forbidden)), imported_roots
