"""FakeLLMService x registry x sanitizer composition — issue #996 (W1 close), AC2.

The W1-close gate (implementation handoff §8): "fake LLMService consumed by at least
one downstream-shaped test — a scripted turn requesting a tool call, dispatched
against the real registry, with the result sanitized — proving the three interfaces
(I1, I2, I3) compose before the WorkflowRunner depends on all of them in W3-A."

- I1 — `FakeLLMService` (#987, ADR-071 decision 6), scripted to propose a tool call,
  exercised through the real `LLMService.complete` contract (`await`, keyword-only
  `messages`/`system`/`tools`/`config`).
- I2 — the real ADR-069 registry: `ToolRegistry` populated by
  `register_product_read_tools`, tool definitions rendered via
  `ToolSpec.render_input_schema()` (the same shape `test_agent_llm_recorded_replay.py`
  sends the real OpenAI adapter, reused here so both W1-B integration suites build
  tool definitions identically).
- I3 — the sanitize package (ADR-070), applied via
  `tests/integration/agent_tool_dispatch.dispatch_and_sanitize` at the same boundary
  a real dispatcher would use.

This is deliberately not a rehearsal of `WorkflowRunner` (W3-A, not built yet) — no
loop, no multi-turn continuation, no `stop_reason`. It proves the three shapes fit
together for one tool-call turn, which is the whole of what a W1-close checkpoint
owns.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from juli_backend.integrations.tiktok.factories import ProductionReadResources
from juli_backend.services.agent.llm import AssistantTurn, ToolCallBlock, Usage
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.tools.product import (
    PRODUCT_READ_TOOL_HANDLERS,
    ProductToolContext,
    register_product_read_tools,
)
from juli_backend.services.agent.tools.registry import ToolRegistry
from tests.integration.agent_tool_dispatch import dispatch_and_sanitize

BOUND_PRODUCT_ID = "1736405947247986307"
RAW_SKU_ID = "raw-sku-id-must-never-leak"


class _StubProductsResource:
    def get_details(self, product_id: str) -> dict:
        return {
            "id": BOUND_PRODUCT_ID,
            "title": "Hero Running Shoe",
            "status": "ACTIVATE",
            "update_time": 1_782_892_330,
            "skus": [
                {
                    "id": RAW_SKU_ID,
                    "inventory": [{"quantity": 43, "warehouse_id": "wh-1"}],
                    "price": {"currency": "VND", "tax_exclusive_price": "72000"},
                }
            ],
        }

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        return {}

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        return {}


def _registry_tool_definitions(registry: ToolRegistry) -> list[dict]:
    """The I2 shape a caller sends an `LLMService.complete` call — mirrors
    `test_agent_llm_recorded_replay.py::_registry_tool_definitions`."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.render_input_schema(),
        }
        for spec in sorted(registry.list_all(), key=lambda spec: spec.name)
    ]


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    return registry


@pytest.fixture
def resources() -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=_StubProductsResource(),  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


class TestFakeLlmRegistryAndSanitizerCompose:
    async def test_scripted_tool_call_dispatches_against_the_real_registry_and_sanitizes(
        self, registry, resources
    ):
        fake = FakeLLMService(
            script=[
                AssistantTurn(
                    blocks=(
                        ToolCallBlock(
                            call_id="call_1",
                            tool_name="get_product_information",
                            arguments={},
                        ),
                    ),
                    usage=Usage(input_tokens=12, output_tokens=6),
                ),
            ]
        )

        # I1: a real `LLMService.complete` call, scripted rather than networked.
        turn = await fake.complete(
            messages=[{"role": "user", "content": "Look up the product information."}],
            system="You are Juli. Tools take no identifier arguments; the product is bound.",
            tools=_registry_tool_definitions(registry),
            config=LLMConfig(),
        )

        tool_calls = [block for block in turn.blocks if isinstance(block, ToolCallBlock)]
        assert len(tool_calls) == 1
        proposed = tool_calls[0]
        assert proposed.tool_name == "get_product_information"

        # I2 + I3: dispatch the proposed call against the real registry/handler,
        # sanitize the result.
        context = ProductToolContext(product_id=BOUND_PRODUCT_ID)
        sanitized = dispatch_and_sanitize(
            registry=registry,
            handlers=PRODUCT_READ_TOOL_HANDLERS,
            tool_name=proposed.tool_name,
            resources=resources,
            context=context,
            arguments=proposed.arguments,
        )

        assert "error" not in sanitized
        assert sanitized["title"] == {"source": "vendor", "text": "Hero Running Shoe"}
        datetime.fromisoformat(sanitized["update_time"])
        assert sanitized["sku_prices"]["items"] == [{"amount": 72000, "currency": "VND"}]
        serialized = str(sanitized)
        assert BOUND_PRODUCT_ID not in serialized
        assert RAW_SKU_ID not in serialized

        # The fake recorded exactly the call it received — I1's own contract,
        # unaffected by what I2/I3 did with its output.
        assert len(fake.recorded_calls) == 1
        assert fake.recorded_calls[0].tools == tuple(_registry_tool_definitions(registry))

    async def test_the_fake_never_touches_the_registry_or_the_sanitizer(self, registry):
        """I1 stays a pure block-scripting double — dispatching and sanitizing
        the tool call it proposes is entirely the caller's job, never the
        fake's. Calling `complete` a second time past the one scripted turn
        proves the fake did nothing beyond returning that turn."""
        fake = FakeLLMService(
            script=[
                AssistantTurn(
                    blocks=(ToolCallBlock(call_id="c1", tool_name="get_product_information"),),
                    usage=Usage(input_tokens=1, output_tokens=1),
                ),
            ]
        )
        await fake.complete(
            messages=[], system="s", tools=_registry_tool_definitions(registry), config=LLMConfig()
        )

        from juli_backend.services.agent.llm.fake import ScriptExhaustedError

        with pytest.raises(ScriptExhaustedError):
            await fake.complete(
                messages=[],
                system="s",
                tools=_registry_tool_definitions(registry),
                config=LLMConfig(),
            )
