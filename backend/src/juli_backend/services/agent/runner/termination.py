"""Termination-policy evaluation — iteration cap, extensions, paused wall
clock, checkpoint cancellation (ADR-073 decision 2, issue #1120 / AGT-W3A).

**Architect lock (parent-cache-issue-1115, ADR-073 decision 2).** Every
numeric termination value this module consults — `max_iterations`,
`max_extensions`, `extension_iterations`, `wall_clock_timeout_s`,
`approval_timeout_h` — comes from the `TerminationPolicy` a caller passes
in, read off `OPTIMIZE_PRODUCT_TERMINATION_POLICY` on the active
`Playbook`. **This module never defines its own numeric termination
constant.** A bare `6`, `8`, `300`, or `4` literal anywhere below (outside
a docstring) is a defect — `tests/unit/test_agent_runner_termination.py`'s
`TestNoHardcodedPolicyLiterals` AST-scans this file and fails the build if
one appears. #1119's review mutated `core.py` to hard-code the iteration
cap and no test caught it, because no scripted scenario exceeded ~3
iterations (issue #1120's first inherited finding) — the fix is two-layered:
scenarios that genuinely reach the boundaries (this module + its test file),
plus this static guard, so a literal creeping back in breaks a test even if
some future scenario is under-scripted again.

**Two independent decision surfaces, one shared checkpoint.**

1. `evaluate_checkpoint` — cancellation and the wall-clock timeout. Both are
   evaluated through this single function (never two separately-written
   comparisons) at the top of every loop iteration and immediately before
   every tool execution (`WorkflowRunner`'s call sites, `core.py`). Checkpoints
   are cooperative, never preemptive: a checkpoint that returns a
   `StopReason` only ever prevents the *next* unit of work (the next
   iteration, the next tool call) from starting — it can never unwind one
   already in flight, because nothing in this module (or its caller) has any
   mechanism to interrupt a call already made.
2. `evaluate_iteration_gate` — the soft cap / extension-grant / hard-cap
   decision, evaluated once at the top of every iteration, after the
   checkpoint. Distinct from (1) because granting an extension is not a stop
   decision, it changes the effective cap for subsequent gate evaluations.

**The wall clock accumulates, it does not track wall-clock timestamps
directly (ADR-073 decision 2: "running time only... pauses during
waiting_approval").** `accumulate_running_seconds` adds a caller-measured
delta to the running total; there is deliberately no `pause()`/`resume()`
pair to forget to call correctly — the clock "pauses" simply because the
caller does not call `accumulate_running_seconds` while the run sits in
`waiting_approval` (out of this slice's reachability — CONFIRM-pausing is
#1123). This module supplies the accumulation rule and the checkpoint
comparison; the *measurement* of a running-time delta (via an injected
clock) is `WorkflowRunner`'s job (`core.py`), since only the runner's loop
knows when "running" starts and stops.

**Rounding decision (issue #1120's second inherited finding, from #1118's
review).** `RunState.running_seconds_elapsed` (`state.py`, a `float`) is the
sole authority every decision in this module consults — `evaluate_checkpoint`
compares the float against `policy.wall_clock_timeout_s` directly, never
against a rounded value. `workflow_runs.running_seconds_elapsed` (the
`Integer` column #1117 shipped) is a **lossy mirror**, computed fresh from
the float by `running_seconds_column_value` at write time — never itself
accumulated as an independent running integer total. That choice is
deliberate: recomputing from the authoritative float on every write bounds
the column's drift from the float to a single rounding step (< 0.5s,
round-half-up) *at any instant*, regardless of how many pause/resume cycles
or iterations have occurred — an independently-accumulated integer would let
per-write rounding error compound across the run's lifetime, which
`running_seconds_column_value`'s statelessness rules out by construction.
`tests/unit/test_agent_runner_termination.py`'s
`TestRunningSecondsRounding` asserts this bound across the maximum 8
iterations a run can take, and separately asserts termination at 300.0s and
non-termination at 299.6s both come out consistently regardless of which
representation (float vs. the column mirror) a caller mistakenly consulted
— which is the whole reason the float, never the mirror, backs
`evaluate_checkpoint`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from juli_backend.services.agent.playbooks.base import TerminationPolicy
from juli_backend.services.agent.runner.status import StopReason


def evaluate_checkpoint(
    *,
    cancel_requested: bool,
    running_seconds_elapsed: float,
    policy: TerminationPolicy,
) -> StopReason | None:
    """The one checkpoint function both cancellation and the wall-clock
    timeout are evaluated through (ADR-073 decision 2 acceptance criterion:
    "Cancellation and timeout are evaluated through the same checkpoint
    mechanism — assert both paths call one shared checkpoint function
    rather than duplicating the check").

    Called by `WorkflowRunner` at the top of every iteration and
    immediately before every tool execution — never mid-write; a call
    already in flight always completes regardless of what this function
    would return if called again afterward.

    Cancellation is checked before the wall clock: if a seller cancelled a
    run in the same instant its wall-clock budget also expired, the more
    specific, seller-initiated reason wins.

    Returns `None` when the run should proceed; a `StopReason` when the
    caller must stop before starting the next unit of work.
    """
    if cancel_requested:
        return StopReason.CANCELLED_BY_SELLER
    if running_seconds_elapsed >= policy.wall_clock_timeout_s:
        return StopReason.WALL_CLOCK_TIMEOUT
    return None


def accumulate_running_seconds(current_elapsed: float, *, delta_seconds: float) -> float:
    """Add one caller-measured running-time delta to the wall-clock
    accumulator (ADR-073 decision 2: "running time only").

    There is no companion `pause`/`resume` pair: the clock "pauses" across a
    `waiting_approval` span simply because the caller (`WorkflowRunner`)
    does not call this function while paused — nothing to forget, nothing to
    get out of sync. `delta_seconds` must be non-negative (a caller-measured
    duration, never a raw timestamp difference that could go backward on a
    misbehaving clock); a negative delta is a caller bug, raised loudly
    rather than silently subtracted from the accumulator.
    """
    if delta_seconds < 0:
        raise ValueError(
            f"accumulate_running_seconds: delta_seconds must be non-negative, got {delta_seconds!r}"
        )
    return current_elapsed + delta_seconds


def running_seconds_column_value(running_seconds_elapsed: float) -> int:
    """The lossy, round-half-up mirror of `running_seconds_elapsed` for the
    `workflow_runs.running_seconds_elapsed` `Integer` column (#1117) —
    issue #1120's rounding decision (see module docstring).

    Always derived fresh from the authoritative float — never accumulated
    independently — so the column can drift from the float by at most one
    rounding step (< 0.5s) at any point in a run's lifetime, no matter how
    many times this is called across a run's iterations.
    """
    if running_seconds_elapsed < 0:
        raise ValueError(
            "running_seconds_column_value: running_seconds_elapsed must be "
            f"non-negative, got {running_seconds_elapsed!r}"
        )
    return math.floor(running_seconds_elapsed + 0.5)


class IterationGateAction(StrEnum):
    """What `WorkflowRunner` should do next, per `evaluate_iteration_gate`."""

    PROCEED = "proceed"
    EXTEND = "extend"
    STOP = "stop"


@dataclass(frozen=True)
class IterationGate:
    """One `evaluate_iteration_gate` decision.

    `stop_reason` is set only when `action` is `STOP` (always
    `StopReason.ITERATION_CAP_EXCEEDED` — the only reason this gate ever
    produces). `granted_extension_iterations` is set only when `action` is
    `EXTEND`, carrying the number of additional iterations this grant adds
    (`policy.extension_iterations`, read off the policy — never a literal)
    so a caller can narrate the grant without re-reading the policy itself.
    """

    action: IterationGateAction
    stop_reason: StopReason | None = None
    granted_extension_iterations: int | None = None


def effective_iteration_cap(*, extensions_granted: int, policy: TerminationPolicy) -> int:
    """The iteration count a run may reach *right now*, given how many
    extensions have already been granted: `max_iterations` plus one
    `extension_iterations` block per grant so far. With
    `OPTIMIZE_PRODUCT_TERMINATION_POLICY` (`max_iterations=6`,
    `extension_iterations=2`) this is `6` before any grant and `8` after one
    — never a literal `6`/`8` written here; both fall out of the policy
    values arithmetically.
    """
    return policy.max_iterations + extensions_granted * policy.extension_iterations


def evaluate_iteration_gate(
    *,
    iteration_count: int,
    extensions_granted: int,
    policy: TerminationPolicy,
) -> IterationGate:
    """Decide whether the run may make its next `LLMService.complete()` call
    outright, needs a newly-granted extension to make it, or must stop.

    Called once at the top of every iteration, after `evaluate_checkpoint`.
    `iteration_count` is the number of `complete()` calls already made this
    run; this call is asking whether call number `iteration_count + 1` may
    proceed.

    - Below the effective cap (`effective_iteration_cap` given
      `extensions_granted` grants so far) -> `PROCEED`, no change.
    - At or above the effective cap, with an extension still available
      (`extensions_granted < policy.max_extensions`) -> `EXTEND`: the caller
      must record the grant (increment its own `extensions_granted` counter,
      emit the visible `workflow.status` event) *before* proceeding with the
      call this grant is unlocking.
    - At or above the effective cap, with no extension left -> `STOP`,
      `stop_reason=StopReason.ITERATION_CAP_EXCEEDED`.

    This is why "the model proposed `continue`" needs no explicit block
    type: the block vocabulary (`llm/blocks.py`) has `TextBlock` /
    `ToolCallBlock` / `FinalResponse` and nothing else, so a turn that ends
    without a `FinalResponse` *is* the model proposing to continue —
    `WorkflowRunner`'s loop only reaches this gate when it is about to make
    another call anyway, i.e. exactly when that implicit proposal has been
    made.
    """
    cap = effective_iteration_cap(extensions_granted=extensions_granted, policy=policy)
    if iteration_count < cap:
        return IterationGate(action=IterationGateAction.PROCEED)
    if extensions_granted < policy.max_extensions:
        return IterationGate(
            action=IterationGateAction.EXTEND,
            granted_extension_iterations=policy.extension_iterations,
        )
    return IterationGate(
        action=IterationGateAction.STOP,
        stop_reason=StopReason.ITERATION_CAP_EXCEEDED,
    )


def extension_grant_narration(
    *,
    extensions_granted_after_grant: int,
    policy: TerminationPolicy,
) -> str:
    """The `workflow.status` `phase_narration` text for one extension grant
    (ADR-073 decision 2: "Each grant emits a visible `workflow.status`
    event"; `WorkflowStatusPayload`'s own docstring: "there is no separate
    'extension' field; the grant is narrated through this one free-text
    field"). Every number in the sentence is read off `policy` —
    `extension_iterations`, `extensions_granted_after_grant`,
    `policy.max_extensions` — never a literal.
    """
    return (
        f"Continuing past the standard iteration limit: granting "
        f"{policy.extension_iterations} more iteration(s) "
        f"(extension {extensions_granted_after_grant} of {policy.max_extensions})."
    )


__all__ = [
    "IterationGate",
    "IterationGateAction",
    "accumulate_running_seconds",
    "effective_iteration_cap",
    "evaluate_checkpoint",
    "evaluate_iteration_gate",
    "extension_grant_narration",
    "running_seconds_column_value",
]
