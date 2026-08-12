"""Agent tool registry core contract tests — issue #980 (W1-A, ADR-069 decision 3).

`ToolSpec` carries the seven attributes an agent capability definition needs
(name, model-facing description, declared input/output shape, read|write
classification, auto|confirm policy, timeout), and `ToolRegistry` holds them
under explicit registration with lookup-by-name and enumerate-all. The
model-facing JSON schema shown to the LLM is derived from the declared input
shape via `model_json_schema()` — never hand-written — so it cannot drift
from what the platform validates.

No marketplace I/O and no real capabilities exist in this slice: everything
below is proven against a `get_widget_status` definition declared in this
test file only.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from juli_backend.services.agent.tools.registry import (
    DuplicateToolError,
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_MODULE = REPO_ROOT / "backend/src/juli_backend/services/agent/tools/registry.py"


# --- Fixture capability definition (test-only; no real capability in this slice) ---


class GetWidgetStatusInput(BaseModel):
    widget_id: str


class GetWidgetStatusOutput(BaseModel):
    widget_id: str
    status: str


def make_get_widget_status_spec() -> ToolSpec:
    return ToolSpec(
        name="get_widget_status",
        description="Look up the current status of a widget.",
        input_model=GetWidgetStatusInput,
        output_model=GetWidgetStatusOutput,
        classification=ToolClassification.READ,
        policy=ToolPolicy.AUTO,
        timeout_seconds=10,
    )


class TestToolSpecAttributes:
    """A capability definition carries all seven ADR-069 decision-3 attributes."""

    def test_tool_spec_carries_all_seven_attributes(self):
        spec = make_get_widget_status_spec()

        assert spec.name == "get_widget_status"
        assert spec.description == "Look up the current status of a widget."
        assert spec.input_model is GetWidgetStatusInput
        assert spec.output_model is GetWidgetStatusOutput
        assert spec.classification is ToolClassification.READ
        assert spec.policy is ToolPolicy.AUTO
        assert spec.timeout_seconds == 10

    def test_classification_rejects_free_string(self):
        """classification is a constrained value, not a free string."""
        with pytest.raises(TypeError):
            ToolSpec(
                name="get_widget_status",
                description="Look up the current status of a widget.",
                input_model=GetWidgetStatusInput,
                output_model=GetWidgetStatusOutput,
                classification="read",  # type: ignore[arg-type]
                policy=ToolPolicy.AUTO,
                timeout_seconds=10,
            )

    def test_policy_rejects_free_string(self):
        """policy is a constrained value, not a free string."""
        with pytest.raises(TypeError):
            ToolSpec(
                name="get_widget_status",
                description="Look up the current status of a widget.",
                input_model=GetWidgetStatusInput,
                output_model=GetWidgetStatusOutput,
                classification=ToolClassification.READ,
                policy="auto",  # type: ignore[arg-type]
                timeout_seconds=10,
            )

    def test_classification_and_policy_are_enum_members(self):
        assert set(ToolClassification) == {
            ToolClassification.READ,
            ToolClassification.WRITE,
        }
        assert set(ToolPolicy) == {ToolPolicy.AUTO, ToolPolicy.CONFIRM}


class TestExplicitRegistration:
    """Registration is explicit; a duplicate name raises."""

    def test_register_adds_the_spec(self):
        registry = ToolRegistry()
        spec = make_get_widget_status_spec()

        registry.register(spec)

        assert registry.get("get_widget_status") is spec

    def test_registering_duplicate_name_raises(self):
        registry = ToolRegistry()
        registry.register(make_get_widget_status_spec())

        with pytest.raises(DuplicateToolError):
            registry.register(make_get_widget_status_spec())


class TestLookup:
    """Looking up an unknown name raises an error naming the unknown capability."""

    def test_lookup_known_tool_returns_its_spec(self):
        registry = ToolRegistry()
        spec = make_get_widget_status_spec()
        registry.register(spec)

        assert registry.get("get_widget_status") is spec

    def test_lookup_unknown_tool_raises_naming_it(self):
        registry = ToolRegistry()

        with pytest.raises(UnknownToolError) as exc_info:
            registry.get("nonexistent_tool")

        assert "nonexistent_tool" in str(exc_info.value)


class TestEnumeration:
    """All registered capabilities can be enumerated."""

    def test_list_all_returns_every_registered_spec(self):
        registry = ToolRegistry()
        widget_spec = make_get_widget_status_spec()

        class GetOtherThingInput(BaseModel):
            thing_id: str

        class GetOtherThingOutput(BaseModel):
            thing_id: str
            name: str

        other_spec = ToolSpec(
            name="get_other_thing",
            description="Look up another thing.",
            input_model=GetOtherThingInput,
            output_model=GetOtherThingOutput,
            classification=ToolClassification.READ,
            policy=ToolPolicy.AUTO,
            timeout_seconds=5,
        )

        registry.register(widget_spec)
        registry.register(other_spec)

        names = {spec.name for spec in registry.list_all()}
        assert names == {"get_widget_status", "get_other_thing"}

    def test_list_all_empty_registry_returns_empty_list(self):
        registry = ToolRegistry()
        assert registry.list_all() == []


class TestRenderedSchemaIsDerivedFromInputModel:
    """The rendered schema is derived from the declared input shape."""

    def test_rendered_schema_reflects_the_input_model_fields(self):
        spec = make_get_widget_status_spec()

        schema = spec.render_input_schema()

        assert schema == GetWidgetStatusInput.model_json_schema()
        assert "widget_id" in schema["properties"]

    def test_changing_the_declared_shape_changes_the_rendered_schema(self):
        """Changing input_model changes the rendered schema — asserted directly."""

        class GetWidgetStatusInputV2(BaseModel):
            widget_id: str
            include_history: bool = False

        narrow_spec = ToolSpec(
            name="get_widget_status_v1",
            description="Look up the current status of a widget.",
            input_model=GetWidgetStatusInput,
            output_model=GetWidgetStatusOutput,
            classification=ToolClassification.READ,
            policy=ToolPolicy.AUTO,
            timeout_seconds=10,
        )
        widened_spec = ToolSpec(
            name="get_widget_status_v2",
            description="Look up the current status of a widget, optionally with history.",
            input_model=GetWidgetStatusInputV2,
            output_model=GetWidgetStatusOutput,
            classification=ToolClassification.READ,
            policy=ToolPolicy.AUTO,
            timeout_seconds=10,
        )

        narrow_schema = narrow_spec.render_input_schema()
        widened_schema = widened_spec.render_input_schema()

        assert narrow_schema != widened_schema
        assert "include_history" not in narrow_schema["properties"]
        assert "include_history" in widened_schema["properties"]

    def test_rendering_never_hand_written_matches_model_json_schema_exactly(self):
        """The schema must be exactly what `model_json_schema()` produces — no
        hand-authored transformation layer that could drift from validation."""
        spec = make_get_widget_status_spec()
        assert spec.render_input_schema() == spec.input_model.model_json_schema()


class TestRenderedSchemaIsModelConsumable:
    """Rendering produces valid model-consumable JSON schema.

    Structural assertions on our own contract only — not a re-validation of
    Pydantic's `model_json_schema()` output against a third-party JSON Schema
    meta-schema validator, which would test Pydantic rather than this
    registry, and would pull in a dependency the backend install does not
    declare (`backend/pyproject.toml`, `backend/constraints.txt`).
    """

    def test_rendered_schema_has_object_type_and_properties_mapping(self):
        spec = make_get_widget_status_spec()
        schema = spec.render_input_schema()

        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)

    def test_declared_fields_appear_with_expected_json_types(self):
        spec = make_get_widget_status_spec()
        schema = spec.render_input_schema()

        assert schema["properties"]["widget_id"]["type"] == "string"

    def test_required_fields_appear_and_optional_fields_do_not(self):
        class OptionalFieldInput(BaseModel):
            widget_id: str
            include_history: bool = False

        spec = ToolSpec(
            name="get_widget_status_optional",
            description="Look up widget status, optionally including history.",
            input_model=OptionalFieldInput,
            output_model=GetWidgetStatusOutput,
            classification=ToolClassification.READ,
            policy=ToolPolicy.AUTO,
            timeout_seconds=10,
        )
        schema = spec.render_input_schema()

        assert schema["required"] == ["widget_id"]
        assert "include_history" not in schema["required"]

    def test_rendered_schema_round_trips_through_json_dumps(self):
        """ "Model-consumable" here means JSON-serialisable — proven by an actual round trip."""
        spec = make_get_widget_status_spec()
        schema = spec.render_input_schema()

        deserialized = json.loads(json.dumps(schema))

        assert deserialized == schema


class TestNoMarketplaceImports:
    """No import of any marketplace client or resource in this module."""

    def test_registry_module_imports_no_marketplace_or_tiktok_symbols(self):
        tree = ast.parse(REGISTRY_MODULE.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_substrings = ("tiktok", "marketplace", "integrations")
        offending = {
            module
            for module in imported_modules
            if any(bad in module.lower() for bad in forbidden_substrings)
        }
        assert not offending, f"registry.py must not import marketplace/vendor modules: {offending}"
