"""Typed frozen `Playbook` artifact — issue #1036 (W2-A, ADR-072 decision 2).

One artifact, three consumers (ADR-072 decision 2): ADR-069's two-way
cross-validation imports it, the (not-yet-built) run executor derives its
run allowlist from it, and the (not-yet-built) prompt composer renders it
into the prompt's single `{playbook}` slot. Because all three read this one
artifact, the text the model sees and the allowlist the executor enforces
cannot disagree.

This module holds the generic, workflow-agnostic shape (`Playbook`,
`PlaybookStep`, `TerminationPolicy`) plus the tool-resolution validator.
The concrete Optimize Product playbook lives in `optimize_product.py`.

**Safety surface (ADR-072 d.2, ADR-068 d.2's "compiled" requirement).** Every
type here is a frozen dataclass — data only, no behavior a tuning loop could
redirect. A future prompt optimizer can tune prose (`services/agent/prompts/`,
out of scope here and owned elsewhere in this wave); it can never mutate a
playbook. `__post_init__` validation raises on malformed *data* (e.g. an
empty `tools` tuple); it never reaches out to anything — no marketplace
import, no I/O, no network access anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from juli_backend.services.agent.tools.registry import ToolPolicy, ToolRegistry, UnknownToolError


class PlaybookToolResolutionError(ValueError):
    """Raised when a `Playbook` step names a tool that does not resolve
    against the real `ToolRegistry` — names the offending step (workflow
    key, step id, intent) and the unresolved tool name, never just "some
    tool was wrong" (issue #1036 acceptance criterion: fail loudly)."""


@dataclass(frozen=True)
class TerminationPolicy:
    """Declarative loop-termination values (ADR-073 decision 2), carried on
    the `Playbook` artifact itself so the runner reads termination from the
    same artifact rather than a module constant.

    - `max_iterations` — soft cap; one iteration = one `LLMService.complete()`
      call.
    - `max_extensions` — how many times the model's `continue` proposal at
      the soft cap is auto-granted.
    - `extension_iterations` — additional iterations granted per extension
      (ADR-073: "+2 iterations each"; hard cap for Optimize Product v1 is
      `max_iterations + max_extensions * extension_iterations` = 6 + 1*2 = 8).
    - `wall_clock_timeout_s` — measured over running time only; the clock
      pauses during `waiting_approval` (ADR-073 decision 2).
    - `approval_timeout_h` — how long a `waiting_approval` run may sit
      unanswered before the reaper expires it (ADR-073 decision 2 amendment).
    - `required_steps` — tool names whose completion defines "did the job"
      for the execution-quality metric; a `final_response` without them is
      honest data, not a synthetic failure (ADR-073 decision 2).
    - `terminal_tools` — tool names that are side-effect-free and can be
      called to explicitly end a run without proposing changes (ADR-088
      decision 1). Not added as playbook steps; instead, appended to the
      model-facing tool list directly by the runner. Empty by default.
    """

    max_iterations: int
    max_extensions: int
    extension_iterations: int
    wall_clock_timeout_s: int
    approval_timeout_h: int
    required_steps: tuple[str, ...]
    terminal_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.max_iterations, int) or self.max_iterations <= 0:
            raise ValueError("TerminationPolicy.max_iterations must be a positive int")
        if not isinstance(self.max_extensions, int) or self.max_extensions < 0:
            raise ValueError("TerminationPolicy.max_extensions must be a non-negative int")
        if not isinstance(self.extension_iterations, int) or self.extension_iterations <= 0:
            raise ValueError("TerminationPolicy.extension_iterations must be a positive int")
        if not isinstance(self.wall_clock_timeout_s, int) or self.wall_clock_timeout_s <= 0:
            raise ValueError("TerminationPolicy.wall_clock_timeout_s must be a positive int")
        if not isinstance(self.approval_timeout_h, int) or self.approval_timeout_h <= 0:
            raise ValueError("TerminationPolicy.approval_timeout_h must be a positive int")
        if not isinstance(self.required_steps, tuple) or not self.required_steps:
            raise ValueError("TerminationPolicy.required_steps must be a non-empty tuple")
        if not all(isinstance(name, str) and name for name in self.required_steps):
            raise ValueError("TerminationPolicy.required_steps entries must be non-empty strings")
        if not isinstance(self.terminal_tools, tuple):
            raise ValueError("TerminationPolicy.terminal_tools must be a tuple")
        if not all(isinstance(name, str) and name for name in self.terminal_tools):
            raise ValueError("TerminationPolicy.terminal_tools entries must be non-empty strings")


