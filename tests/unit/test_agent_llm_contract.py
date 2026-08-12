"""Issue #985 — Juli-owned block vocabulary, LLMService protocol, fail-closed LLMConfig.

ADR-071 decisions 1 and 4. No provider code lands in this slice: the three block
types, the usage record, and the assistant turn are Juli-owned dataclasses; the
service is a `Protocol`; configuration resolves playbook override -> environment ->
defaults; `OPENAI_API_KEY` is required via `require_env` and fails closed.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
from typing import Protocol

import pytest

from juli_backend.services.agent.llm import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    AssistantTurn,
    FinalResponse,
    LLMConfig,
    LLMConfigOverride,
    LLMService,
    TextBlock,
    ToolCallBlock,
    Usage,
    resolve_llm_config,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LLM_MODULE_DIR = REPO_ROOT / "backend/src/juli_backend/services/agent/llm"

FORBIDDEN_PROVIDER_IMPORT_PREFIXES = (
    "openai",
    "anthropic",
    "litellm",
    "ollama",
    "langchain",
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
    """Isolate every test from the ambient shell/.env — no real key, no leaks."""
    for name in _LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def _with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A patched (never real) key, matching the require_env pattern used elsewhere."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-patched-not-real")


# ---------------------------------------------------------------------------
# Blocks, usage, assistant turn: Juli-owned, no provider dependency
# ---------------------------------------------------------------------------


class TestBlockVocabulary:
    def test_text_block_is_frozen_dataclass(self):
        block = TextBlock(text="hello seller")
        assert dataclasses.is_dataclass(block)
        assert block.text == "hello seller"
        with pytest.raises(dataclasses.FrozenInstanceError):
            block.text = "mutated"  # type: ignore[misc]

    def test_tool_call_block_carries_call_id_name_and_arguments(self):
        block = ToolCallBlock(
            call_id="call_1",
            tool_name="get_product",
            arguments={"product_id": "abc"},
        )
        assert dataclasses.is_dataclass(block)
        assert block.call_id == "call_1"
        assert block.tool_name == "get_product"
        assert block.arguments == {"product_id": "abc"}

    def test_tool_call_block_arguments_default_to_empty_dict(self):
        block = ToolCallBlock(call_id="call_2", tool_name="noop")
        assert block.arguments == {}

    def test_final_response_is_frozen_dataclass(self):
        block = FinalResponse(content="done")
        assert dataclasses.is_dataclass(block)
        assert block.content == "done"
        assert block.structured_output is None

    def test_usage_carries_input_and_output_token_counts(self):
        usage = Usage(input_tokens=120, output_tokens=45)
        assert usage.input_tokens == 120
        assert usage.output_tokens == 45
        with pytest.raises(dataclasses.FrozenInstanceError):
            usage.input_tokens = 0  # type: ignore[misc]

    def test_assistant_turn_carries_blocks_and_usage(self):
        turn = AssistantTurn(
            blocks=(
                TextBlock(text="checking inventory"),
                ToolCallBlock(call_id="call_1", tool_name="get_inventory"),
                FinalResponse(content="Stock looks healthy."),
            ),
            usage=Usage(input_tokens=10, output_tokens=5),
        )
        assert len(turn.blocks) == 3
        assert isinstance(turn.blocks[0], TextBlock)
        assert isinstance(turn.blocks[1], ToolCallBlock)
        assert isinstance(turn.blocks[2], FinalResponse)
        assert turn.usage.input_tokens == 10
        assert turn.usage.output_tokens == 5

    def test_assistant_turn_is_frozen_dataclass(self):
        turn = AssistantTurn(blocks=(), usage=Usage(input_tokens=0, output_tokens=0))
        with pytest.raises(dataclasses.FrozenInstanceError):
            turn.usage = Usage(input_tokens=1, output_tokens=1)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LLMService: expressed as a protocol, not a concrete adapter
# ---------------------------------------------------------------------------


class TestLLMServiceIsAProtocol:
    def test_llm_service_is_a_typing_protocol(self):
        assert Protocol in LLMService.__mro__
        assert getattr(LLMService, "_is_protocol", False) is True

    def test_llm_service_declares_complete_with_expected_signature(self):
        signature = inspect.signature(LLMService.complete)
        params = list(signature.parameters)
        assert params == ["self", "messages", "system", "tools", "config"]

    def test_a_conforming_fake_satisfies_the_protocol_at_runtime(self):
        class FakeLLMService:
            async def complete(self, *, messages, system, tools, config) -> AssistantTurn:
                return AssistantTurn(blocks=(), usage=Usage(input_tokens=0, output_tokens=0))

        assert isinstance(FakeLLMService(), LLMService)

    def test_a_non_conforming_object_does_not_satisfy_the_protocol(self):
        class NotAnLlmService:
            pass

        assert not isinstance(NotAnLlmService(), LLMService)


# ---------------------------------------------------------------------------
# LLMConfig: playbook override -> environment -> defaults, fail-closed key
# ---------------------------------------------------------------------------


class TestLLMConfigResolution:
    def test_default_model_is_gpt_5_4_nano(self, _with_api_key):
        assert DEFAULT_MODEL == "gpt-5.4-nano"
        config = resolve_llm_config()
        assert config.model == "gpt-5.4-nano"

    def test_resolves_to_defaults_when_no_override_or_env(self, _with_api_key):
        config = resolve_llm_config()
        assert config == LLMConfig(
            model=DEFAULT_MODEL,
            max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            temperature=DEFAULT_TEMPERATURE,
            request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )

    def test_environment_value_beats_default(self, monkeypatch: pytest.MonkeyPatch, _with_api_key):
        monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")
        monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2048")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.9")
        monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "60")

        config = resolve_llm_config()

        assert config.model == "gpt-5.4-mini"
        assert config.max_output_tokens == 2048
        assert config.temperature == pytest.approx(0.9)
        assert config.request_timeout_seconds == pytest.approx(60.0)

    def test_playbook_override_beats_environment(
        self, monkeypatch: pytest.MonkeyPatch, _with_api_key
    ):
        monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")
        monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "2048")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.9")
        monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "60")

        override = LLMConfigOverride(
            model="gpt-5.4-nano-playbook",
            max_output_tokens=512,
            temperature=0.1,
            request_timeout_seconds=15,
        )
        config = resolve_llm_config(override)

        assert config.model == "gpt-5.4-nano-playbook"
        assert config.max_output_tokens == 512
        assert config.temperature == pytest.approx(0.1)
        assert config.request_timeout_seconds == pytest.approx(15.0)

    def test_playbook_override_beats_default_when_env_absent(self, _with_api_key):
        override = LLMConfigOverride(model="gpt-5.4-nano-playbook")
        config = resolve_llm_config(override)
        assert config.model == "gpt-5.4-nano-playbook"
        # Unset override fields still fall through to defaults.
        assert config.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS

    def test_partial_override_only_replaces_its_own_field(
        self, monkeypatch: pytest.MonkeyPatch, _with_api_key
    ):
        monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")
        override = LLMConfigOverride(temperature=0.3)

        config = resolve_llm_config(override)

        assert config.model == "gpt-5.4-mini"  # env still wins; override left this field unset
        assert config.temperature == pytest.approx(0.3)

    def test_missing_api_key_raises_with_patched_environment(self):
        """AC: absent OPENAI_API_KEY raises, asserted with a patched (never real) env."""
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            resolve_llm_config()

    def test_blank_api_key_raises_same_as_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENAI_API_KEY", "   ")
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            resolve_llm_config()


# ---------------------------------------------------------------------------
# No provider code in this slice
# ---------------------------------------------------------------------------


class TestNoProviderCodeInThisSlice:
    """AC: nothing in this slice imports the provider SDK.

    An AST import check, not a source-text substring check: this module
    legitimately *names* the provider in documentation (the `OPENAI_API_KEY`
    env var, prose describing the future OpenAI adapter this package leaves
    room for) without ever importing it — exactly the seam ADR-071 decision 1
    asks for.
    """

    def test_no_module_in_the_llm_package_imports_a_provider_sdk(self):
        python_files = sorted(LLM_MODULE_DIR.glob("*.py"))
        assert python_files, "expected LLM module files to exist"

        for path in python_files:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                for name in names:
                    if not name:
                        continue
                    top_level = name.split(".")[0].lower()
                    assert top_level not in FORBIDDEN_PROVIDER_IMPORT_PREFIXES, (
                        f"{path.relative_to(REPO_ROOT)} imports provider SDK {name!r}"
                    )
