"""`RunState` — ADR-073 decision 1, issue #1118 / AGT-W3A.

Pure-Python, no database needed: this slice ships an explicit state object
and its blob (de)serialization, not a runner or storage plumbing (that's
`test_conversation_store.py`).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from juli_backend.services.agent.runner.state import (
    RunState,
    RunStateFieldMissingError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/services/agent/runner/state.py"


def _full_blob() -> dict:
    return {
        "conversation_window": [
            {"role": "user", "content": "optimize this listing"},
            {"role": "assistant", "content": "sure, let me look"},
        ],
        "iteration_count": 2,
        "extensions_granted": 1,
        "next_sequence": 5,
        "pending_confirmation": {"tool_call_id": "call_1", "tool_name": "update_price"},
        "basis_snapshots": {"price": "sha256:deadbeef"},
        "running_seconds_elapsed": 12.5,
    }


class TestRunStateShape:
    """AC1: RunState is an explicit dataclass with named fields for
    conversation window, iteration_count, extensions_granted,
    next_sequence, pending_confirmation, basis_snapshots, and a
    running-time accumulator — assert each field exists by name and
    type."""

    def test_is_a_dataclass(self):
        assert dataclasses.is_dataclass(RunState)

    def test_has_exactly_the_required_named_fields_with_expected_types(self):
        expected_types = {
            "conversation_window": list,
            "iteration_count": int,
            "extensions_granted": int,
            "next_sequence": int,
            "pending_confirmation": type(None),  # default value's type
            "basis_snapshots": dict,
            "running_seconds_elapsed": float,
        }
        field_names = {f.name for f in dataclasses.fields(RunState)}
        for name in expected_types:
            assert name in field_names, f"RunState is missing field {name!r}"

        state = RunState()
        assert isinstance(state.conversation_window, list)
        assert isinstance(state.iteration_count, int)
        assert isinstance(state.extensions_granted, int)
        assert isinstance(state.next_sequence, int)
        assert state.pending_confirmation is None
        assert isinstance(state.basis_snapshots, dict)
        assert isinstance(state.running_seconds_elapsed, float)

    def test_defaults_describe_a_fresh_run(self):
        state = RunState()
        assert state.conversation_window == []
        assert state.iteration_count == 0
        assert state.extensions_granted == 0
        assert state.next_sequence == 0
        assert state.pending_confirmation is None
        assert state.basis_snapshots == {}
        assert state.running_seconds_elapsed == 0.0


class TestNextSequenceOwnership:
    """AC2: next_sequence is owned by RunState, not derived or recomputed
    elsewhere — reading it twice in sequence (simulating two emitted
    events) yields two increasing integers with no reuse and no gap logic
    hidden outside this object (ADR-073/074 I5)."""

    def test_allocate_sequence_yields_increasing_non_reused_integers(self):
        state = RunState()

        first = state.allocate_sequence()
        second = state.allocate_sequence()
        third = state.allocate_sequence()

        assert (first, second, third) == (0, 1, 2)
        assert len({first, second, third}) == 3  # no reuse

    def test_allocate_sequence_advances_the_owned_counter(self):
        state = RunState(next_sequence=41)

        minted = state.allocate_sequence()

        assert minted == 41
        assert state.next_sequence == 42  # the object itself owns the advance


class TestBasisSnapshotsStructurallySeparate:
    """AC3: basis_snapshots is a field structurally distinct from the
    conversation window — serializing only the conversation window (the
    value passed to LLMService.complete) never includes any
    basis_snapshots content, by construction (ADR-073 decision 4)."""

    def test_conversation_window_for_llm_excludes_basis_snapshots(self):
        secret_hash = "sha256:super-secret-basis-hash-the-llm-must-never-see"
        state = RunState(
            conversation_window=[{"role": "user", "content": "optimize this listing"}],
            basis_snapshots={"price": secret_hash, "title": "sha256:another-one"},
        )

        llm_view = state.conversation_window_for_llm()

        assert llm_view == state.conversation_window
        serialized = json.dumps(llm_view)
        assert secret_hash not in serialized
        assert "basis_snapshots" not in serialized

    def test_conversation_window_for_llm_returns_a_copy_not_the_live_list(self):
        state = RunState(conversation_window=[{"role": "user", "content": "hi"}])

        llm_view = state.conversation_window_for_llm()
        llm_view.append({"role": "user", "content": "mutated after the fact"})

        assert len(state.conversation_window) == 1


class TestRoundTripFidelity:
    """AC5: the JSONB-blob implementation round-trips every RunState field
    through serialize -> deserialize with value equality — asserted
    field-by-field, not just object-equality, so a silently-dropped field
    is caught."""

    def test_to_dict_from_dict_round_trip_is_field_by_field_lossless(self):
        original = RunState(
            conversation_window=[
                {"role": "user", "content": "optimize this listing"},
                {"role": "assistant", "content": "sure, let me look"},
            ],
            iteration_count=3,
            extensions_granted=1,
            next_sequence=7,
            pending_confirmation={"tool_call_id": "call_9", "tool_name": "update_price"},
            basis_snapshots={"price": "sha256:abc123"},
            running_seconds_elapsed=42.75,
        )

        blob = original.to_dict()
        restored = RunState.from_dict(blob)

        assert restored.conversation_window == original.conversation_window
        assert restored.iteration_count == original.iteration_count
        assert restored.extensions_granted == original.extensions_granted
        assert restored.next_sequence == original.next_sequence
        assert restored.pending_confirmation == original.pending_confirmation
        assert restored.basis_snapshots == original.basis_snapshots
        assert restored.running_seconds_elapsed == original.running_seconds_elapsed

    def test_to_dict_round_trips_through_json_text(self):
        """The blob genuinely has to survive going through JSON text, since
        that's what a JSONB column stores/loads."""
        original = RunState.from_dict(_full_blob())

        blob_after_json_round_trip = json.loads(json.dumps(original.to_dict()))
        restored = RunState.from_dict(blob_after_json_round_trip)

        assert restored == original


