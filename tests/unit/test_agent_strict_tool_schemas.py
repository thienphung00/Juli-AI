"""Strict tool schemas (fast track P76-1, D78).

Every tool Juli offers the model goes out as an OpenAI strict function
(``"strict": true``) whose ``parameters`` is `to_strict(input_schema)`. This module is
the gate D78.5 names: a tool schema `to_strict` cannot convert fails HERE, in CI --
the running adapter only logs it and sends that one tool non-strict.

It also pins the other half of the contract: under strict mode the model sends an
explicit ``null`` for every optional field it leaves out, and `ToolSpec.parse_input`
turns that ``null`` back into the field's default (``attach_staged_image`` stays
``False``, a SKU's ``currency`` stays ``"VND"``), proven through the real runner
driven by the scripted fake LLM.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from juli_backend.services.agent.composition import build_product_tool_registry
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import FinalResponse, ToolCallBlock
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.llm.openai_adapter import JsonSchemaFormat, _translate_tool
from juli_backend.services.agent.llm.strict_schema import (
    StrictSchemaError,
    strict_problems,
    to_strict,
)
from juli_backend.services.agent.playbooks import get_registered_playbooks
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools.product_write import (
    ProductSkuPrice,
    UpdateProductListingInput,
)
from juli_backend.services.agent.tools.registry import null_as_default
from juli_backend.services.content_analysis.openai_media import VISION_SCHEMA
from juli_backend.services.content_analysis.scoring import SCORING_SCHEMA
from juli_backend.services.content_cards.schemas import LIVE_PLAN_SCHEMA, VIDEO_SCRIPT_SCHEMA
from juli_backend.services.lever_flows import PHOTO_PLAYBOOK, PROMOTION_PLAYBOOK
from juli_backend.services.run_changes import REVERT_LISTING_PLAYBOOK
from tests.unit.test_agent_runner_pause_resume import (
    _pause_resume_playbook,
    _seed_workflow_run,
    _SpyToolExecutor,
    _SteppingClock,
    _turn,
)

_REGISTRY = build_product_tool_registry()


def _every_playbook() -> list[Playbook]:
    return [
        *get_registered_playbooks().values(),
        PHOTO_PLAYBOOK,
        PROMOTION_PLAYBOOK,
        REVERT_LISTING_PLAYBOOK,
    ]


def _offered_tool_names(playbook: Playbook) -> list[str]:
    """What `WorkflowRunner._tool_definitions` offers: step tools, then terminal tools."""
    names = [tool for step in playbook.steps for tool in step.tools]
    names += list(playbook.termination_policy.terminal_tools)
    return list(dict.fromkeys(names))


def _wire(tool_name: str) -> dict[str, Any]:
    spec = _REGISTRY.get(tool_name)
    return _translate_tool(
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.render_input_schema(),
        }
    )


# --- the registry gate (D78.5) ------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(spec.name for spec in _REGISTRY.list_all()))
def test_every_registered_tool_converts_and_conforms(tool_name: str) -> None:
    schema = _REGISTRY.get(tool_name).render_input_schema()
    strict = to_strict(schema)  # raises StrictSchemaError: that is the CI failure
    assert strict_problems(strict) == []
    assert to_strict(strict) == strict, "to_strict must be idempotent"
    wire = _wire(tool_name)
    assert wire["strict"] is True
    assert wire["parameters"] == strict


@pytest.mark.parametrize(
    "playbook", _every_playbook(), ids=lambda playbook: f"{playbook.workflow_key}"
)
def test_every_playbook_offers_only_strict_tools(playbook: Playbook) -> None:
    names = _offered_tool_names(playbook)
    assert names, f"{playbook.workflow_key} offers no tools"
    for name in names:
        wire = _wire(name)
        assert wire["strict"] is True, name
        assert strict_problems(wire["parameters"]) == [], name


def test_update_product_listing_wire_body_golden() -> None:
    """The exact function entry OpenAI receives for the listing write (edits: below)."""
    wire = _wire("update_product_listing")
    edits = wire["parameters"]["properties"].pop("edits")
    assert wire["parameters"]["required"].pop() == "edits"
    assert wire == {
        "type": "function",
        "name": "update_product_listing",
        "description": _REGISTRY.get("update_product_listing").description,
        "parameters": {
            "description": (
                "New title and/or description to apply to the listing of the product\n"
                "already selected for this run, and whether to attach the image already\n"
                "uploaded for this run."
            ),
            "properties": {
                "title": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "attach_staged_image": {
                    "type": ["boolean", "null"],
                    "description": "null means the default, false.",
                },
            },
            "type": "object",
            "required": ["title", "description", "attach_staged_image"],
            "additionalProperties": False,
        },
        "strict": True,
    }
    assert edits["anyOf"][-1] == {"type": "null"}
    assert "edits to the current listing" in edits["description"].lower()


def test_listing_edit_ops_convert_to_a_closed_any_of_union() -> None:
    """P76-6: the discriminated `description_ops` union goes out as `anyOf` of closed
    objects, each pinned by its `op` const; the Pydantic `discriminator` is dropped."""
    edits = _wire("update_product_listing")["parameters"]["properties"]["edits"]["anyOf"][0]
    assert edits["required"] == ["title_ops", "description_ops"]
    title_op = edits["properties"]["title_ops"]["items"]
    assert title_op["properties"]["op"] == {"const": "replace_title_span", "type": "string"}
    branches = edits["properties"]["description_ops"]["items"]["anyOf"]
    assert [b["properties"]["op"]["const"] for b in branches] == [
        "replace_span",
        "insert_after",
        "append_section",
    ]
    for branch in branches:
        assert branch["additionalProperties"] is False
        assert branch["required"] == list(branch["properties"])
        assert "reason_code" in branch["required"]
    assert "discriminator" not in json.dumps(edits) and "oneOf" not in json.dumps(edits)


def test_a_strict_edits_call_parses_into_listing_edit_ops() -> None:
    params = _REGISTRY.get("update_product_listing").parse_input(
        {
            "title": None,
            "description": None,
            "attach_staged_image": None,
            "edits": {
                "title_ops": [
                    {"op": "replace_title_span", "old": "a", "new": "b", "reason_code": "TITLE_X"}
                ],
                "description_ops": [
                    {"op": "insert_after", "section_index": 0, "text": "t", "reason_code": "DESC_X"}
                ],
            },
        }
    )
    assert params.edits is not None
    assert params.edits.description_ops[0].op == "insert_after"
    assert params.attach_staged_image is False


def test_discriminator_without_one_of_is_refused() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "object", "discriminator": {"propertyName": "op"}}},
    }
    with pytest.raises(StrictSchemaError, match="discriminator") as raised:
        to_strict(schema)
    assert "$.a" in str(raised.value)


def test_nested_model_is_inlined_and_closed() -> None:
    """`update_product_price` renders its SKU model as a $ref; the wire inlines it."""
    parameters = _wire("update_product_price")["parameters"]
    assert "$defs" not in parameters
    sku = parameters["properties"]["skus"]["items"]
    assert sku["additionalProperties"] is False
    assert sku["required"] == ["sku_ref", "amount", "currency"]
    assert sku["properties"]["currency"]["type"] == ["string", "null"]
    assert parameters["properties"]["skus"]["minItems"] == 1


def test_length_bounds_move_to_the_description_and_stay_enforced() -> None:
    parameters = _wire("create_product")["parameters"]
    title = parameters["properties"]["title"]
    assert "minLength" not in title and "maxLength" not in title
    assert title["description"] == "Must be 10-255 characters long."
    with pytest.raises(ValidationError):
        _REGISTRY.get("create_product").parse_input(
            {"category_id": "1", "title": "short", "description": "x" * 30, "reason_vi": "r"}
        )


# --- output formats (JsonSchemaFormat) ----------------------------------------


@pytest.mark.parametrize(
    "schema",
    [SCORING_SCHEMA, VISION_SCHEMA, VIDEO_SCRIPT_SCHEMA, LIVE_PLAN_SCHEMA],
    ids=["scoring", "vision", "video_script", "live_plan"],
)
def test_output_formats_already_conform_and_go_out_unchanged(schema: dict[str, Any]) -> None:
    assert strict_problems(schema) == []
    wire = JsonSchemaFormat(name="x", schema=schema).to_wire()["format"]
    assert wire["strict"] is True
    assert wire["schema"] == schema


def test_unconvertible_output_format_is_logged_and_sent_non_strict(
    caplog: pytest.LogCaptureFixture,
) -> None:
    schema = {"type": "object", "properties": {"m": {"type": "object", "additionalProperties": {}}}}
    with caplog.at_level(logging.ERROR):
        wire = JsonSchemaFormat(name="bad", schema=schema).to_wire()["format"]
    assert wire["strict"] is False
    assert wire["schema"] == schema
    assert any(r.message == "strict_schema_unconvertible" for r in caplog.records)


def test_unconvertible_tool_never_raises_in_the_adapter(caplog: pytest.LogCaptureFixture) -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "allOf": [{}, {}]}
    with caplog.at_level(logging.ERROR):
        wire = _translate_tool({"name": "odd", "description": "d", "input_schema": schema})
    assert wire["strict"] is False
    assert wire["parameters"] == schema
    assert any(r.message == "strict_schema_unconvertible" for r in caplog.records)


# --- to_strict rules ----------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"anyOf": [{"type": "object", "properties": {}}]}, "root"),
        ({"type": "object", "properties": {"a": {"type": "string", "not": {}}}}, "'not'"),
        (
            {"type": "object", "properties": {"a": {"type": "array", "uniqueItems": True}}},
            "uniqueItems",
        ),
        ({"type": "object", "properties": {"a": {"type": "string", "format": "uri"}}}, "uri"),
        ({"type": "object", "additionalProperties": {"type": "string"}}, "open object"),
        (
            {
                "type": "object",
                "properties": {"n": {"$ref": "#/$defs/Node"}},
                "$defs": {
                    "Node": {"type": "object", "properties": {"n": {"$ref": "#/$defs/Node"}}}
                },
            },
            "recursive",
        ),
        ({"type": "object", "properties": {"a": {"$ref": "#/$defs/Missing"}}}, "unresolved"),
        ({"type": "array", "items": {"type": "string"}}, "root must be an object"),
    ],
)
def test_unconvertible_constructs_raise(schema: dict[str, Any], message: str) -> None:
    with pytest.raises(StrictSchemaError, match=message):
        to_strict(schema)


def test_property_names_that_look_like_keywords_are_kept() -> None:
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}, "default": {"type": "string"}},
        "required": ["title"],
    }
    out = to_strict(schema)
    assert list(out["properties"]) == ["title", "default"]
    assert out["required"] == ["title", "default"]
    assert out["properties"]["default"] == {"type": ["string", "null"]}


def test_optional_enum_is_wrapped_in_any_of_with_null() -> None:
    class _In(BaseModel):
        kind: str = "video"

    schema = {
        "type": "object",
        "properties": {"kind": {"enum": ["video", "live"], "type": "string", "default": "video"}},
    }
    out = to_strict(schema)
    assert out["properties"]["kind"] == {
        "anyOf": [{"enum": ["video", "live"], "type": "string"}, {"type": "null"}],
        "description": 'null means the default, "video".',
    }
    assert null_as_default(_In, {"kind": None}) == {}


def test_to_strict_does_not_mutate_its_input() -> None:
    schema = _REGISTRY.get("update_product_price").render_input_schema()
    before = copy.deepcopy(schema)
    to_strict(schema)
    assert schema == before


# --- null means default (ToolSpec.parse_input) --------------------------------


def test_explicit_nulls_fall_back_to_field_defaults() -> None:
    params = _REGISTRY.get("update_product_listing").parse_input(
        {"title": None, "description": "Mô tả mới", "attach_staged_image": None}
    )
    assert params == UpdateProductListingInput(description="Mô tả mới")


def test_nested_null_falls_back_to_the_nested_default() -> None:
    params = _REGISTRY.get("update_product_price").parse_input(
        {"skus": [{"sku_ref": "S1", "amount": "199000", "currency": None}]}
    )
    assert params.skus == [ProductSkuPrice(sku_ref="S1", amount="199000", currency="VND")]


def test_null_for_a_required_field_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        _REGISTRY.get("update_product_price").parse_input({"skus": None})


# --- fake-LLM replay: strict-shaped arguments through the real runner ---------


async def test_strict_shaped_call_pauses_and_resumes_with_defaults(engine: AsyncEngine) -> None:
    """The confirm-pause golden path, with the arguments a strict model writes."""
    strict_args = {"title": "Tiêu đề mới", "description": None, "attach_staged_image": None}
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        run_id = await _seed_workflow_run(session)
        runner = WorkflowRunner(
            llm_service=FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1", tool_name="get_product_information", arguments={}
                        )
                    ),
                    _turn(
                        ToolCallBlock(
                            call_id="c2",
                            tool_name="update_product_listing",
                            arguments=strict_args,
                        )
                    ),
                ]
            ),
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=JsonbConversationStore(session),
            registry=_REGISTRY,
            playbook=_pause_resume_playbook(),
            clock=_SteppingClock(step=1.0),
        )
        paused = await runner.run(run_id, product_ref="prod-1")
        assert paused.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        await session.commit()

    async with factory() as session:
        spy = _SpyToolExecutor()
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=[_turn(FinalResponse(content="Xong."))]),
            tool_executor=spy,
            event_sink=InMemoryEventSink(),
            conversation_store=JsonbConversationStore(session),
            registry=_REGISTRY,
            playbook=_pause_resume_playbook(),
            clock=_SteppingClock(step=1.0),
        )
        result = await runner.resume(run_id, approved=True)

    assert result.status == WorkflowRunStatus.COMPLETED
    assert spy.calls == [
        ("update_product_listing", UpdateProductListingInput(title="Tiêu đề mới")),
    ]
