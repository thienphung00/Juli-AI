"""Termination-policy evaluation — issue #1120 / AGT-W3A (ADR-073 decision 2).

Pure-unit scenario suite against `FakeLLMService` (ADR-071 decision 6) plus
direct unit tests of `runner/termination.py`'s pure functions — no database,
no network, no real sleeping (every wall-clock test uses a controllable
fake clock).

Covers every #1120 acceptance criterion: the iteration soft cap and
auto-granted extensions reaching the hard cap, exactly one `workflow.status`
event per grant, the paused wall-clock accumulator, checkpoint cancellation
that never interrupts an in-flight tool call, cancellation and timeout
sharing one checkpoint function, the reachable `stop_reason` enumeration,
and `approval_timeout_h`'s policy value / status-mapping pair.

Also covers issue #1120's two inherited findings (from #1119's and #1118's
reviews, both recorded on this issue):

1. **Every termination number must be read, never hard-coded.**
   `TestNoHardcodedPolicyLiterals` AST-scans `termination.py` for the
   literals `6`/`8`/`300`/`4`; `TestPolicyValuesArePinnedToTheirSource` and
   `TestIterationExtensionArithmeticIsPinnedToItsSource` construct playbooks
   with deliberately unusual policy values and assert the runner's observed
   behaviour changes accordingly — the thing scripting boundary scenarios
   alone cannot catch (a scenario that happens to reach iteration 6 says
   nothing about whether `6` came from the policy or a literal).
2. **The `running_seconds_elapsed` rounding rule.** `TestRunningSecondsRounding`
   and `TestWallClockPausesAcrossWaitingApproval` state and test this
   module's decision: the `RunState` float is authoritative for every
   termination decision, the `workflow_runs` integer column is a lossy
   mirror recomputed fresh (round-half-up) at write time rather than
   accumulated independently — bounding its drift from the float to under
   half a second at any point in a run's lifetime, across the maximum 8
   iterations a run can take.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from typing import Any

import pytest

from juli_backend.services.agent.events import EventSink, InMemoryEventSink, WorkflowStatusEvent
from juli_backend.services.agent.llm import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    AssistantTurn,
    FinalResponse,
    LLMConfig,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep, TerminationPolicy
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.core import RunResult, WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.status import StopReason, WorkflowRunStatus, status_for
from juli_backend.services.agent.runner.termination import (
    IterationGateAction,
    accumulate_running_seconds,
    effective_iteration_cap,
    evaluate_checkpoint,
    evaluate_iteration_gate,
    extension_grant_narration,
    running_seconds_column_value,
)
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/services/agent/runner/core.py"
TERMINATION_MODULE_PATH = (
    REPO_ROOT / "backend/src/juli_backend/services/agent/runner/termination.py"
)


# --- shared fixtures / doubles ------------------------------------------------


class _InMemoryConversationStore:
    """A minimal `ConversationStore` double — no database, matching the
    protocol shape `test_agent_runner_core.py`'s own stub uses."""

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, RunState] = {}

    def seed(self, workflow_run_id: uuid.UUID, state: RunState | None = None) -> None:
        self._store[workflow_run_id] = state if state is not None else RunState()

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        return self._store[workflow_run_id]

    async def persist(self, workflow_run_id: uuid.UUID, state: RunState) -> None:
        self._store[workflow_run_id] = state

    def state_for(self, workflow_run_id: uuid.UUID) -> RunState:
        return self._store[workflow_run_id]


