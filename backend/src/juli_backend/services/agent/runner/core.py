"""`WorkflowRunner` — the agent execution-loop core (ADR-073 decision 1,
issue #1119 / AGT-W3A).

Constructor-injected with exactly four protocols — `LLMService`
(`llm/service.py`), `ToolExecutor` (`tool_executor.py`, this slice),
`EventSink` (`events/sink.py`, #1125/W3B — imported, never redefined here),
`ConversationStore` (`conversation_store.py`, #1118) — plus two plain,
non-protocol collaborators every run needs regardless of injection: the real
`ToolRegistry` (`tools/registry.py`) and the active `Playbook`
(`playbooks/base.py`). The registry and playbook are what make "one
artifact, three consumers" (ADR-072 decision 2) hold at the runner boundary:
the same `Playbook` that names the tools the model is told about is the one
`_dispatch_tool_call` checks a `ToolCallBlock` against, so the two can never
disagree.

**Block dispatch (ADR-073 decision 1).**

- `TextBlock` -> emit `assistant.text`, append one conversation message.
- `ToolCallBlock` -> resolve against the registry, then the active
  playbook's allowlist (two distinct, distinguishable refusal cases — see
  `_dispatch_tool_call`), then validate `arguments` against the target
  `ToolSpec.input_model`. Only a call that survives all three ever reaches
  `ToolExecutor.execute`. The raw result is run through
  `guard_inbound_tool_result` before it is ever appended to the
  conversation — the model never sees an unsanitized tool result.
- `FinalResponse` -> run through `guard_outbound_agent_output` *before*
  anything about the response is recorded. A banned-pattern hit raises
  `BannedPatternGuardFailure` straight out of `run()` — no completion event,
  no `stop_reason=final_response`, nothing written to the conversation for
  that block. Recovery (repair retry, rules-template fallback) is
  explicitly out of scope here (issue #994's P7 deferral); this module only
  ever calls the guard and lets a hit propagate.

**Self-correction (ADR-073 decision 6 test-strategy item).** A `ToolCallBlock`
whose `arguments` fail `input_model` validation is refused and an error is
returned to the model for exactly one corrected retry. Two *consecutive*
malformed-params refusals end the run with `stop_reason=tool_error_unrecoverable`
rather than requesting a third attempt — any other block (text, a
successfully-dispatched tool call, or a playbook/registry refusal, which is
a distinct failure class from a malformed-params one) resets the streak.

**Termination (ADR-073 decision 2, issue #1120 / `runner/termination.py`).**
Every numeric termination value is read off `self._playbook.termination_policy`
— never a literal in this module. `evaluate_checkpoint` (cancellation +
paused wall clock, one shared function) runs at the top of every iteration
and immediately before every `ToolCallBlock` dispatch; a call already in
flight always completes, since a checkpoint only ever gates the *next* unit
of work. `evaluate_iteration_gate` runs at the top of every iteration, after
the checkpoint, to grant a soft-cap extension (emitting one visible
`workflow.status` event per grant) or stop with `iteration_cap_exceeded`.
`state.running_seconds_elapsed` (the float `RunState` field #1118 shipped)
is accumulated once per completed iteration via
`termination.accumulate_running_seconds`, using this module's own injected
`clock` to measure the iteration's running-time delta — see
`termination.py`'s module docstring for the rounding decision governing the
`workflow_runs.running_seconds_elapsed` integer mirror, which this module
does not itself write (no direct database access here, same as
`prompt_version`/`prompt_sha256`/`status`).

**What this slice still deliberately does not do (see issue #1119's
"Boundaries", now narrowed by #1120's own boundaries).** No idempotency
ledger / claim-then-execute (#1121); no basis-hash compare-before-write
(#1122); no pause/resume round-trip for a CONFIRM-policy tool (#1123) — a
`ToolCallBlock` naming a CONFIRM tool is still dispatched exactly like an
AUTO one in this slice, once it clears the allowlist and validation checks;
a later slice is what actually pauses the run before invoking the handler,
so `paused_for_confirmation`/`confirmation_declined`/`confirmation_expired`/
`concurrency_conflict` are not produced by any code in this module — see
`tests/unit/test_agent_runner_termination.py` for the explicit reachability
assertion.

**`compose()`/prompt stamping (ADR-072 decision 4).** `compose()`,
`prompt_version()`, and `prompt_sha256()` are called exactly once, at the
top of `run()`, from the injected `Playbook`'s own `workflow_key`/`version`
— never recomputed per iteration. The `RunResult` this returns carries both
values so a caller can stamp them on the `workflow_runs` row; this module
has no direct database access of its own (only `ConversationStore.load`/
`persist`, which touch `state` and nothing else), so writing them to the
row's actual `prompt_version`/`prompt_sha256` columns is a later slice's
job, exactly like `status`/`stop_reason`/`running_seconds_elapsed`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

from pydantic import BaseModel, ValidationError

from juli_backend.services.agent.events import (
    AssistantTextEvent,
    AssistantTextPayload,
    EventSink,
    ToolCompletedEvent,
    ToolCompletedPayload,
    ToolStartedEvent,
    ToolStartedPayload,
    WorkflowCompletedEvent,
    WorkflowCompletedPayload,
    WorkflowFailedEvent,
    WorkflowFailedPayload,
    WorkflowStartedEvent,
    WorkflowStartedPayload,
    WorkflowStatusEvent,
    WorkflowStatusPayload,
)
from juli_backend.services.agent.llm import (
    FinalResponse,
    LLMConfig,
    LLMService,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
)
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.agent.prompts.composer import compose, prompt_sha256, prompt_version
from juli_backend.services.agent.runner.conversation_store import ConversationStore
from juli_backend.services.agent.runner.state import ConversationMessage, RunState
from juli_backend.services.agent.runner.status import StopReason, WorkflowRunStatus, status_for
from juli_backend.services.agent.runner.termination import (
    IterationGateAction,
    accumulate_running_seconds,
    evaluate_checkpoint,
    evaluate_iteration_gate,
    extension_grant_narration,
)
from juli_backend.services.agent.runner.tool_executor import ToolExecutor
from juli_backend.services.agent.sanitize import (
    TranslatedError,
    guard_inbound_tool_result,
    guard_outbound_agent_output,
    to_error_envelope,
)
from juli_backend.services.agent.tools import ToolRegistry, UnknownToolError
from juli_backend.services.execution.types import ExecutionErrorCategory


@dataclass(frozen=True)
class RunResult:
    """What one `WorkflowRunner.run()` call produced.

    Terminal outcomes only reach here through `guard_outbound_agent_output`
    (for `final_response`) or via a `stop_reason` this module itself picked
    for a run it gave up on (self-correction exhausted). `status` is derived
    from `stop_reason` via `status_for` (`status.py`'s total mapping) —
    never guessed independently. `prompt_version`/`prompt_sha256` are the
    values `compose()` produced at the top of this run, identical regardless
    of how many iterations it took to reach a terminal block.
    """

    stop_reason: StopReason
    status: WorkflowRunStatus
    final_response: str | None
    prompt_version: str
    prompt_sha256: str
    iteration_count: int


class _ToolCallOutcome(Enum):
    """Internal-only classification of how `_dispatch_tool_call` resolved a
    single `ToolCallBlock` — drives the self-correction streak in `run()`.
    Never leaves this module."""

    SUCCESS = auto()
    REFUSED = auto()
    MALFORMED = auto()


# Two consecutive malformed-params attempts on a tool call end the run
# (ADR-073 decision 6 / issue #1119 acceptance criteria: "a second malformed
# attempt ... terminates the run rather than requesting a third"). Not a
# policy number read from any Playbook — this is the self-correction rule
# this slice itself owns and implements, distinct from the termination-policy
# values (`max_iterations`, `wall_clock_timeout_s`, ...) that stay #1120's.
_MAX_CONSECUTIVE_MALFORMED_ATTEMPTS = 2


class WorkflowRunner:
    """Owns one agent run's block-dispatch loop while it executes (ADR-073
    decision 1).

    Every collaborator is constructor-injected — no module-level singleton,
    no hidden global. Two independently constructed `WorkflowRunner`
    instances (even against the same registry/playbook) never share
    mutable state; each `run()` call loads its own `RunState` fresh from
    the injected `ConversationStore`.

    `clock` and `cancel_check` are the two termination-policy injection
    seams (issue #1120): `clock` (default `time.monotonic`) measures each
    iteration's running-time delta for the wall-clock accumulator; a test
    passes a controllable fake so no scenario ever sleeps in wall-clock
    time. `cancel_check` (default: always `False`) is polled at every
    checkpoint (`termination.evaluate_checkpoint`) to learn whether
    cancellation has been requested — the actual `cancel_requested` storage
    (a `workflow_runs` column) is out of this module's reach; this seam is
    how a later slice's caller wires that column's value in without this
    module gaining direct database access.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        tool_executor: ToolExecutor,
        event_sink: EventSink,
        conversation_store: ConversationStore,
        registry: ToolRegistry,
        playbook: Playbook,
        llm_config: LLMConfig | None = None,
        clock: Callable[[], float] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._tool_executor = tool_executor
        self._event_sink = event_sink
        self._conversation_store = conversation_store
        self._registry = registry
        self._playbook = playbook
        self._llm_config = llm_config if llm_config is not None else LLMConfig()
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._cancel_check: Callable[[], bool] = (
            cancel_check if cancel_check is not None else (lambda: False)
        )
        self._allowed_tool_names: frozenset[str] = frozenset(
            tool_name for step in playbook.steps for tool_name in step.tools
        )

    async def run(self, workflow_run_id: uuid.UUID, *, product_ref: str) -> RunResult:
        """Run the loop for `workflow_run_id` to a terminal block.

        Loads `RunState` from the injected `ConversationStore`, composes the
        system prompt exactly once, then alternates `LLMService.complete()`
        calls with block dispatch until a `FinalResponse` or a self-correction
        give-up ends the run. `RunState` is persisted after every iteration
        (ADR-073 decision 1: "written per iteration") so a later slice's
        resume path has a fresh blob to load from, even though resuming a
        paused run is not this slice's concern.

        Raises `BannedPatternGuardFailure` (propagated from
        `guard_outbound_agent_output`, uncaught) if a `FinalResponse`'s
        content trips the outbound banned-pattern guard — see the module
        docstring's `FinalResponse` bullet for why this is left to propagate
        rather than translated into a `RunResult`.
        """
        state = await self._conversation_store.load(workflow_run_id)

        system_prompt = compose(self._playbook.workflow_key, self._playbook.version)
        version_str = prompt_version(self._playbook.workflow_key, self._playbook.version)
        sha256 = prompt_sha256(self._playbook.workflow_key, self._playbook.version)
        tool_definitions = self._tool_definitions()

        await self._emit(
            workflow_run_id,
            state,
            WorkflowStartedEvent,
            WorkflowStartedPayload(
                workflow_key=self._playbook.workflow_key,
                product_ref=product_ref,
                prompt_version=version_str,
            ),
        )

        consecutive_malformed = 0
        policy = self._playbook.termination_policy

        while True:
            # --- checkpoint: top of iteration (ADR-073 decision 2) ---------
            checkpoint_reason = evaluate_checkpoint(
                cancel_requested=self._cancel_check(),
                running_seconds_elapsed=state.running_seconds_elapsed,
                policy=policy,
            )
            if checkpoint_reason is not None:
                stop = await self._terminate(
                    workflow_run_id, state, checkpoint_reason, version_str, sha256
                )
                await self._conversation_store.persist(workflow_run_id, state)
                return stop

            # --- iteration cap / extension gate -----------------------------
            gate = evaluate_iteration_gate(
                iteration_count=state.iteration_count,
                extensions_granted=state.extensions_granted,
                policy=policy,
            )
            if gate.action is IterationGateAction.STOP:
                # `evaluate_iteration_gate` always sets `stop_reason` on a STOP
                # action (its only reason: ITERATION_CAP_EXCEEDED); the `or`
                # fallback exists purely so this call stays statically typed
                # without a defensive `assert`.
                stop = await self._terminate(
                    workflow_run_id,
                    state,
                    gate.stop_reason or StopReason.ITERATION_CAP_EXCEEDED,
                    version_str,
                    sha256,
                )
                await self._conversation_store.persist(workflow_run_id, state)
                return stop
            if gate.action is IterationGateAction.EXTEND:
                state.extensions_granted += 1
                await self._emit(
                    workflow_run_id,
                    state,
                    WorkflowStatusEvent,
                    WorkflowStatusPayload(
                        phase_narration=extension_grant_narration(
                            extensions_granted_after_grant=state.extensions_granted,
                            policy=policy,
                        )
                    ),
                )

            iteration_started_at = self._clock()
            turn = await self._llm_service.complete(
                messages=state.conversation_window_for_llm(),
                system=system_prompt,
                tools=tool_definitions,
                config=self._llm_config,
            )
            state.iteration_count += 1

            stop = None
            for block in turn.blocks:
                if isinstance(block, TextBlock):
                    consecutive_malformed = 0
                    await self._append_text_block(workflow_run_id, state, block)
                elif isinstance(block, FinalResponse):
                    consecutive_malformed = 0
                    stop = await self._finalize(workflow_run_id, state, block, version_str, sha256)
                    break
                elif isinstance(block, ToolCallBlock):
                    # --- checkpoint: immediately before tool execution ------
                    pre_tool_reason = evaluate_checkpoint(
                        cancel_requested=self._cancel_check(),
                        running_seconds_elapsed=state.running_seconds_elapsed,
                        policy=policy,
                    )
                    if pre_tool_reason is not None:
                        stop = await self._terminate(
                            workflow_run_id, state, pre_tool_reason, version_str, sha256
                        )
                        break
                    outcome = await self._dispatch_tool_call(workflow_run_id, state, block)
                    if outcome is _ToolCallOutcome.MALFORMED:
                        consecutive_malformed += 1
                        if consecutive_malformed >= _MAX_CONSECUTIVE_MALFORMED_ATTEMPTS:
                            stop = await self._give_up(workflow_run_id, state, version_str, sha256)
                            break
                    else:
                        consecutive_malformed = 0
                else:  # pragma: no cover - Block is a closed union, this is defensive
                    raise TypeError(f"WorkflowRunner cannot dispatch block type {type(block)!r}")

            elapsed = self._clock() - iteration_started_at
            state.running_seconds_elapsed = accumulate_running_seconds(
                state.running_seconds_elapsed, delta_seconds=elapsed
            )

            await self._conversation_store.persist(workflow_run_id, state)

            if stop is not None:
                return stop

    # --- block handlers -----------------------------------------------------

    async def _append_text_block(
        self, workflow_run_id: uuid.UUID, state: RunState, block: TextBlock
    ) -> None:
        state.conversation_window.append({"role": "assistant", "content": block.text})
        await self._emit(
            workflow_run_id, state, AssistantTextEvent, AssistantTextPayload(text=block.text)
        )

    async def _dispatch_tool_call(
        self, workflow_run_id: uuid.UUID, state: RunState, block: ToolCallBlock
    ) -> _ToolCallOutcome:
        """Registry lookup -> playbook allowlist -> `input_model` validation
        -> `ToolExecutor.execute` -> `guard_inbound_tool_result` -> append.

        The three refusal paths (unregistered, registered-but-not-in-playbook,
        malformed params) never call `self._tool_executor.execute` — a spy
        `ToolExecutor` records zero calls for any of them. Each produces a
        distinguishable, business-language message: the acceptance criteria
        require the two allowlist cases be distinguishable from each other
        and from a malformed-params refusal, which the message text (and the
        `_ToolCallOutcome` this returns) both satisfy without inventing a
        second error-envelope shape.
        """
        try:
            spec = self._registry.get(block.tool_name)
        except UnknownToolError:
            await self._refuse(
                workflow_run_id,
                state,
                block,
                message=f"Tool {block.tool_name!r} is not a registered agent capability.",
            )
            return _ToolCallOutcome.REFUSED

        if block.tool_name not in self._allowed_tool_names:
            await self._refuse(
                workflow_run_id,
                state,
                block,
                message=(
                    f"Tool {block.tool_name!r} is registered but is not part of the "
                    f"active {self._playbook.workflow_key!r} playbook and cannot be called."
                ),
            )
            return _ToolCallOutcome.REFUSED

        try:
            params = spec.input_model.model_validate(block.arguments)
        except ValidationError as exc:
            await self._refuse(
                workflow_run_id,
                state,
                block,
                message=(
                    f"Parameters for tool {block.tool_name!r} failed validation: "
                    f"{exc.errors()!r}. Correct the parameters and try again."
                ),
            )
            return _ToolCallOutcome.MALFORMED

        state.conversation_window.append(self._tool_call_message(block))
        await self._emit(
            workflow_run_id,
            state,
            ToolStartedEvent,
            ToolStartedPayload(tool_call_id=block.call_id, tool_name=block.tool_name),
        )

        raw_result = self._tool_executor.execute(tool_name=block.tool_name, params=params)
        sanitized = guard_inbound_tool_result(raw_result, tool_name=block.tool_name)
        ok = sanitized is raw_result

        await self._emit(
            workflow_run_id,
            state,
            ToolCompletedEvent,
            ToolCompletedPayload(
                tool_call_id=block.call_id,
                tool_name=block.tool_name,
                ok=ok,
                summary=("completed" if ok else "blocked by the inbound safety guard"),
            ),
        )
        state.conversation_window.append(
            {
                "role": "tool",
                "tool_call_id": block.call_id,
                "tool_name": block.tool_name,
                "content": dict(sanitized),
            }
        )
        return _ToolCallOutcome.SUCCESS

    async def _refuse(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        block: ToolCallBlock,
        *,
        message: str,
    ) -> None:
        """Record a refused `ToolCallBlock` — never dispatched to
        `ToolExecutor` — as one assistant proposal plus one error tool
        result, in the same `{"error": {"category", "message", "retryable"}}`
        shape `guard_inbound_tool_result` uses for a sanitizer hit, so the
        conversation has one error shape to reason about regardless of which
        seam produced it.
        """
        state.conversation_window.append(self._tool_call_message(block))
        envelope = to_error_envelope(
            TranslatedError(
                category=ExecutionErrorCategory.VALIDATION,
                message=message,
                retryable=False,
            )
        )
        state.conversation_window.append(
            {
                "role": "tool",
                "tool_call_id": block.call_id,
                "tool_name": block.tool_name,
                "content": envelope,
            }
        )
        await self._emit(
            workflow_run_id,
            state,
            ToolCompletedEvent,
            ToolCompletedPayload(
                tool_call_id=block.call_id, tool_name=block.tool_name, ok=False, summary=message
            ),
        )

    async def _finalize(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        block: FinalResponse,
        version_str: str,
        sha256: str,
    ) -> RunResult:
        # Raises BannedPatternGuardFailure straight out of run() on a hit —
        # deliberately before anything below is recorded (module docstring).
        guard_outbound_agent_output(
            {"content": block.content, "structured_output": block.structured_output}
        )
        state.conversation_window.append({"role": "assistant", "content": block.content})
        stop_reason = StopReason.FINAL_RESPONSE
        await self._emit(
            workflow_run_id,
            state,
            WorkflowCompletedEvent,
            WorkflowCompletedPayload(stop_reason=stop_reason),
        )
        return RunResult(
            stop_reason=stop_reason,
            status=status_for(stop_reason),
            final_response=block.content,
            prompt_version=version_str,
            prompt_sha256=sha256,
            iteration_count=state.iteration_count,
        )

    async def _give_up(
        self, workflow_run_id: uuid.UUID, state: RunState, version_str: str, sha256: str
    ) -> RunResult:
        stop_reason = StopReason.TOOL_ERROR_UNRECOVERABLE
        status = status_for(stop_reason)
        await self._emit(
            workflow_run_id,
            state,
            WorkflowFailedEvent,
            WorkflowFailedPayload(status=status, stop_reason=stop_reason),
        )
        return RunResult(
            stop_reason=stop_reason,
            status=status,
            final_response=None,
            prompt_version=version_str,
            prompt_sha256=sha256,
            iteration_count=state.iteration_count,
        )

    async def _terminate(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        stop_reason: StopReason,
        version_str: str,
        sha256: str,
    ) -> RunResult:
        """End the run for a termination-policy reason (issue #1120):
        checkpoint cancellation (`cancelled_by_seller`), the paused wall
        clock (`wall_clock_timeout`), or the exhausted iteration cap
        (`iteration_cap_exceeded`). All three map to a failure-class status
        (`status.py`'s total mapping), so — like `_give_up` — this emits
        `workflow.failed`, never `workflow.completed`.
        """
        status = status_for(stop_reason)
        await self._emit(
            workflow_run_id,
            state,
            WorkflowFailedEvent,
            WorkflowFailedPayload(status=status, stop_reason=stop_reason),
        )
        return RunResult(
            stop_reason=stop_reason,
            status=status,
            final_response=None,
            prompt_version=version_str,
            prompt_sha256=sha256,
            iteration_count=state.iteration_count,
        )

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _tool_call_message(block: ToolCallBlock) -> ConversationMessage:
        return {
            "role": "assistant",
            "tool_call": {
                "call_id": block.call_id,
                "tool_name": block.tool_name,
                "arguments": dict(block.arguments),
            },
        }

    def _tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """The model-facing tool list, rendered from the active `Playbook`'s
        own allowlist — the same source `_dispatch_tool_call` enforces
        against, so what the model is told it can call and what the
        executor accepts cannot disagree (ADR-072 decision 2)."""
        seen: set[str] = set()
        definitions: list[ToolDefinition] = []
        for step in self._playbook.steps:
            for tool_name in step.tools:
                if tool_name in seen:
                    continue
                seen.add(tool_name)
                spec = self._registry.get(tool_name)
                definitions.append(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "input_schema": spec.render_input_schema(),
                    }
                )
        return tuple(definitions)

    async def _emit(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        event_cls: Any,
        payload: BaseModel,
    ) -> None:
        event = event_cls(
            workflow_run_id=workflow_run_id,
            sequence_number=state.allocate_sequence(),
            timestamp=datetime.now(UTC),
            payload=payload,
            v=1,
        )
        await self._event_sink.emit(event)


__all__ = ["RunResult", "WorkflowRunner"]
