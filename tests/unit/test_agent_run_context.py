"""Opening context message + initial run state (issue #1188).

These tests pin the two halves of the defect the #1124 live smoke found:
a run row created with `state={}` crashed `WorkflowRunner.run()` at its
first statement, and the opening `source: "juli"` context message the
prompt contract depends on was never built in production code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from juli_backend.services.agent.run_context import (
    DIRECT_RUN_RATIONALE,
    JULI_SOURCE,
    build_opening_context_message,
    initial_run_state,
)
from juli_backend.services.agent.runner import RunState, RunStateFieldMissingError

PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "backend/src/juli_backend/services/agent/prompts/optimize_product/v1.md"
)


class TestInitialRunState:
    def test_blob_loads_through_from_dict(self):
        """The regression this slice exists for: a freshly created run must be
        loadable by the exact reader `WorkflowRunner.run()` uses."""
        blob = initial_run_state(
            build_opening_context_message(workflow_key="optimize_product_2", rationale="why")
        )
        state = RunState.from_dict(blob)
        assert state.iteration_count == 0
        assert len(state.conversation_window) == 1

    def test_blob_carries_every_known_field(self):
        """Built from a default `RunState`, so the field set cannot drift from
        the dataclass -- a hand-written literal would silently start producing
        blobs `from_dict` rejects, which is the bug being fixed."""
        blob = initial_run_state(
            build_opening_context_message(workflow_key="optimize_product_2", rationale="why")
        )
        assert set(blob) == set(RunState().to_dict())

    def test_empty_blob_is_still_rejected(self):
        """ADR-073 decision 5's guarantee must survive this fix: `{}` means a
        corrupted/truncated blob, never a fresh run. If this test ever fails
        because `from_dict` was made lenient, the fix was applied in the wrong
        place."""
        with pytest.raises(RunStateFieldMissingError):
            RunState.from_dict({})

    def test_opening_context_is_the_first_user_message(self):
        opening = build_opening_context_message(workflow_key="optimize_product_2", rationale="why")
        blob = initial_run_state(opening)
        first = blob["conversation_window"][0]
        assert first["role"] == "user"
        assert json.loads(first["content"]) == opening


class TestOpeningContextMessage:
    def test_source_is_juli(self):
        msg = build_opening_context_message(workflow_key="k", rationale="r")
        assert msg["source"] == JULI_SOURCE == "juli"

    def test_absent_fields_are_omitted_not_faked(self):
        """Prompt Sec.4: "the real message may omit a field with no value --
        never fabricate one that is missing". An empty `signals: []` would
        assert "we looked and found none", a different claim from "no signal
        data accompanies this run"."""
        msg = build_opening_context_message(workflow_key="k", rationale="r")
        assert "signals" not in msg
        assert "expected_impact" not in msg["action_card"]

    def test_present_fields_are_included(self):
        signals = [{"kpi_id": "ctr", "signal_type": "risk", "one_line": "ctr down"}]
        impact = {"metric": "ctr", "confidence": "low"}
        msg = build_opening_context_message(
            workflow_key="k", rationale="r", signals=signals, expected_impact=impact
        )
        assert msg["signals"] == signals
        assert msg["action_card"]["expected_impact"] == impact

    def test_direct_run_rationale_does_not_invent_a_trigger(self):
        """A run with no ActionCard behind it must say so rather than imply a
        signal the seller never saw."""
        assert "directly" in DIRECT_RUN_RATIONALE
        assert "no prior signal" in DIRECT_RUN_RATIONALE

    def test_shape_matches_the_prompt_contract(self):
        """The prompt tells the model exactly which keys arrive. If either side
        changes without the other, the model is grounded in a message shape it
        was not told about -- so pin agreement, not just our own output."""
        documented = json.loads(
            PROMPT_PATH.read_text(encoding="utf-8").split("```json", 1)[1].split("```", 1)[0]
        )
        msg = build_opening_context_message(
            workflow_key="k",
            rationale="r",
            signals=[{"kpi_id": "ctr"}],
            expected_impact={"metric": "ctr", "confidence": "low"},
        )
        assert set(msg) == set(documented)
        assert set(msg["action_card"]) == set(documented["action_card"])
        assert set(msg["product_binding"]) == set(documented["product_binding"])