class _SpyToolExecutor:
    """Records every `execute` call it receives; returns a fixed result."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(self, *, tool_name: str, params: Any) -> dict[str, Any]:
        self.calls.append((tool_name, params))
        return dict(self._result)


class _CancelFlippingToolExecutor:
    """A `ToolExecutor` whose `execute` flips a shared cancellation flag as
    a *side effect of the call itself* — simulating `cancel_requested`
    arriving while a write is "in progress". This runner has no concurrency
    of its own (`execute` is a plain synchronous call), so the only way to
    prove "an in-flight write is never interrupted" is to show the call
    that flips the flag always completes and its result is always recorded
    — never that the call itself is preempted mid-execution.
    """

    def __init__(
        self, cancel_flag: dict[str, bool], *, result: dict[str, Any] | None = None
    ) -> None:
        self._cancel_flag = cancel_flag
        self._result = result if result is not None else {"ok": True}
        self.calls: list[str] = []

    def execute(self, *, tool_name: str, params: Any) -> dict[str, Any]:
        self.calls.append(tool_name)
        self._cancel_flag["requested"] = True
        return dict(self._result)


class _SteppingClock:
    """A controllable fake clock: each call returns the current value, then
    advances it by `step`. No real sleeping anywhere — a wall-clock test
    that trips ADR-073's 300s budget does so in microseconds of test time.
    """

    def __init__(self, *, step: float, start: float = 0.0) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


class _ManualClock:
    """A fake clock advanced only by explicit `.advance()` calls — stands
    in for "real wall-clock time" in `TestWallClockPausesAcrossWaitingApproval`,
    independent of the running-time accumulator it is being compared
    against. Not `WorkflowRunner`-injectable (no `__call__`); that seam is
    `_SteppingClock`, used everywhere else in this file.
    """

    def __init__(self) -> None:
        self.value: float = 0.0

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _step(tool_name: str, *, policy: ToolPolicy = ToolPolicy.AUTO) -> PlaybookStep:
    return PlaybookStep(
        step_id=tool_name, intent=f"Call {tool_name}.", tools=(tool_name,), policy=policy
    )


def _minimal_playbook(
    steps: tuple[PlaybookStep, ...],
    *,
    policy: TerminationPolicy = OPTIMIZE_PRODUCT_TERMINATION_POLICY,
) -> Playbook:
    """A `Playbook` sharing the real `optimize_product_2` workflow_key/version
    (so `compose()` still resolves a real prose binding) but with a
    caller-chosen step list and termination policy — the policy override is
    what lets the "pinned to source" tests prove the runner reads whatever
    policy it is given, not a value baked into `core.py`/`termination.py`.
    """
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=steps,
        termination_policy=policy,
    )


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


def _llm(*turns: AssistantTurn) -> FakeLLMService:
    return FakeLLMService(script=list(turns))


def _runner(
    *,
    llm_service: FakeLLMService,
    tool_executor: Any,
    event_sink: EventSink,
    conversation_store: _InMemoryConversationStore,
    playbook: Playbook,
    registry: ToolRegistry,
    clock: Any = None,
    cancel_check: Any = None,
) -> WorkflowRunner:
    return WorkflowRunner(
        llm_service=llm_service,
        tool_executor=tool_executor,
        event_sink=event_sink,
        conversation_store=conversation_store,
        registry=registry,
        playbook=playbook,
        clock=clock,
        cancel_check=cancel_check,
    )


# =============================================================================
# Pure `termination.py` unit tests
# =============================================================================


# --- AC: every termination number is read off TerminationPolicy ---------------


class TestNoHardcodedPolicyLiterals:
    """ADR-073 decision 2 architect lock / issue #1120's first inherited
    finding: "Termination values are READ off OPTIMIZE_PRODUCT_TERMINATION_POLICY.
    The runner never defines its own constants; a literal 6 or 300 in
    runner code is a defect." AST-scans the *numeric constants actually
    parsed* out of `termination.py` **and `core.py`** — not a text grep —
    so a docstring mentioning "300s" never false-triggers, and no amount of
    rewording the source can hide a real `ast.Constant(6)` from this check.

    Both modules are scanned: `core.py` is where a hard-coded policy number
    is most tempting to introduce (a developer reaching for a literal while
    writing loop control flow), and it is exactly where #1119's review
    introduced one that no scripted scenario caught (issue #1120's first
    inherited finding). Scanning only `termination.py` would have left that
    exact regression class covered by behavioural scenarios alone — this
    guard makes it two-layered in practice, not just in description.
    """

    _FORBIDDEN_INT_LITERALS = frozenset({6, 8, 300, 4})
    _SCANNED_MODULES = (TERMINATION_MODULE_PATH, CORE_MODULE_PATH)

    def test_no_scanned_module_contains_forbidden_policy_literals(self):
        for path in self._SCANNED_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, int)
                and not isinstance(node.value, bool)
                and node.value in self._FORBIDDEN_INT_LITERALS
            }
            assert found == set(), (
                f"{path.name} contains forbidden hard-coded policy literal(s) {sorted(found)} "
                "— every termination number must be read off TerminationPolicy, never "
                "redefined in runner code."
            )


class TestSharedCheckpointMechanism:
    """AC: "Cancellation and timeout are evaluated through the same
    checkpoint mechanism — assert both paths call one shared checkpoint
    function rather than duplicating the check."."""

    def test_core_module_calls_the_shared_checkpoint_function_at_exactly_two_sites(self):
        tree = ast.parse(CORE_MODULE_PATH.read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "evaluate_checkpoint"
        ]
        assert len(calls) == 2, (
            "core.py must call termination.evaluate_checkpoint exactly twice — once at the "
            "top of each iteration, once immediately before each tool execution — never a "
            "second, separately-written cancellation/wall-clock comparison."
        )

    def test_core_module_never_reads_wall_clock_timeout_s_directly(self):
        # If core.py ever compared state.running_seconds_elapsed against
        # policy.wall_clock_timeout_s itself, that would be exactly the
        # duplicated-check regression the acceptance criterion rules out.
        # AST-based (an `ast.Attribute` access), not a text search, so a
        # comment/docstring mentioning the field name never false-triggers.
        tree = ast.parse(CORE_MODULE_PATH.read_text(encoding="utf-8"))
        attribute_accesses = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert "wall_clock_timeout_s" not in attribute_accesses


