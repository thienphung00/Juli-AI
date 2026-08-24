"""Adversarial fixture suite (ADR-070/075 decision 5, issue #1218).

**Fixture-directory discovery.** Every `tests/fixtures/agent_sanitize_hidden_text/*.json`
file is one recorded injection attempt, or one proof that legitimate content
survives untouched. This module discovers files by glob and parametrizes
generically over their declared shape — adding a fixture means adding one
JSON file to that directory, never touching this file. No fixture-directory
discovery pattern existed in this package before this issue (every prior
golden case hardcoded one `Path`, per `test_agent_sanitize_golden.py`); this
module introduces it.

**Two assertion levels per fixture** (issue #1218 acceptance criteria):

1. **The sanitizer neutralizes it** (`test_sanitizer_neutralizes_the_fixture`)
   -- `guard_inbound_tool_result` is run against a tool-result-shaped
   payload carrying the fixture's `raw_text` in the field its `source_field`
   names. A fixture whose `expected_guard_outcome` is `"blocked"` must come
   back as the `{"error": ...}` envelope -- the pre-existing fail-closed
   banned-pattern gate (ADR-070 decision 6) catching it, e.g. the
   `tool_shaped_json` fixture's literal `tool_name` key. A `"passthrough"`
   fixture must come back with its field's `text` equal to
   `expected_stripped_text`: unchanged for content-shaped attacks
   (instruction-bearing prose, a seller capability-unlock note) that are
   defanged structurally (provenance tagging, never executed as
   instruction) rather than by deletion, and character-stripped for the
   three hidden-text categories (control characters, zero-width/invisible
   Unicode, bidi overrides) plus untouched for the two legitimate-content
   fixtures (Vietnamese diacritics, emoji).
2. **The scripted loop is behaviour-invariant**
   (`test_scripted_loop_is_behaviour_invariant_with_and_without_the_payload`)
   -- a real `WorkflowRunner` scripted (via `FakeLLMService`) to call one
   tool then finish is driven twice: once with the fixture's `raw_text` as
   the tool's returned field, once with a fixed neutral baseline in its
   place. Both runs must dispatch the identical sequence of tool calls and
   reach the identical `stop_reason` -- proving the payload's mere presence
   has no power over the loop's control flow, only over what data flows
   through it, which is exactly the "structural" claim ADR-070 decision 3
   makes about vendor/seller text.

Unit tier: no network, no provider key -- `FakeLLMService` plays back a
fixed script, `_RecordingToolExecutor` below returns a fixed dict, and
`_InMemoryConversationStore` is a plain in-process double.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from juli_backend.services.agent.events import EventSink, InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.sanitize import guard_inbound_tool_result
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "agent_sanitize_hidden_text"
FIXTURE_PATHS = sorted(FIXTURES_DIR.glob("*.json"))

_TOOL_NAME = "get_product_information"
_BASELINE_TEXT = "Baseline vendor description with no adversarial payload present."


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_result_for(fixture: dict[str, Any], *, text: str) -> dict[str, Any]:
    return {"description": {"source": fixture["source_field"], "text": text}}


def test_fixture_directory_is_not_empty() -> None:
    """Canary against a typo'd glob silently discovering zero fixtures --
    a parametrized suite with 0 cases passes vacuously."""
    assert len(FIXTURE_PATHS) >= 8


# ---------------------------------------------------------------------------
# Level 1: the sanitizer neutralizes it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=lambda p: p.stem)
def test_sanitizer_neutralizes_the_fixture(path: Path) -> None:
    fixture = _load_fixture(path)
    tool_result = _tool_result_for(fixture, text=fixture["raw_text"])

    guarded = guard_inbound_tool_result(tool_result, tool_name=_TOOL_NAME)

    if fixture["expected_guard_outcome"] == "blocked":
        assert set(guarded) == {"error"}
    else:
        assert "error" not in guarded
        assert guarded["description"]["text"] == fixture["expected_stripped_text"]


# ---------------------------------------------------------------------------
# Level 2: the scripted loop is behaviour-invariant, with vs. without.
# ---------------------------------------------------------------------------


class _InMemoryConversationStore:
    """Minimal `ConversationStore` double -- no database. Mirrors the shape
    `test_agent_runner_core.py`'s own local double uses (each agent test
    module keeps its own, per this repo's convention)."""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, RunState] = {}

    def seed(self, workflow_run_id: uuid.UUID) -> None:
        self._store[workflow_run_id] = RunState()

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        return self._store[workflow_run_id]

    async def persist(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        *,
        status: WorkflowRunStatus | None = None,
        stop_reason: StopReason | None = None,
        required_steps_completed: bool | None = None,
        running_seconds_elapsed: int | None = None,
    ) -> None:
        self._store[workflow_run_id] = state


class _RecordingToolExecutor:
    """Returns a fixed tool result carrying ``text`` in its provenance
    field. Content is the only thing that varies between a fixture's two
    runs; dispatch itself (tool name, params) is otherwise identical."""

    def __init__(self, *, source_field: str, text: str) -> None:
        self._source_field = source_field
        self._text = text
        self.calls: list[str] = []

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(tool_name)
        return {"description": {"source": self._source_field, "text": self._text}}


def _minimal_playbook() -> Playbook:
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=(
            PlaybookStep(
                step_id=_TOOL_NAME,
                intent="Call get_product_information.",
                tools=(_TOOL_NAME,),
                policy=ToolPolicy.AUTO,
            ),
        ),
        termination_policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    )


async def _run_scripted_loop(*, source_field: str, text: str) -> tuple[list[str], StopReason]:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    sink: EventSink = InMemoryEventSink()
    registry = ToolRegistry()
    register_product_read_tools(registry)
    executor = _RecordingToolExecutor(source_field=source_field, text=text)

    runner = WorkflowRunner(
        llm_service=FakeLLMService(
            script=[
                AssistantTurn(
                    blocks=(ToolCallBlock(call_id="c1", tool_name=_TOOL_NAME, arguments={}),),
                    usage=Usage(input_tokens=1, output_tokens=1),
                ),
                AssistantTurn(
                    blocks=(FinalResponse(content="Done."),),
                    usage=Usage(input_tokens=1, output_tokens=1),
                ),
            ]
        ),
        tool_executor=executor,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=_minimal_playbook(),
    )

    result = await runner.run(run_id, product_ref="prod-1")
    return executor.calls, result.stop_reason


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=lambda p: p.stem)
async def test_scripted_loop_is_behaviour_invariant_with_and_without_the_payload(
    path: Path,
) -> None:
    fixture = _load_fixture(path)

    calls_with, stop_reason_with = await _run_scripted_loop(
        source_field=fixture["source_field"], text=fixture["raw_text"]
    )
    calls_without, stop_reason_without = await _run_scripted_loop(
        source_field=fixture["source_field"], text=_BASELINE_TEXT
    )

    assert calls_with == calls_without
    assert stop_reason_with == stop_reason_without
    # Sanity: the script really did dispatch the tool both times -- an
    # empty call list would make the equality assertion above vacuous.
    assert calls_with == [_TOOL_NAME]
