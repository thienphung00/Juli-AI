"""Dual-language contract test: the eight-event `WorkflowRunEvent` Pydantic
union (#1125, ADR-074 decision 2) and its TypeScript mirror
(`packages/contracts/src/agent-events.ts`, #1126 / AGT-W3B) can never
silently disagree.

Same mechanism as `tests/unit/test_agent_banned_patterns_contract.py`: a
Python test that shells out to `node -e "..."` to run the *actual* TS source
(transpiled fresh, in-process, via the `typescript` package already a
`packages/contracts` devDependency -- no new dependency is added) against the
same golden fixture files both languages consume, and asserts the parsed
shapes agree byte-for-byte, per event type.

The golden fixtures (one per event type, plus an envelope `v: 1` snapshot)
live in `packages/contracts/fixtures/agent-events/`. Two additional
`invalid/` fixtures deliberately exploit a real per-language leniency
difference (Pydantic's lax int coercion vs. this hand-rolled TS validator's
strict `typeof` checks, and Pydantic's strict `datetime` parsing vs. the TS
validator's bare `typeof "string"` check) to prove that if a real divergence
ever entered the picture, this test would catch it and *name* which of the
eight event types drifted -- not just fail vaguely.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from juli_backend.services.agent.events import (
    EVENT_TYPES,
    AssistantTextPayload,
    ToolCompletedPayload,
    ToolStartedPayload,
    WorkflowApprovalRequiredPayload,
    WorkflowCompletedPayload,
    WorkflowFailedPayload,
    WorkflowRunEventAdapter,
    WorkflowStartedPayload,
    WorkflowStatusPayload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "packages" / "contracts"
AGENT_EVENTS_TS_PATH = CONTRACTS_DIR / "src" / "agent-events.ts"
FIXTURES_DIR = CONTRACTS_DIR / "fixtures" / "agent-events"
INVALID_FIXTURES_DIR = FIXTURES_DIR / "invalid"

GOLDEN_FIXTURES: dict[str, Path] = {
    "workflow.started": FIXTURES_DIR / "workflow-started.json",
    "workflow.status": FIXTURES_DIR / "workflow-status.json",
    "assistant.text": FIXTURES_DIR / "assistant-text.json",
    "tool.started": FIXTURES_DIR / "tool-started.json",
    "tool.completed": FIXTURES_DIR / "tool-completed.json",
    "workflow.approval_required": FIXTURES_DIR / "workflow-approval-required.json",
    "workflow.completed": FIXTURES_DIR / "workflow-completed.json",
    "workflow.failed": FIXTURES_DIR / "workflow-failed.json",
}

PAYLOAD_MODELS = {
    "workflow.started": WorkflowStartedPayload,
    "workflow.status": WorkflowStatusPayload,
    "assistant.text": AssistantTextPayload,
    "tool.started": ToolStartedPayload,
    "tool.completed": ToolCompletedPayload,
    "workflow.approval_required": WorkflowApprovalRequiredPayload,
    "workflow.completed": WorkflowCompletedPayload,
    "workflow.failed": WorkflowFailedPayload,
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Node invocation -- mirrors `test_agent_banned_patterns_contract.py`'s
# `_compile_in_node`: shell out to `node -e "..."`, transpiling the real
# `agent-events.ts` source fresh each call (via the `typescript` package,
# already a `packages/contracts` devDependency -- resolved because the
# subprocess's cwd is `packages/contracts`, where pnpm symlinks it).
# ---------------------------------------------------------------------------

# Transpiles agent-events.ts (argv[1]) to CommonJS, loads it, and runs
# `validateAgentEvent` over a batch of {id, event} items (argv[2], JSON),
# printing `{"results": [{"id", "ok", "value"?, "error"?}, ...]}`.
_VALIDATE_BATCH_SCRIPT = r"""
const fs = require("fs");
const os = require("os");
const path = require("path");
const ts = require("typescript");

const tsSourcePath = process.argv[1];
const items = JSON.parse(process.argv[2]);

const source = fs.readFileSync(tsSourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  fileName: "agent-events.ts",
});

const tmpFile = path.join(os.tmpdir(), `agent-events-validate-${process.pid}-${Date.now()}.cjs`);
fs.writeFileSync(tmpFile, transpiled.outputText);
let mod;
try {
  mod = require(tmpFile);
} finally {
  fs.unlinkSync(tmpFile);
}

const results = items.map((item) => {
  try {
    const value = mod.validateAgentEvent(item.event);
    return { id: item.id, ok: true, value };
  } catch (err) {
    return { id: item.id, ok: false, error: String((err && err.message) || err) };
  }
});
process.stdout.write(JSON.stringify({ results }));
"""

# Transpiles agent-events.ts (argv[1]) and prints its exported field-set
# tables and discriminant list, for the Python-side field-parity diff.
_INTROSPECT_SCRIPT = r"""
const fs = require("fs");
const os = require("os");
const path = require("path");
const ts = require("typescript");