class TestCheckpointFunction:
    def test_neither_cancellation_nor_timeout_returns_none(self):
        assert (
            evaluate_checkpoint(
                cancel_requested=False,
                running_seconds_elapsed=0.0,
                policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
            )
            is None
        )

    def test_cancellation_takes_priority_over_a_simultaneous_wall_clock_timeout(self):
        reason = evaluate_checkpoint(
            cancel_requested=True,
            running_seconds_elapsed=float(OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s),
            policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
        )
        assert reason == StopReason.CANCELLED_BY_SELLER

    def test_wall_clock_timeout_fires_at_exactly_the_threshold(self):
        threshold = float(OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s)
        reason = evaluate_checkpoint(
            cancel_requested=False,
            running_seconds_elapsed=threshold,
            policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
        )
        assert reason == StopReason.WALL_CLOCK_TIMEOUT

    def test_wall_clock_timeout_does_not_fire_just_under_the_threshold(self):
        just_under = float(OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s) - 0.4  # 299.6s
        reason = evaluate_checkpoint(
            cancel_requested=False,
            running_seconds_elapsed=just_under,
            policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
        )
        assert reason is None


# --- Rounding decision (issue #1120's second inherited finding) --------------


class TestRunningSecondsRounding:
    """Decision, stated and tested: `RunState.running_seconds_elapsed`
    (the float) is authoritative for every termination decision.
    `workflow_runs.running_seconds_elapsed` (the `Integer` column #1117
    shipped) is a round-half-up mirror computed fresh from the float —
    never accumulated as its own running integer total — so its drift from
    the float is bounded to under one rounding step (0.5s) at any instant,
    regardless of how many pause/resume cycles or iterations a run takes.
    """

    def test_round_half_up_basic_cases(self):
        assert running_seconds_column_value(0.0) == 0
        assert running_seconds_column_value(299.4) == 299
        assert running_seconds_column_value(299.5) == 300  # half rounds up
        assert running_seconds_column_value(300.0) == 300
        assert running_seconds_column_value(0.49) == 0
        assert running_seconds_column_value(0.5) == 1

    def test_rejects_negative_input(self):
        with pytest.raises(ValueError):
            running_seconds_column_value(-0.1)

    def test_column_mirror_drift_never_exceeds_half_a_second_across_the_maximum_eight_iterations(
        self,
    ):
        # 8 = OPTIMIZE_PRODUCT_TERMINATION_POLICY's hard cap
        # (max_iterations + max_extensions * extension_iterations) — the
        # most iterations, and therefore the most accumulation calls, any
        # one run can make.
        deltas = [37.51, 22.33, 41.17, 19.98, 28.71, 33.29, 44.44, 12.06]
        elapsed = 0.0
        for delta in deltas:
            elapsed = accumulate_running_seconds(elapsed, delta_seconds=delta)
            mirrored = running_seconds_column_value(elapsed)
            assert abs(mirrored - elapsed) < 0.5, (
                f"column mirror {mirrored} drifted >= 0.5s from authoritative float {elapsed}"
            )

    def test_accumulate_rejects_negative_delta(self):
        with pytest.raises(ValueError):
            accumulate_running_seconds(10.0, delta_seconds=-1.0)

    def test_termination_is_decided_from_the_float_not_the_rounded_mirror(self):
        """At 299.6s the float says "keep going"; the rounded column
        mirror (300) would wrongly say "stop" if a caller mistakenly
        consulted it instead — this is why `evaluate_checkpoint` only ever
        takes the float (see `TestCheckpointFunction` above); this test
        pins down *why* that choice matters."""
        policy = OPTIMIZE_PRODUCT_TERMINATION_POLICY
        almost = float(policy.wall_clock_timeout_s) - 0.4  # 299.6s
        assert running_seconds_column_value(almost) == policy.wall_clock_timeout_s  # rounds to 300
        assert (
            evaluate_checkpoint(
                cancel_requested=False, running_seconds_elapsed=almost, policy=policy
            )
            is None
        )  # the float itself says "not yet"