class TestForwardCompatUnknownFields:
    """AC6: deserializing a blob with one extra, unrecognized field does
    not raise — the documented forward-compat behavior is
    preserve-and-round-trip (ADR-073 decision 5, the P-CS seam)."""

    def test_unknown_field_does_not_raise_and_is_captured(self):
        blob = _full_blob()
        blob["future_pcs_field"] = {"anything": "a later P-CS phase might add"}

        state = RunState.from_dict(blob)

        assert state.unknown_fields == {
            "future_pcs_field": {"anything": "a later P-CS phase might add"}
        }

    def test_unknown_field_survives_a_read_modify_write_cycle(self):
        """Non-destructive: a blob written by a future version must not
        lose data when read and rewritten by this one."""
        blob = _full_blob()
        blob["future_pcs_field"] = "data from a newer writer"

        state = RunState.from_dict(blob)
        state.iteration_count += 1  # simulate this version doing real work
        rewritten = state.to_dict()

        assert rewritten["future_pcs_field"] == "data from a newer writer"
        assert rewritten["iteration_count"] == blob["iteration_count"] + 1


class TestMissingRequiredFieldFailsLoudly:
    """AC7: deserializing a blob missing a currently-required field fails
    loudly, not silently defaulted — a corrupted or truncated blob must
    never be mistaken for a fresh run."""

    @pytest.mark.parametrize(
        "missing_field",
        [
            "conversation_window",
            "iteration_count",
            "extensions_granted",
            "next_sequence",
            "pending_confirmation",
            "basis_snapshots",
            "running_seconds_elapsed",
        ],
    )
    def test_missing_required_field_raises(self, missing_field: str):
        blob = _full_blob()
        del blob[missing_field]

        with pytest.raises(RunStateFieldMissingError, match=missing_field):
            RunState.from_dict(blob)

    def test_missing_field_error_is_a_value_error(self):
        """Callers that only know to catch ValueError still catch this."""
        blob = _full_blob()
        del blob["next_sequence"]

        with pytest.raises(ValueError):
            RunState.from_dict(blob)


class TestNoWorkflowRunnerInThisSlice:
    """AC8: no WorkflowRunner class exists or is imported by this slice's
    production code — this slice is provably runner-independent (ADR-073's
    "no runner yet" boundary).

    Docstring prose *documenting* the deferral (e.g. "WorkflowRunner is a
    later slice") is expected and fine — what must not appear is an actual
    class definition or import."""

    def test_state_module_defines_no_workflow_runner_class(self):
        source = STATE_MODULE_PATH.read_text()
        assert "class WorkflowRunner" not in source

    def test_state_module_imports_no_workflow_runner(self):
        source = STATE_MODULE_PATH.read_text()
        assert "import WorkflowRunner" not in source