const tsSourcePath = process.argv[1];
const source = fs.readFileSync(tsSourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  fileName: "agent-events.ts",
});

const tmpFile = path.join(os.tmpdir(), `agent-events-introspect-${process.pid}-${Date.now()}.cjs`);
fs.writeFileSync(tmpFile, transpiled.outputText);
let mod;
try {
  mod = require(tmpFile);
} finally {
  fs.unlinkSync(tmpFile);
}

process.stdout.write(JSON.stringify({
  agentEventTypes: mod.AGENT_EVENT_TYPES,
  payloadFields: mod.PAYLOAD_FIELDS,
  envelopeFields: mod.ENVELOPE_FIELDS,
  stopReasons: mod.STOP_REASONS,
}));
"""


def _require_node_bin() -> str:
    """Recomputed on every call (not cached at import time) so the
    fails-clearly-when-missing test below can monkeypatch `shutil.which` and
    observe the real failure path, not a value baked in before the patch.
    """
    node_bin = shutil.which("node")
    assert node_bin, (
        "node binary not found on PATH -- required to check the TypeScript "
        "agent-events validator (packages/contracts/src/agent-events.ts)"
    )
    return node_bin


def _run_node_script(script: str, *args: str) -> dict:
    node_bin = _require_node_bin()
    proc = subprocess.run(
        [node_bin, "-e", script, *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        cwd=CONTRACTS_DIR,
    )
    return json.loads(proc.stdout)


def _ts_validate_batch(items: list[dict]) -> dict[str, dict]:
    result = _run_node_script(_VALIDATE_BATCH_SCRIPT, str(AGENT_EVENTS_TS_PATH), json.dumps(items))
    return {entry["id"]: entry for entry in result["results"]}


@functools.lru_cache(maxsize=1)
def _ts_introspect() -> dict:
    return _run_node_script(_INTROSPECT_SCRIPT, str(AGENT_EVENTS_TS_PATH))


# ---------------------------------------------------------------------------
# Node availability: fails clearly, never a silent skip.
# ---------------------------------------------------------------------------


def test_node_is_on_path_for_this_environment():
    """Sanity check for the report: node really is available here, and the
    dual-language tests below are exercising it for real, not skipping.
    """
    assert shutil.which("node"), "node binary not found on PATH"


def test_dual_language_check_fails_clearly_when_node_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(AssertionError, match="node binary not found on PATH"):
        _require_node_bin()


# ---------------------------------------------------------------------------
# All eight event types exist on both sides, and no more.
# ---------------------------------------------------------------------------


def test_python_and_typescript_agree_on_the_set_of_eight_event_types():
    introspected = _ts_introspect()
    assert set(EVENT_TYPES) == set(introspected["agentEventTypes"])
    assert len(EVENT_TYPES) == 8
    assert set(GOLDEN_FIXTURES) == set(EVENT_TYPES)


def test_assistant_text_delta_is_not_a_ts_union_member():
    introspected = _ts_introspect()
    assert "assistant.text.delta" not in introspected["agentEventTypes"]


# ---------------------------------------------------------------------------
# Field-for-field parity per type (not just aggregate).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", sorted(PAYLOAD_MODELS))
def test_payload_field_sets_match_between_python_and_typescript(event_type):
    introspected = _ts_introspect()
    python_fields = set(PAYLOAD_MODELS[event_type].model_fields.keys())
    ts_fields = set(introspected["payloadFields"][event_type])
    assert python_fields == ts_fields, (
        f"{event_type}: payload field-set diverges between languages -- "
        f"python-only={python_fields - ts_fields}, ts-only={ts_fields - python_fields}"
    )


# ---------------------------------------------------------------------------
# Golden fixtures: byte-equal-in-shape, per type, both languages.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", sorted(GOLDEN_FIXTURES))
def test_golden_fixture_round_trips_byte_equal_on_python_side(event_type):
    raw = _read_json(GOLDEN_FIXTURES[event_type])
    event = WorkflowRunEventAdapter.validate_python(raw)
    assert event.event_type == event_type
    assert event.model_dump(mode="json") == raw


@pytest.mark.parametrize("event_type", sorted(GOLDEN_FIXTURES))
def test_golden_fixture_is_byte_equal_in_shape_across_both_languages(event_type):
    raw = _read_json(GOLDEN_FIXTURES[event_type])

    python_event = WorkflowRunEventAdapter.validate_python(raw)
    python_dump = python_event.model_dump(mode="json")
    assert python_dump == raw, f"{event_type}: Python round-trip is not byte-equal to the fixture"

    ts_results = _ts_validate_batch([{"id": event_type, "event": raw}])
    ts_result = ts_results[event_type]
    assert ts_result["ok"], (
        f"{event_type}: TS validator rejected the golden fixture: {ts_result.get('error')}"
    )
    assert ts_result["value"] == raw, (
        f"{event_type}: TS validator's parsed shape diverges from the fixture"
    )
    assert ts_result["value"] == python_dump, (
        f"{event_type}: Python and TypeScript parsed structures are not byte-equal"
    )


# ---------------------------------------------------------------------------
# Envelope snapshot: pins v: 1.
# ---------------------------------------------------------------------------


def test_envelope_v1_snapshot_fixture_pins_v_equal_1_on_both_languages():
    raw = _read_json(FIXTURES_DIR / "envelope-v1-snapshot.json")
    assert raw["v"] == 1

    event = WorkflowRunEventAdapter.validate_python(raw)
    assert event.v == 1

    results = _ts_validate_batch([{"id": "envelope-snapshot", "event": raw}])
    result = results["envelope-snapshot"]
    assert result["ok"]
    assert result["value"]["v"] == 1


def test_envelope_with_wrong_v_fails_on_both_languages():
    raw = _read_json(INVALID_FIXTURES_DIR / "wrong-envelope-version.json")
    assert raw["v"] != 1

    with pytest.raises(ValidationError):
        WorkflowRunEventAdapter.validate_python(raw)

    results = _ts_validate_batch([{"id": "wrong-v", "event": raw}])
    result = results["wrong-v"]
    assert not result["ok"]
    assert "v must be the literal 1" in result["error"]


# ---------------------------------------------------------------------------
# `assistant.text.delta` stays reserved -- rejected by both, naming it.
# ---------------------------------------------------------------------------


def test_assistant_text_delta_fixture_rejected_by_both_languages_naming_it():
    raw = _read_json(INVALID_FIXTURES_DIR / "assistant-text-delta-reserved.json")
    assert raw["event_type"] == "assistant.text.delta"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowRunEventAdapter.validate_python(raw)
    assert "assistant.text.delta" in str(exc_info.value)

    results = _ts_validate_batch([{"id": "delta", "event": raw}])
    result = results["delta"]
    assert not result["ok"]
    assert "assistant.text.delta" in result["error"]


# ---------------------------------------------------------------------------
# Negative fixtures: a one-language-only-valid divergence fails loudly,
# naming the offending event type. This is the mechanism's whole point --
# proves the contract test would actually catch real drift, not just pass
# vacuously because both languages happen to agree today.
# ---------------------------------------------------------------------------


def test_python_only_valid_divergence_fails_the_ts_side_naming_workflow_started():
    """`sequence_number` is a numeric *string* ("0") in this fixture.
    Pydantic's lax int coercion accepts it and produces `sequence_number ==
    0` -- genuinely Python-only-valid. The hand-rolled TS validator requires
    a real `number` (mirroring the `AgentEvent` field type) and must reject
    it, naming `workflow.started` as the offender.
    """
    raw = _read_json(INVALID_FIXTURES_DIR / "python-only-valid-workflow-started.json")
    assert raw["event_type"] == "workflow.started"
    assert isinstance(raw["sequence_number"], str)

    # Confirm this really is Python-valid (not merely "we assumed it is").
    event = WorkflowRunEventAdapter.validate_python(raw)
    assert event.sequence_number == 0

    results = _ts_validate_batch([{"id": "python-only-valid", "event": raw}])
    result = results["python-only-valid"]
    assert not result["ok"], "TS validator should reject a stringly-typed sequence_number"
    assert result["error"].startswith("workflow.started:"), (
        f"TS-side failure must name the offending event type, got: {result['error']!r}"
    )


def test_ts_only_valid_divergence_fails_the_python_side_naming_tool_started():
    """`timestamp` is a non-ISO string ("not-a-timestamp") in this fixture.
    This hand-rolled TS validator only checks `typeof timestamp ===
    "string"` -- genuinely TS-only-valid. Pydantic's strict `datetime` field
    must reject it, naming `tool.started` as the offender.
    """
    raw = _read_json(INVALID_FIXTURES_DIR / "ts-only-valid-tool-started.json")
    assert raw["event_type"] == "tool.started"

    # Confirm this really is TS-valid (not merely "we assumed it is").
    results = _ts_validate_batch([{"id": "ts-only-valid", "event": raw}])
    result = results["ts-only-valid"]
    assert result["ok"], f"expected TS validator to accept this fixture, got: {result.get('error')}"

    with pytest.raises(ValidationError) as exc_info:
        WorkflowRunEventAdapter.validate_python(raw)
    assert "tool.started" in str(exc_info.value), (
        f"Python-side failure must name the offending event type, got: {exc_info.value!r}"
    )