class TestWallClockPausesAcrossWaitingApproval:
    """AC: "The wall-clock accumulator excludes a waiting_approval span —
    assert this using a fake/controllable clock: advance the clock during
    a simulated waiting_approval pause and prove the running-time
    accumulator does not advance, then resume and prove it advances again."

    There is no `pause()`/`resume()` API on this module (see
    `termination.py`'s module docstring): the clock "pauses" simply
    because nothing calls `accumulate_running_seconds` during a
    `waiting_approval` span. This test proves that directly: a large
    amount of *wall-clock* time (represented by the fake clock advancing)
    passes during the simulated pause, but the running-time accumulator —
    which is never told about that gap — is unaffected.
    """

    def test_accumulator_ignores_a_large_gap_while_paused_then_resumes_from_where_it_left_off(self):
        wall_clock = _ManualClock()  # represents real elapsed time, running + paused alike

        # --- running phase: two 10s iterations, each accumulated ---
        elapsed = 0.0
        wall_clock.advance(10.0)
        elapsed = accumulate_running_seconds(elapsed, delta_seconds=10.0)
        wall_clock.advance(10.0)
        elapsed = accumulate_running_seconds(elapsed, delta_seconds=10.0)
        assert elapsed == 20.0

        # --- simulated waiting_approval pause: 10,000s of wall-clock time
        # passes, but nothing calls accumulate_running_seconds while paused
        # (that omission IS the pause mechanism, ADR-073 decision 2) ---
        wall_clock.advance(10_000.0)
        assert elapsed == 20.0  # unchanged: the pause contributed nothing

        # --- resume: running-time accumulation continues from 20.0 ---
        wall_clock.advance(15.0)
        elapsed = accumulate_running_seconds(elapsed, delta_seconds=15.0)
        assert elapsed == 35.0  # 20.0 (pre-pause) + 15.0 (post-resume); the 10,000s never counted
        assert wall_clock.value == 10_035.0  # real elapsed time was far larger than running time


class TestWallClockOvershootBound:
    """Meta review follow-up on #1120: `state.running_seconds_elapsed` is
    only updated once, after a full iteration completes — the pre-tool
    checkpoint within that iteration reads a stale, pre-iteration value, so
    an iteration already in progress can run past `wall_clock_timeout_s`
    before the next checkpoint notices. Review's framing ("unbounded") was
    too strong: one iteration's overshoot is bounded by
    `LLMConfig.request_timeout_seconds` plus the sum of the `ToolSpec.timeout_seconds`
    of every tool call that iteration's turn dispatches — this test computes
    that bound from the *real* `LLMConfig` default and the *real* Optimize
    Product tool registry (never a value copied by hand), so a future change
    to any tool's declared timeout — or the LLM default — fails this test
    instead of silently making `termination.py`'s documented figure stale.
    """

    def test_the_documented_worst_case_bound_matches_the_real_registry_and_llm_default(self):
        assert LLMConfig().request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
        assert DEFAULT_REQUEST_TIMEOUT_SECONDS == 30.0

        registry = _full_registry()
        tool_names = {
            tool_name for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps for tool_name in step.tools
        }
        total_tool_timeout_seconds = sum(
            registry.get(tool_name).timeout_seconds for tool_name in tool_names
        )

        # Every registered Optimize Product tool, summed -- the worst case
        # is a single turn whose blocks call all six.
        assert total_tool_timeout_seconds == 105

        per_iteration_overshoot_ceiling = (
            DEFAULT_REQUEST_TIMEOUT_SECONDS + total_tool_timeout_seconds
        )
        assert per_iteration_overshoot_ceiling == 135.0

        worst_case_total_duration = (
            OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s
            + per_iteration_overshoot_ceiling
        )
        assert worst_case_total_duration == 435.0  # 300s budget + 135s worst-case overshoot


# --- Iteration gate / extension arithmetic ------------------------------------


