"""Generic `Playbook` artifact contract tests — issue #1036 (W2-A, ADR-072 decision 2).

Exercises the workflow-agnostic shape (`Playbook`, `PlaybookStep`,
`TerminationPolicy`) and the tool-resolution validator
(`validate_playbook_tools`) against synthetic fixtures only — the concrete
Optimize Product playbook is proven separately in
`test_agent_playbooks_optimize_product.py`.

Acceptance criteria covered here (from the issue #1036 workflow cache):
- "Playbook is a frozen dataclass — mutating a released playbook raises.
  Assert this." -> `TestPlaybookIsFrozen`.
- "Every tools entry resolves against the real registry... A typo'd tool
  name must fail loudly, naming the offending step — assert that
  behaviour, do not merely rely on it." -> `TestValidatePlaybookTools`,
  driven with synthetic mismatched fixtures so the assertion does not
  depend on the concrete Optimize Product playbook happening to be right.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pydantic import BaseModel

from juli_backend.services.agent.playbooks.base import (
    Playbook,
    PlaybookStep,
    PlaybookToolResolutionError,
    TerminationPolicy,
    validate_playbook_tools,
)
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)


class _FixtureInput(BaseModel):
    pass


class _FixtureOutput(BaseModel):
    status: str = "ok"


def _make_registry(*names: str) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(
            ToolSpec(
                name=name,
                description=f"Test-only fixture tool {name}.",
                input_model=_FixtureInput,
                output_model=_FixtureOutput,
                classification=ToolClassification.READ,
                policy=ToolPolicy.AUTO,
                timeout_seconds=10,
            )
        )
    return registry


def _make_termination_policy(**overrides: Any) -> TerminationPolicy:
    defaults: dict[str, Any] = dict(
        max_iterations=6,
        max_extensions=1,
        extension_iterations=2,
        wall_clock_timeout_s=300,
        approval_timeout_h=4,
        required_steps=("do_the_thing",),
    )
    defaults.update(overrides)
    return TerminationPolicy(**defaults)


def _make_step(**overrides: Any) -> PlaybookStep:
    defaults: dict[str, Any] = dict(
        step_id="1",
        intent="Do the thing the seller asked for.",
        tools=("do_the_thing",),
        policy=ToolPolicy.AUTO,
    )
    defaults.update(overrides)
    return PlaybookStep(**defaults)


def _make_playbook(**overrides: Any) -> Playbook:
    defaults: dict[str, Any] = dict(
        workflow_key="fixture_workflow",
        version=1,
        steps=(_make_step(),),
        termination_policy=_make_termination_policy(),
    )
    defaults.update(overrides)
    return Playbook(**defaults)


class TestPlaybookIsFrozen:
    """Acceptance criterion: mutating a released playbook raises."""

    def test_mutating_playbook_field_raises(self):
        playbook = _make_playbook()
        with pytest.raises(dataclasses.FrozenInstanceError):
            playbook.version = 2  # type: ignore[misc]

    def test_mutating_playbook_step_field_raises(self):
        step = _make_step()
        with pytest.raises(dataclasses.FrozenInstanceError):
            step.intent = "Something else."  # type: ignore[misc]

    def test_mutating_termination_policy_field_raises(self):
        policy = _make_termination_policy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.max_iterations = 99  # type: ignore[misc]


class TestPlaybookValidation:
    def test_empty_steps_rejected(self):
        with pytest.raises(ValueError, match="steps"):
            _make_playbook(steps=())

    def test_non_playbook_step_entries_rejected(self):
        with pytest.raises(TypeError, match="PlaybookStep"):
            _make_playbook(steps=("not-a-step",))

    def test_duplicate_step_ids_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            _make_playbook(steps=(_make_step(step_id="1"), _make_step(step_id="1")))

    def test_non_positive_version_rejected(self):
        with pytest.raises(ValueError, match="version"):
            _make_playbook(version=0)

    def test_empty_workflow_key_rejected(self):
        with pytest.raises(ValueError, match="workflow_key"):
            _make_playbook(workflow_key="")


class TestPlaybookStepValidation:
    def test_empty_tools_rejected(self):
        with pytest.raises(ValueError, match="tools"):
            _make_step(tools=())

    def test_non_tool_policy_rejected(self):
        with pytest.raises(TypeError, match="ToolPolicy"):
            _make_step(policy="auto")

    def test_empty_intent_rejected(self):
        with pytest.raises(ValueError, match="intent"):
            _make_step(intent="")

    def test_empty_step_id_rejected(self):
        with pytest.raises(ValueError, match="step_id"):
            _make_step(step_id="")


class TestTerminationPolicyValidation:
    def test_non_positive_max_iterations_rejected(self):
        with pytest.raises(ValueError, match="max_iterations"):
            _make_termination_policy(max_iterations=0)

    def test_negative_max_extensions_rejected(self):
        with pytest.raises(ValueError, match="max_extensions"):
            _make_termination_policy(max_extensions=-1)

    def test_empty_required_steps_rejected(self):
        with pytest.raises(ValueError, match="required_steps"):
            _make_termination_policy(required_steps=())

    def test_non_positive_wall_clock_timeout_rejected(self):
        with pytest.raises(ValueError, match="wall_clock_timeout_s"):
            _make_termination_policy(wall_clock_timeout_s=0)


class TestValidatePlaybookTools:
    """Acceptance criterion: a typo'd tool name fails loudly, naming the
    offending step — proven here by driving the validator with synthetic
    mismatched inputs, not merely trusting the real playbook happens to
    line up."""

    def test_all_tools_resolve_passes_silently(self):
        registry = _make_registry("do_the_thing")
        validate_playbook_tools(_make_playbook(), registry)  # must not raise

    def test_unresolved_tool_name_raises_naming_the_step(self):
        registry = _make_registry("do_the_thing")
        playbook = _make_playbook(
            steps=(
                _make_step(step_id="1"),
                _make_step(
                    step_id="2",
                    intent="Do a mistyped thing.",
                    tools=("do_the_thing_TYPO",),
                ),
            )
        )
        with pytest.raises(PlaybookToolResolutionError) as exc_info:
            validate_playbook_tools(playbook, registry)
        message = str(exc_info.value)
        assert "'2'" in message
        assert "do_the_thing_TYPO" in message
        assert "fixture_workflow" in message

    def test_unresolved_tool_error_names_only_the_offending_step(self):
        """Multiple steps exist and only one has a bad tool name; the raised
        message names that step's id specifically, not a generic message."""
        registry = _make_registry("read_a", "read_b")
        playbook = _make_playbook(
            steps=(
                _make_step(step_id="1", intent="Read A.", tools=("read_a",)),
                _make_step(step_id="2", intent="Read B, badly.", tools=("read_b_typo",)),
            )
        )
        with pytest.raises(PlaybookToolResolutionError, match=r"step '2'"):
            validate_playbook_tools(playbook, registry)