@dataclass(frozen=True)
class PlaybookStep:
    """One ordered playbook step (ADR-072 decision 2).

    `intent` is business English, seller-meaningful — never a vendor
    endpoint name or an internal class name (issue #1036 acceptance
    criterion; note #1014 flags model-facing vendor vocabulary as an open
    defect this artifact must not add to). `tools` names `ToolSpec`
    **names** (never vendor endpoint names) — resolved against the real
    registry by `validate_playbook_tools`, not merely assumed. `policy`
    reuses `ToolPolicy` from the tool registry itself (AUTO/CONFIRM) so the
    playbook and the registry can never speak two different policy
    vocabularies for the same concept.
    """

    step_id: str
    intent: str
    tools: tuple[str, ...]
    policy: ToolPolicy

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("PlaybookStep.step_id must be a non-empty string")
        if not self.intent:
            raise ValueError("PlaybookStep.intent must be a non-empty string")
        if not isinstance(self.tools, tuple) or not self.tools:
            raise ValueError("PlaybookStep.tools must be a non-empty tuple")
        if not all(isinstance(name, str) and name for name in self.tools):
            raise ValueError("PlaybookStep.tools entries must be non-empty strings")
        if not isinstance(self.policy, ToolPolicy):
            raise TypeError(f"PlaybookStep.policy must be a ToolPolicy member, got {self.policy!r}")


@dataclass(frozen=True)
class Playbook:
    """A frozen, version-addressed workflow playbook (ADR-072 decision 2).

    Mutating a released `Playbook` (or any of its steps) raises
    `dataclasses.FrozenInstanceError` — this is the safety surface: a
    future prompt optimizer tunes the prose file, never this artifact.
    """

    workflow_key: str
    version: int
    steps: tuple[PlaybookStep, ...]
    termination_policy: TerminationPolicy

    def __post_init__(self) -> None:
        if not self.workflow_key:
            raise ValueError("Playbook.workflow_key must be a non-empty string")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("Playbook.version must be a positive int")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("Playbook.steps must be a non-empty tuple")
        if not all(isinstance(step, PlaybookStep) for step in self.steps):
            raise TypeError("Playbook.steps entries must all be PlaybookStep instances")
        if not isinstance(self.termination_policy, TerminationPolicy):
            raise TypeError("Playbook.termination_policy must be a TerminationPolicy instance")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError(f"Playbook.steps has duplicate step_id values: {step_ids}")


def validate_playbook_tools(playbook: Playbook, registry: ToolRegistry) -> None:
    """Resolve every `tools` entry on every step against the real registry.

    Raises `PlaybookToolResolutionError` naming the offending step
    (workflow key, step id, intent) and the unresolved tool name on the
    first mismatch. Called eagerly at import time by each concrete playbook
    module (e.g. `optimize_product.py`) against the real
    `register_product_read_tools`/`register_product_write_tools` registry,
    so a typo'd tool name fails loudly at import rather than silently
    later — the whole point of the "one artifact, three consumers" design
    (ADR-072 decision 2): the text the model sees and the allowlist the
    executor enforces cannot disagree because both trace back to a playbook
    already proven to resolve.
    """
    for step in playbook.steps:
        for tool_name in step.tools:
            try:
                registry.get(tool_name)
            except UnknownToolError as exc:
                raise PlaybookToolResolutionError(
                    f"Playbook {playbook.workflow_key!r} v{playbook.version} step "
                    f"{step.step_id!r} ({step.intent!r}) references unknown tool "
                    f"{tool_name!r}, which does not resolve against the real "
                    "ToolRegistry."
                ) from exc