class TestIterationGatePureFunction:
    _POLICY = TerminationPolicy(
        max_iterations=3,
        max_extensions=2,
        extension_iterations=5,
        wall_clock_timeout_s=999,
        approval_timeout_h=1,
        required_steps=("x",),
    )

    def test_effective_cap_reads_policy_values(self):
        assert effective_iteration_cap(extensions_granted=0, policy=self._POLICY) == 3
        assert effective_iteration_cap(extensions_granted=1, policy=self._POLICY) == 8
        assert effective_iteration_cap(extensions_granted=2, policy=self._POLICY) == 13

    def test_gate_proceeds_below_the_effective_cap(self):
        gate = evaluate_iteration_gate(iteration_count=0, extensions_granted=0, policy=self._POLICY)
        assert gate.action is IterationGateAction.PROCEED
        assert gate.stop_reason is None
        assert gate.granted_extension_iterations is None

    def test_gate_extends_at_the_cap_with_an_extension_available(self):
        gate = evaluate_iteration_gate(iteration_count=3, extensions_granted=0, policy=self._POLICY)
        assert gate.action is IterationGateAction.EXTEND
        assert gate.granted_extension_iterations == 5
        assert gate.stop_reason is None

    def test_gate_stops_at_the_cap_once_extensions_are_exhausted(self):
        gate = evaluate_iteration_gate(
            iteration_count=13, extensions_granted=2, policy=self._POLICY
        )
        assert gate.action is IterationGateAction.STOP
        assert gate.stop_reason is StopReason.ITERATION_CAP_EXCEEDED
        assert gate.granted_extension_iterations is None


class TestExtensionGrantNarration:
    def test_narration_reads_every_number_from_the_policy_not_a_literal(self):
        policy = TerminationPolicy(
            max_iterations=3,
            max_extensions=5,
            extension_iterations=9,
            wall_clock_timeout_s=10,
            approval_timeout_h=1,
            required_steps=("x",),
        )
        text = extension_grant_narration(extensions_granted_after_grant=2, policy=policy)
        assert "9" in text  # extension_iterations
        assert "2 of 5" in text  # extensions_granted_after_grant of max_extensions


# =============================================================================
# End-to-end `WorkflowRunner` scenarios
# =============================================================================


# --- AC: soft cap + auto-granted extension reaching hard cap 8 ---------------


