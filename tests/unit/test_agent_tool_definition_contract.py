"""The runner's tool definitions survive the adapter's translation.

`WorkflowRunner._tool_definitions` (`runner/core.py`) is the only producer
of `ToolDefinition`s; `_translate_tool` (`llm/openai_adapter.py`) is the
only consumer. They disagreed on the schema's key — producer `input_schema`,
consumer `parameters` — and the consumer's `or {"type": "object",
"properties": {}}` fallback turned the disagreement into silence. Every tool
reached the model declared as taking no arguments.

It survived every existing test because both halves were tested in
isolation: the adapter's unit tests hand-build definitions using the key the
adapter expects, and the runner's tests assert on the definitions it emits.
Neither ever passed one to the other. These tests do exactly that, with the
real registry and the real playbook, so the two halves can never drift apart
again unnoticed.
"""

from __future__ import annotations

import pytest

from juli_backend.services.agent.llm.openai_adapter import _translate_tool
from juli_backend.services.agent.playbooks.optimize_product import OPTIMIZE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.agent.tools.terminal import register_terminal_tools


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _real_tool_definitions():
    """The exact list `WorkflowRunner._tool_definitions` builds, produced the
    same way (playbook order, deduplicated, schema from the `ToolSpec`)."""
    registry = _registry()
    seen: set[str] = set()
    definitions = []
    for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
        for tool_name in step.tools:
            if tool_name in seen:
                continue
            seen.add(tool_name)
            spec = registry.get(tool_name)
            definitions.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.render_input_schema(),
                }
            )
    return definitions


def _translated_by_name() -> dict[str, dict]:
    return {tool["name"]: _translate_tool(tool) for tool in _real_tool_definitions()}


class TestEveryPlaybookToolReachesTheModelWithItsRealSchema:
    def test_the_playbook_produces_definitions_at_all(self):
        assert _real_tool_definitions(), "no tools rendered from the Optimize Product playbook"

    @pytest.mark.parametrize("tool_name", [t["name"] for t in _real_tool_definitions()])
    def test_translated_parameters_match_the_tool_spec_schema(self, tool_name):
        expected = _registry().get(tool_name).render_input_schema()
        assert _translated_by_name()[tool_name]["parameters"] == expected

    def test_a_tool_with_required_arguments_does_not_arrive_argument_less(self):
        """The live symptom, pinned directly: `update_product_price` requires
        a non-empty `skus` list, and the model was told it took nothing, so
        it called it with `{}` on every attempt."""
        parameters = _translated_by_name()["update_product_price"]["parameters"]
        assert parameters.get("required"), "update_product_price declares no required arguments"
        assert "skus" in parameters["required"]
        assert parameters["properties"], "empty properties -- the model cannot pass anything"

    def test_no_playbook_tool_translates_to_an_empty_property_set(self):
        for name, translated in _translated_by_name().items():
            assert translated["parameters"].get("type") == "object", name
            assert "properties" in translated["parameters"], name


class TestTheEmptySchemaFallbackIsGone:
    def test_a_definition_with_no_input_schema_raises(self):
        with pytest.raises(ValueError, match="no 'input_schema'"):
            _translate_tool({"name": "x", "description": "y"})

    def test_the_old_parameters_key_is_no_longer_silently_accepted(self):
        """A caller still writing the adapter's old key gets an error, not a
        tool the model believes takes no arguments."""
        with pytest.raises(ValueError, match="no 'input_schema'"):
            _translate_tool({"name": "x", "description": "y", "parameters": {"type": "object"}})