class TestIterationCapAndExtensions:
    async def test_soft_cap_alone_with_no_extension_available_stops_exactly_at_max_iterations(
        self,
    ):
        """Genuine boundary: reaches the real soft cap of 6 (sourced from
        OPTIMIZE_PRODUCT_TERMINATION_POLICY, extensions forced off) with no
        extension possible."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        policy = TerminationPolicy(
            max_iterations=OPTIMIZE_PRODUCT_TERMINATION_POLICY.max_iterations,
            max_extensions=0,
            extension_iterations=OPTIMIZE_PRODUCT_TERMINATION_POLICY.extension_iterations,
            wall_clock_timeout_s=OPTIMIZE_PRODUCT_TERMINATION_POLICY.wall_clock_timeout_s,
            approval_timeout_h=OPTIMIZE_PRODUCT_TERMINATION_POLICY.approval_timeout_h,
            required_steps=OPTIMIZE_PRODUCT_TERMINATION_POLICY.required_steps,
        )
        playbook = _minimal_playbook((_step("get_product_information"),), policy=policy)
        llm = _llm(*(_turn(TextBlock(text=f"still working {i}")) for i in range(6)))

        runner = _runner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.ITERATION_CAP_EXCEEDED
        assert result.status == WorkflowRunStatus.TIMED_OUT
        assert result.iteration_count == 6
        assert len(llm.recorded_calls) == 6  # never asked for a 7th
        assert [e for e in sink.events if e.event_type == "workflow.status"] == []
        assert store.state_for(run_id).extensions_granted == 0

    async def test_model_proposed_continue_at_soft_cap_grants_one_extension_reaching_hard_cap_eight(
        self,
    ):
        """Genuine boundary: the real policy's soft cap (6), one extension
        of 2, hard cap 8, then a refused 9th attempt (ADR-073 decision 2 /
        the AC's exact scenario)."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))
        llm = _llm(*(_turn(TextBlock(text=f"still working {i}")) for i in range(8)))

        runner = _runner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.ITERATION_CAP_EXCEEDED
        assert result.status == WorkflowRunStatus.TIMED_OUT
        assert result.iteration_count == 8
        assert len(llm.recorded_calls) == 8  # the 9th call was refused, never made
        assert store.state_for(run_id).extensions_granted == 1

        status_events = [e for e in sink.events if e.event_type == "workflow.status"]
        assert len(status_events) == 1  # exactly one grant -> exactly one event
        assert isinstance(status_events[0], WorkflowStatusEvent)
        assert "2" in status_events[0].payload.phase_narration  # extension_iterations
        assert "1 of 1" in status_events[0].payload.phase_narration

    async def test_zero_workflow_status_events_when_the_run_finishes_well_under_the_soft_cap(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        playbook = _minimal_playbook((_step("get_product_information"),))
        llm = _llm(_turn(FinalResponse(content="Done well under the cap.")))

        runner = _runner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.FINAL_RESPONSE
        assert [e for e in sink.events if e.event_type == "workflow.status"] == []


class TestPolicyValuesArePinnedToTheirSource:
    """Issue #1120's first inherited finding: prove `max_iterations` and
    `wall_clock_timeout_s` are READ off the policy, not defaulted to 6/300,
    by giving the runner deliberately unusual values and watching observed
    behaviour follow them."""

    async def test_an_unusual_max_iterations_of_three_caps_the_run_there_not_at_six(self):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        policy = TerminationPolicy(
            max_iterations=3,
            max_extensions=0,
            extension_iterations=1,
            wall_clock_timeout_s=999_999,
            approval_timeout_h=1,
            required_steps=("x",),
        )
        playbook = _minimal_playbook((_step("get_product_information"),), policy=policy)
        llm = _llm(*(_turn(TextBlock(text=f"turn {i}")) for i in range(3)))

        runner = _runner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.ITERATION_CAP_EXCEEDED
        assert result.iteration_count == 3
        assert len(llm.recorded_calls) == 3  # a hardcoded 6 would have consumed a 4th turn

    async def test_an_unusual_wall_clock_timeout_of_five_seconds_trips_there_not_at_three_hundred(
        self,
    ):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        policy = TerminationPolicy(
            max_iterations=999_999,
            max_extensions=0,
            extension_iterations=1,
            wall_clock_timeout_s=5,
            approval_timeout_h=1,
            required_steps=("x",),
        )
        playbook = _minimal_playbook((_step("get_product_information"),), policy=policy)
        llm = _llm(*(_turn(TextBlock(text=f"turn {i}")) for i in range(2)))
        clock = _SteppingClock(step=3.0)  # 3s/iteration: trips at 6s (>= 5s), after 2 turns

        runner = _runner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
            clock=clock,
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.WALL_CLOCK_TIMEOUT
        assert result.iteration_count == 2  # a hardcoded 300 would never have tripped on 6s
        assert len(llm.recorded_calls) == 2


class TestIterationExtensionArithmeticIsPinnedToItsSource:
    async def test_unusual_max_extensions_and_extension_iterations_change_the_hard_cap(self):
        """max_iterations=3, max_extensions=2, extension_iterations=2 ->
        two grants, hard cap 3 + 2*2 = 7 -- deliberately not 6 or 8, so this
        cannot be mistaken for the real policy's numbers by coincidence."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        policy = TerminationPolicy(
            max_iterations=3,
            max_extensions=2,
            extension_iterations=2,
            wall_clock_timeout_s=999_999,
            approval_timeout_h=1,
            required_steps=("x",),
        )
        playbook = _minimal_playbook((_step("get_product_information"),), policy=policy)
        llm = _llm(*(_turn(TextBlock(text=f"turn {i}")) for i in range(7)))

        runner = _runner(
            llm_service=llm,
            tool_executor=_SpyToolExecutor(),
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert result.stop_reason == StopReason.ITERATION_CAP_EXCEEDED
        assert result.iteration_count == 7
        assert len(llm.recorded_calls) == 7
        assert store.state_for(run_id).extensions_granted == 2
        assert len([e for e in sink.events if e.event_type == "workflow.status"]) == 2


# --- AC: checkpoint cancellation never interrupts an in-flight write ---------


class TestCheckpointCancellationNeverInterruptsAnInFlightWrite:
    async def test_a_call_that_flips_the_flag_still_completes_stop_honored_next_top_of_iteration(
        self,
    ):
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        sink = InMemoryEventSink()
        cancel_flag = {"requested": False}
        executor = _CancelFlippingToolExecutor(cancel_flag)
        playbook = _minimal_playbook((_step("get_product_information"),))
        llm = _llm(
            _turn(ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})),
            _turn(FinalResponse(content="should never be reached")),
        )

        runner = _runner(
            llm_service=llm,
            tool_executor=executor,
            event_sink=sink,
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
            cancel_check=lambda: cancel_flag["requested"],
        )
        result = await runner.run(run_id, product_ref="prod-1")

        # The call that flipped the flag ran to completion and was recorded
        # (never interrupted mid-write) -- cancellation is honored only at
        # the next checkpoint, before the next unit of work starts.
        assert executor.calls == ["get_product_information"]
        assert result.stop_reason == StopReason.CANCELLED_BY_SELLER
        assert result.status == WorkflowRunStatus.CANCELLED
        assert len(llm.recorded_calls) == 1  # the 2nd complete() call was never made

        completed = [e for e in sink.events if e.event_type == "tool.completed"]
        assert len(completed) == 1
        assert completed[0].payload.ok is True  # the in-flight write succeeded normally

    async def test_second_tool_call_in_the_same_turn_is_refused_by_the_pre_execution_checkpoint(
        self,
    ):
        """Proves the checkpoint runs "immediately before each tool
        execution" (plural) -- not merely once per iteration -- by putting
        two `ToolCallBlock`s in a single turn and flipping cancellation as
        a side effect of the first."""
        run_id = uuid.uuid4()
        store = _InMemoryConversationStore()
        store.seed(run_id)
        cancel_flag = {"requested": False}
        executor = _CancelFlippingToolExecutor(cancel_flag)
        playbook = _minimal_playbook((_step("get_product_information"), _step("get_seo_keywords")))
        llm = _llm(
            _turn(
                ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={}),
                ToolCallBlock(call_id="c2", tool_name="get_seo_keywords", arguments={}),
            )
        )

        runner = _runner(
            llm_service=llm,
            tool_executor=executor,
            event_sink=InMemoryEventSink(),
            conversation_store=store,
            playbook=playbook,
            registry=_full_registry(),
            cancel_check=lambda: cancel_flag["requested"],
        )
        result = await runner.run(run_id, product_ref="prod-1")

        assert executor.calls == ["get_product_information"]  # c2 never dispatched
        assert result.stop_reason == StopReason.CANCELLED_BY_SELLER
        assert len(llm.recorded_calls) == 1  # stopped within the same turn


# --- AC: approval_timeout_h policy value + confirmation_expired mapping ------


class TestApprovalTimeout:
    """AC: "approval_timeout_h=4 is asserted as a policy value and as the
    correct confirmation_expired -> cancelled status transition function,
    without implementing a live 4-hour wait — the physical timer is W3-B's
    reaper's job, out of scope here." (#1130 owns the live timer; this
    module and this test own only the value and the mapping.)
    """

    def test_approval_timeout_h_is_four_on_the_real_policy(self):
        assert OPTIMIZE_PRODUCT_TERMINATION_POLICY.approval_timeout_h == 4

    def test_confirmation_expired_maps_to_cancelled(self):
        assert status_for(StopReason.CONFIRMATION_EXPIRED) == WorkflowRunStatus.CANCELLED


# --- AC: every reachable stop_reason has exactly one dedicated scenario -----


async def _final_response_scenario() -> RunResult:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    playbook = _minimal_playbook((_step("get_product_information"),))
    llm = _llm(_turn(FinalResponse(content="All good.")))
    runner = _runner(
        llm_service=llm,
        tool_executor=_SpyToolExecutor(),
        event_sink=InMemoryEventSink(),
        conversation_store=store,
        playbook=playbook,
        registry=_full_registry(),
    )
    return await runner.run(run_id, product_ref="prod-1")


async def _tool_error_unrecoverable_scenario() -> RunResult:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    playbook = _minimal_playbook((_step("update_product_price", policy=ToolPolicy.CONFIRM),))
    llm = _llm(
        _turn(
            ToolCallBlock(
                call_id="c1", tool_name="update_product_price", arguments={"skus": "nope"}
            )
        ),
        _turn(
            ToolCallBlock(
                call_id="c2", tool_name="update_product_price", arguments={"skus": "nope-2"}
            )
        ),
    )
    runner = _runner(
        llm_service=llm,
        tool_executor=_SpyToolExecutor(),
        event_sink=InMemoryEventSink(),
        conversation_store=store,
        playbook=playbook,
        registry=_full_registry(),
    )
    return await runner.run(run_id, product_ref="prod-1")


async def _cancelled_by_seller_scenario() -> RunResult:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    cancel_flag = {"requested": False}
    executor = _CancelFlippingToolExecutor(cancel_flag)
    playbook = _minimal_playbook((_step("get_product_information"),))
    llm = _llm(
        _turn(ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})),
        _turn(FinalResponse(content="unreachable")),
    )
    runner = _runner(
        llm_service=llm,
        tool_executor=executor,
        event_sink=InMemoryEventSink(),
        conversation_store=store,
        playbook=playbook,
        registry=_full_registry(),
        cancel_check=lambda: cancel_flag["requested"],
    )
    return await runner.run(run_id, product_ref="prod-1")


async def _iteration_cap_exceeded_scenario() -> RunResult:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    playbook = _minimal_playbook((_step("get_product_information"),))
    llm = _llm(*(_turn(TextBlock(text=f"turn {i}")) for i in range(8)))
    runner = _runner(
        llm_service=llm,
        tool_executor=_SpyToolExecutor(),
        event_sink=InMemoryEventSink(),
        conversation_store=store,
        playbook=playbook,
        registry=_full_registry(),
    )
    return await runner.run(run_id, product_ref="prod-1")


async def _wall_clock_timeout_scenario() -> RunResult:
    run_id = uuid.uuid4()
    store = _InMemoryConversationStore()
    store.seed(run_id)
    playbook = _minimal_playbook((_step("get_product_information"),))
    llm = _llm(*(_turn(TextBlock(text=f"turn {i}")) for i in range(3)))
    clock = _SteppingClock(step=100.0)  # 3 * 100s == the real 300s budget, exactly
    runner = _runner(
        llm_service=llm,
        tool_executor=_SpyToolExecutor(),
        event_sink=InMemoryEventSink(),
        conversation_store=store,
        playbook=playbook,
        registry=_full_registry(),
        clock=clock,
    )
    return await runner.run(run_id, product_ref="prod-1")


# The stop_reasons this slice's code (core.py + termination.py) can actually
# produce, given today's worktree — #1121 (ledger), #1122 (concurrency), and
# #1123 (pause/resume) are all later slices this issue explicitly does not
# implement, so their stop reasons are not yet reachable by any code this
# module ships. `llm_error` likewise has no producer in this slice (no
# LLMService.complete() error-translation exists yet). See core.py's module
# docstring, "What this slice still deliberately does not do".
_REACHABLE_BY_THIS_SLICE: frozenset[StopReason] = frozenset(
    {
        StopReason.FINAL_RESPONSE,
        StopReason.TOOL_ERROR_UNRECOVERABLE,
        StopReason.CANCELLED_BY_SELLER,
        StopReason.ITERATION_CAP_EXCEEDED,
        StopReason.WALL_CLOCK_TIMEOUT,
    }
)

_DEFERRED_TO_LATER_SLICES: frozenset[StopReason] = frozenset(
    {
        StopReason.CONFIRMATION_DECLINED,
        StopReason.PAUSED_FOR_CONFIRMATION,
        StopReason.CONFIRMATION_EXPIRED,
        StopReason.CONCURRENCY_CONFLICT,
        StopReason.LLM_ERROR,
    }
)

# Reserved, never producible by any W3-A code (ADR-073 decision 5 / the
# ADR-074 amendment) — explicitly excluded from any scenario in this suite.
_RESERVED_UNREACHABLE: frozenset[StopReason] = frozenset(
    {StopReason.WORKER_LOST, StopReason.OUTPUT_VALIDATION_FAILED}
)


class TestStopReasonReachability:
    def test_the_three_sets_partition_every_stop_reason_exactly_once(self):
        all_reasons = frozenset(StopReason)
        union = _REACHABLE_BY_THIS_SLICE | _DEFERRED_TO_LATER_SLICES | _RESERVED_UNREACHABLE
        assert union == all_reasons, f"unaccounted-for StopReason members: {all_reasons - union}"
        assert not (_REACHABLE_BY_THIS_SLICE & _DEFERRED_TO_LATER_SLICES)
        assert not (_REACHABLE_BY_THIS_SLICE & _RESERVED_UNREACHABLE)
        assert not (_DEFERRED_TO_LATER_SLICES & _RESERVED_UNREACHABLE)

    def test_worker_lost_and_output_validation_failed_are_never_referenced_in_production_code(
        self,
    ):
        for path in (CORE_MODULE_PATH, TERMINATION_MODULE_PATH):
            source = path.read_text(encoding="utf-8")
            assert "WORKER_LOST" not in source, f"{path} references the reaper-only stop_reason"
            assert "OUTPUT_VALIDATION_FAILED" not in source, (
                f"{path} references the P7-reserved stop_reason"
            )

    async def test_every_reachable_stop_reason_has_a_dedicated_scenario_reaching_it(self):
        reached: dict[StopReason, RunResult] = {
            StopReason.FINAL_RESPONSE: await _final_response_scenario(),
            StopReason.TOOL_ERROR_UNRECOVERABLE: await _tool_error_unrecoverable_scenario(),
            StopReason.CANCELLED_BY_SELLER: await _cancelled_by_seller_scenario(),
            StopReason.ITERATION_CAP_EXCEEDED: await _iteration_cap_exceeded_scenario(),
            StopReason.WALL_CLOCK_TIMEOUT: await _wall_clock_timeout_scenario(),
        }

        # Every scenario actually produced the stop_reason it was scripted for.
        for expected_reason, result in reached.items():
            assert result.stop_reason == expected_reason

        # And the enumeration is exact: nothing reachable is missing a
        # scenario, and nothing scripted here reaches outside the reachable set.
        assert {result.stop_reason for result in reached.values()} == _REACHABLE_BY_THIS_SLICE
        assert set(reached.keys()) == _REACHABLE_BY_THIS_SLICE
