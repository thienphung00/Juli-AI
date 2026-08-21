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
`workflow_runs.running_seconds_elapsed` integer mirror. As of issue #1216
this module *does* write that mirror (previously it did not — the column
stayed `0` on every real run regardless of duration): every
`_conversation_store.persist(...)` call site, per-iteration and terminal
alike, passes `running_seconds_elapsed=running_seconds_column_value(state
.running_seconds_elapsed)` alongside whatever else it already passes — see
that paragraph below.

**Pause/resume for a CONFIRM-policy tool (ADR-073 decisions 1 and 5, issue
#1123 / AGT-W3A).** Once a `ToolCallBlock` clears the allowlist and
`input_model` validation, `_dispatch_tool_call` checks the target
`ToolSpec.policy` (the registry's own `ToolPolicy`, never a second copy):
AUTO dispatches immediately, exactly as before; CONFIRM never reaches
`ToolExecutor.execute` in this call. Instead the call is recorded on
`state.pending_confirmation`, a `workflow.approval_required` event is
emitted (the only event this module bothers with here — ADR-073 decision
2's paused wall clock and #1118's `next_sequence` counter both already do
the right thing with no special-casing: nothing calls
`accumulate_running_seconds`/`allocate_sequence` again until the run
resumes), and the run ends with `stop_reason=paused_for_confirmation`
(`status.py`'s total mapping: `waiting_approval`). `resume()` is the
second-worker-process entry point: it loads a **fresh** `RunState` from the
injected `ConversationStore` — never anything held by whatever
`WorkflowRunner` instance originally paused, which may not even exist
anymore in this process — and either dispatches the now-approved pending
call and re-enters the same block-dispatch loop `run()` uses
(`_drive_loop`), or ends the run with `stop_reason=confirmation_declined`
without ever calling `ToolExecutor.execute`. `resume()` consumes an
already-authorized `approved: bool`; validating *who* may approve and
recording consent is W4-A's approval endpoint, entirely outside this
module. What remains out of scope here: the idempotency ledger /
claim-then-execute (#1121), basis-hash compare-before-write (#1122), and
the reaper's 4h `confirmation_expired` sweep (#1130).

**Exception translation (ADR-073 decisions 3 and 4, issue #1172).**
`ConcurrencyExhaustedError` (`concurrency.py`) and
`ToolExecutionUnrecoverableError` (`ledger.py`) are collaborator-defined,
typed signals for "this run cannot continue" — a second same-operation
basis-hash mismatch, and a ledger row this run's `verify_applied` read-back
could not resolve, respectively. Neither collaborator this module talks to
is this module's job to wire up (`ProductToolExecutor` is constructed
elsewhere, per the paragraph above), but *catching* the exception they
raise out of `ToolExecutor.execute` is: both `_dispatch_tool_call` (the
`run()` path) and `resume()`'s own direct `execute` call wrap that call in
a `try`/`except` and finalize the run through `_terminate` — the exact
same terminal machinery `evaluate_checkpoint`'s cancellation/wall-clock
timeouts and the iteration-cap gate already use (`workflow.failed` through
the sink, `status_for`, `RunState` persisted) — landing on
`stop_reason=concurrency_conflict` / `tool_error_unrecoverable`
respectively. No in-flight-write semantics change: both exceptions are
raised either *before* a write is attempted (a concurrency conflict) or
*after* `ledger.py`'s own fail-closed verify-then-decide has already given
up (never guessed) — this module only ever translates an already-decided
outcome into a graceful terminal `RunResult`, never second-guesses it.

**LLM-call exception translation (issue #1172).** `LLMService` (the
protocol this module depends on) declares no exception surface of its own
-- by design, per its own docstring, so no vendor-shaped exception type
ever appears in the protocol signature. The one concrete implementation
that exists today, `OpenAIResponsesAdapter`, defines the seam itself:
`LLMProviderError`, "raised in place of any raw `httpx` exception or
malformed-payload exception -- callers never see a provider/SDK-shaped
exception type" (`openai_adapter.py`'s own docstring). This module catches
exactly that type around its one `self._llm_service.complete(...)` call
site (inside `_drive_loop`, shared by `run()` and `resume()`) and
finalizes through `_terminate` with `stop_reason=llm_error` -- the same
translation shape as the two collaborator exceptions above. Deliberately
never a blanket `except Exception`: that would also swallow
`asyncio.CancelledError` semantics and mask the two collaborator
exceptions this module handles separately, neither of which this slice is
willing to risk.

**`tool_call_id` threading (issue #1145).** Both `_dispatch_tool_call` and
`resume` pass the block's own `call_id` through to
`ToolExecutor.execute(..., tool_call_id=...)` — previously omitted, which
left `tool_executor.py`'s ledger-routing branch structurally unreachable
(`ledger`/`workflow_run_id`/`tool_call_id` must *all* be present). This
module still never constructs a `ToolExecutionLedger` or `ConcurrencyGuard`
itself — that stays the caller's job (whatever constructs this run's
`ToolExecutor`, per `tool_executor.py`'s own docstring) — this module only
ever forwards the id it already had.

**`compose()`/prompt stamping (ADR-072 decision 4).** `compose()`,
`prompt_version()`, and `prompt_sha256()` are called exactly once, at the
top of `run()`, from the injected `Playbook`'s own `workflow_key`/`version`
— never recomputed per iteration. The `RunResult` this returns carries both
values so a caller can stamp them on the `workflow_runs` row; this module
has no direct database access of its own (only `ConversationStore.load`/
`persist`), so writing them to the row's actual `prompt_version`/
`prompt_sha256` columns stays a later slice's job. `status`/`stop_reason`/
`completed_at` are no longer in that "later slice" bucket as of issue #1178
(next paragraph), nor is `running_seconds_elapsed`'s own denormalized
integer mirror, as of issue #1216 (two paragraphs below).

**Terminal `status`/`stop_reason`/`completed_at` persistence (issue #1178).**
Every `_conversation_store.persist(...)` call this module makes at a
terminal exit — the two early-return sites in `_drive_loop` (the top-of-
iteration checkpoint terminate, the iteration-cap STOP), the LLM-error
`except` branch, the one common end-of-iteration persist that also covers
`_finalize`/`_pause_for_confirmation`/`_give_up`/the pre-tool-checkpoint and
mid-tool-dispatch terminates, and both of `resume`'s own terminate/decline
branches — now passes `status=stop.status, stop_reason=stop.stop_reason`
(the exact `RunResult` fields `status_for` already computed) through to
`ConversationStore.persist`'s new keyword-only parameters
(`conversation_store.py`). Every persist call that is *not* at a terminal
exit (the ordinary per-iteration persist, and `resume`'s own persist right
after a successfully-dispatched approved tool call, before `_drive_loop`
re-enters) omits them, which defaults to `None`/`None` — a true no-op that
leaves the row's status columns exactly as they were. This module still
never touches `workflow_runs` directly; `JsonbConversationStore` is what
actually flips the column and stamps `completed_at`/`waiting_approval_since`
— see that module's own docstring for the full seam rationale, including
why this is not the same authority as the reaper's `_ReaperEventSink`.

**`required_steps_completed` persistence (issue #1220).** Every one of the
same terminal `persist(...)` call sites above also now passes
`required_steps_completed=self._required_steps_completed(state)` — a third
fact, computed fresh each time by scanning `state.conversation_window`
against `self._playbook.termination_policy.required_steps`
(`termination.py::required_steps_completed`), never derived from or
folded into `stop_reason`. This is deliberately NOT a termination rule:
`stop_reason`/`status` are computed exactly as they were before this
change, on every path, including a `final_response` with zero required
writes completed — that run still ends `stop_reason=final_response`,
`status=completed`; `required_steps_completed=False` is recorded
alongside it as an honest, separate outcome fact (ADR-073 decision 2),
not a reason to invent a new failure branch here.

**`running_seconds_elapsed` column mirror (issue #1216).** The defect:
`workflow_runs.running_seconds_elapsed` recorded `0` on every real run
regardless of how long it actually ran, because nothing on the live path
ever called `termination.running_seconds_column_value` — the pure
function existed and was correct, it was simply never wired to a write.
Unlike `status`/`stop_reason`/`required_steps_completed` (terminal-only),
*every* `_conversation_store.persist(...)` call site in this module —
the per-iteration persist at the bottom of `_drive_loop`'s loop body,
`resume()`'s own persist right after a successfully-dispatched approved
tool call, and every terminal site alongside the other three — now also
passes `running_seconds_elapsed=running_seconds_column_value(state
.running_seconds_elapsed)`, so the column tracks the authoritative float
at every write, not only at a run's end. The mirror is computed fresh
from `state.running_seconds_elapsed` at each call, never accumulated
independently (`termination.py`'s own rounding-decision paragraph), and
this module still never reads the column back for anything — every
termination decision (`evaluate_checkpoint`, both call sites above) keeps
comparing the float directly, exactly as before. The clock excludes a
`waiting_approval` pause by construction, not by subtraction: nothing in
this module calls `accumulate_running_seconds` between the pause site
(`_pause_pending_confirmation`) and `resume()`'s own first clock reading
inside `_drive_loop`, so a pause of any length contributes nothing to the
accumulator either before or after this issue's fix.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    WorkflowApprovalRequiredEvent,
    WorkflowApprovalRequiredPayload,
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
from juli_backend.services.agent.llm.openai_adapter import LLMProviderError
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.agent.prompts.composer import compose, prompt_sha256, prompt_version
from juli_backend.services.agent.runner.concurrency import ConcurrencyExhaustedError
from juli_backend.services.agent.runner.conversation_store import ConversationStore
from juli_backend.services.agent.runner.ledger import ToolExecutionUnrecoverableError
from juli_backend.services.agent.runner.state import ConversationMessage, RunState
from juli_backend.services.agent.runner.termination import (
    IterationGateAction,
    accumulate_running_seconds,
    evaluate_checkpoint,
    evaluate_iteration_gate,
    extension_grant_narration,
    required_steps_completed,
    running_seconds_column_value,
)
from juli_backend.services.agent.runner.tool_executor import ToolExecutor
from juli_backend.services.agent.sanitize import (
    BannedPatternGuardFailure,
    TranslatedError,
    guard_inbound_tool_result,
    guard_outbound_agent_output,
    to_error_envelope,
)
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus, status_for
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry, UnknownToolError
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
    # A validated CONFIRM-policy call — never dispatched to ToolExecutor in
    # this call, recorded on state.pending_confirmation instead (#1123).
    # Resets the self-correction streak exactly like SUCCESS/REFUSED: it is
    # not a malformed-params outcome.
    PAUSED = auto()
    # `ToolExecutor.execute` raised `ConcurrencyExhaustedError` /
    # `ToolExecutionUnrecoverableError` (issue #1172) — the run ends via
    # `_terminate`, never a self-correction retry, so these never touch the
    # malformed-attempt streak either.
    CONCURRENCY_EXHAUSTED = auto()
    UNRECOVERABLE_TOOL_ERROR = auto()


class NoPendingConfirmationError(RuntimeError):
    """Raised by `WorkflowRunner.resume` when the loaded `RunState` has no
    `pending_confirmation` to resume from (issue #1123).

    Resuming a run that was never paused (or whose pending confirmation was
    already resolved by an earlier `resume` call) is a caller bug — this
    module never treats it as a silent no-op.
    """


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
        calls with block dispatch until a `FinalResponse`, a self-correction
        give-up, or a CONFIRM-policy pause ends the run. `RunState` is
        persisted after every iteration (ADR-073 decision 1: "written per
        iteration") so `resume` (below) always has a fresh blob to load
        from — from this same process or a different one.

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

        return await self._drive_loop(
            workflow_run_id,
            state,
            system_prompt=system_prompt,
            version_str=version_str,
            sha256=sha256,
            tool_definitions=tool_definitions,
        )

    async def resume(self, workflow_run_id: uuid.UUID, *, approved: bool) -> RunResult:
        """Resume a run paused at `waiting_approval` (ADR-073 decisions 1
        and 5's resume seam; issue #1123 — the P-CS kill-and-resume gate in
        miniature).

        Loads a **fresh** `RunState` from the injected `ConversationStore`
        — nothing about this call reaches into whatever `WorkflowRunner`
        instance originally paused the run; that instance may live in a
        different process, or may no longer exist at all. This is the
        whole property a CONFIRM pause needs: the resuming worker
        constructs its own `WorkflowRunner` around its own collaborators
        (its own `ConversationStore` implementation pointed at the same
        `workflow_runs` row, its own `ToolExecutor`, its own `EventSink`)
        and calls `resume` — the blob is the only channel of information
        that crosses the boundary.

        `approved` is the already-authorized seller decision. W4-A's
        approval endpoint is what validates *who* may decide and records
        consent; this method only ever consumes the resulting boolean,
        never a raw request — see the module docstring's boundary note.
        A declined confirmation ends the run immediately with
        `stop_reason=confirmation_declined` (`status.py`'s total mapping:
        `completed`) without ever calling `ToolExecutor.execute`. An
        approved confirmation dispatches the pending call through the same
        `ToolExecutor.execute` -> `guard_inbound_tool_result` -> append
        path `_dispatch_tool_call` uses for an AUTO tool, then re-enters
        `_drive_loop` — the same block-dispatch loop `run()` uses — to
        drive the rest of the scripted scenario to completion.

        Because nothing calls `accumulate_running_seconds` or
        `allocate_sequence` while the run sat paused (the pause mechanism
        `termination.py`'s module docstring describes: there is no
        `pause`/`resume` pair to forget), `state.running_seconds_elapsed`
        and `state.next_sequence` both simply continue from whatever the
        blob says — the elapsed real-world duration of the pause is
        invisible to both, by construction, not by any special-casing in
        this method.

        Raises `NoPendingConfirmationError` if the loaded `RunState` has no
        `pending_confirmation` — resuming a run that was never paused (or
        whose pause was already resolved) is a caller bug, never a silent
        no-op.
        """
        state = await self._conversation_store.load(workflow_run_id)
        if state.pending_confirmation is None:
            raise NoPendingConfirmationError(
                f"WorkflowRunner.resume: run {workflow_run_id} has no "
                "pending_confirmation to resume from."
            )

        system_prompt = compose(self._playbook.workflow_key, self._playbook.version)
        version_str = prompt_version(self._playbook.workflow_key, self._playbook.version)
        sha256 = prompt_sha256(self._playbook.workflow_key, self._playbook.version)
        tool_definitions = self._tool_definitions()

        pending = state.pending_confirmation
        state.pending_confirmation = None
        call_id = pending["call_id"]
        tool_name = pending["tool_name"]
        arguments = pending["arguments"]

        if not approved:
            stop_reason = StopReason.CONFIRMATION_DECLINED
            status = status_for(stop_reason)
            state.conversation_window.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "tool_name": tool_name,
                    "content": {"confirmation": {"decision": "declined"}},
                }
            )
            await self._emit(
                workflow_run_id,
                state,
                ToolCompletedEvent,
                ToolCompletedPayload(
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    ok=False,
                    summary="declined by the seller",
                ),
            )
            await self._emit(
                workflow_run_id,
                state,
                WorkflowCompletedEvent,
                WorkflowCompletedPayload(stop_reason=stop_reason),
            )
            await self._conversation_store.persist(
                workflow_run_id,
                state,
                status=status,
                stop_reason=stop_reason,
                required_steps_completed=self._required_steps_completed(state),
                running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
            )
            return RunResult(
                stop_reason=stop_reason,
                status=status,
                final_response=None,
                prompt_version=version_str,
                prompt_sha256=sha256,
                iteration_count=state.iteration_count,
            )

        spec = self._registry.get(tool_name)
        params = spec.input_model.model_validate(arguments)
        await self._emit(
            workflow_run_id,
            state,
            ToolStartedEvent,
            ToolStartedPayload(tool_call_id=call_id, tool_name=tool_name),
        )
        try:
            raw_result = self._tool_executor.execute(
                tool_name=tool_name, params=params, tool_call_id=call_id
            )
        except ConcurrencyExhaustedError:
            # Mirrors `_dispatch_tool_call`'s handling (issue #1172) — this
            # is the second of the two dispatch sites `ToolExecutor.execute`
            # is called from, and must translate the same way.
            stop = await self._terminate(
                workflow_run_id, state, StopReason.CONCURRENCY_CONFLICT, version_str, sha256
            )
            await self._conversation_store.persist(
                workflow_run_id,
                state,
                status=stop.status,
                stop_reason=stop.stop_reason,
                required_steps_completed=self._required_steps_completed(state),
                running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
            )
            return stop
        except ToolExecutionUnrecoverableError:
            stop = await self._terminate(
                workflow_run_id, state, StopReason.TOOL_ERROR_UNRECOVERABLE, version_str, sha256
            )
            await self._conversation_store.persist(
                workflow_run_id,
                state,
                status=stop.status,
                stop_reason=stop.stop_reason,
                required_steps_completed=self._required_steps_completed(state),
                running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
            )
            return stop
        sanitized = guard_inbound_tool_result(raw_result, tool_name=tool_name)
        ok = sanitized is raw_result
        await self._emit(
            workflow_run_id,
            state,
            ToolCompletedEvent,
            ToolCompletedPayload(
                tool_call_id=call_id,
                tool_name=tool_name,
                ok=ok,
                summary=("completed" if ok else "blocked by the inbound safety guard"),
            ),
        )
        state.conversation_window.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "content": dict(sanitized),
            }
        )
        await self._conversation_store.persist(
            workflow_run_id,
            state,
            running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
        )

        return await self._drive_loop(
            workflow_run_id,
            state,
            system_prompt=system_prompt,
            version_str=version_str,
            sha256=sha256,
            tool_definitions=tool_definitions,
        )

    async def _drive_loop(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        *,
        system_prompt: str,
        version_str: str,
        sha256: str,
        tool_definitions: tuple[ToolDefinition, ...],
    ) -> RunResult:
        """The block-dispatch loop shared by `run()` (a fresh run) and
        `resume()` (continuing past a resolved CONFIRM pause) — everything
        about *how* a run proceeds from here on lives in this one method,
        so the two entry points cannot drift apart on checkpoint,
        iteration-gate, or block-dispatch behavior.
        """
        consecutive_malformed = 0
        policy = self._playbook.termination_policy

        while True:
            # --- checkpoint: top of iteration (ADR-073 decision 2) ---------
            checkpoint_reason = evaluate_checkpoint(
                cancel_requested=self._cancel_check(),
                running_seconds_elapsed=state.running_seconds_elapsed,
                policy=policy,
            )
            stop: RunResult | None
            if checkpoint_reason is not None:
                stop = await self._terminate(
                    workflow_run_id, state, checkpoint_reason, version_str, sha256
                )
                await self._conversation_store.persist(
                    workflow_run_id,
                    state,
                    status=stop.status,
                    stop_reason=stop.stop_reason,
                    required_steps_completed=self._required_steps_completed(state),
                    running_seconds_elapsed=running_seconds_column_value(
                        state.running_seconds_elapsed
                    ),
                )
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
                await self._conversation_store.persist(
                    workflow_run_id,
                    state,
                    status=stop.status,
                    stop_reason=stop.stop_reason,
                    required_steps_completed=self._required_steps_completed(state),
                    running_seconds_elapsed=running_seconds_column_value(
                        state.running_seconds_elapsed
                    ),
                )
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
            try:
                turn = await self._llm_service.complete(
                    messages=state.conversation_window_for_llm(),
                    system=system_prompt,
                    tools=tool_definitions,
                    config=self._llm_config,
                )
            except LLMProviderError:
                # The one concrete LLMService's own typed exception surface
                # (issue #1172) — never a blanket `except Exception`, which
                # would also risk swallowing asyncio.CancelledError or the
                # two collaborator exceptions `_dispatch_tool_call` handles
                # separately. No iteration was completed, so neither
                # `iteration_count` nor `running_seconds_elapsed` advances
                # for this attempt — mirroring the checkpoint-terminate
                # branch above.
                stop = await self._terminate(
                    workflow_run_id, state, StopReason.LLM_ERROR, version_str, sha256
                )
                await self._conversation_store.persist(
                    workflow_run_id,
                    state,
                    status=stop.status,
                    stop_reason=stop.stop_reason,
                    required_steps_completed=self._required_steps_completed(state),
                    running_seconds_elapsed=running_seconds_column_value(
                        state.running_seconds_elapsed
                    ),
                )
                return stop
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
                    if outcome is _ToolCallOutcome.PAUSED:
                        stop = await self._pause_for_confirmation(
                            workflow_run_id, state, version_str, sha256
                        )
                        break
                    if outcome is _ToolCallOutcome.CONCURRENCY_EXHAUSTED:
                        stop = await self._terminate(
                            workflow_run_id,
                            state,
                            StopReason.CONCURRENCY_CONFLICT,
                            version_str,
                            sha256,
                        )
                        break
                    if outcome is _ToolCallOutcome.UNRECOVERABLE_TOOL_ERROR:
                        stop = await self._terminate(
                            workflow_run_id,
                            state,
                            StopReason.TOOL_ERROR_UNRECOVERABLE,
                            version_str,
                            sha256,
                        )
                        break
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

            await self._conversation_store.persist(
                workflow_run_id,
                state,
                status=stop.status if stop is not None else None,
                stop_reason=stop.stop_reason if stop is not None else None,
                required_steps_completed=(
                    self._required_steps_completed(state) if stop is not None else None
                ),
                running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
            )

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
                # The one refusal that a *different next call* genuinely
                # fixes, so the only one tagged retryable. Observed on the
                # live write-path smoke: the model proposed
                # `update_product_price` with `{}`, got this refusal back
                # carrying `retryable: false` alongside prose reading
                # "Correct the parameters and try again", and finalized
                # without ever retrying -- it believed the flag, not the
                # sentence. The run recorded `final_response` having written
                # nothing. The two allowlist refusals below stay
                # non-retryable: re-proposing a tool that is not registered,
                # or not in this playbook, cannot succeed however it is
                # phrased.
                retryable=True,
            )
            return _ToolCallOutcome.MALFORMED

        if spec.policy is ToolPolicy.CONFIRM:
            await self._pause_pending_confirmation(workflow_run_id, state, block)
            return _ToolCallOutcome.PAUSED

        state.conversation_window.append(self._tool_call_message(block))
        await self._emit(
            workflow_run_id,
            state,
            ToolStartedEvent,
            ToolStartedPayload(tool_call_id=block.call_id, tool_name=block.tool_name),
        )

        try:
            raw_result = self._tool_executor.execute(
                tool_name=block.tool_name, params=params, tool_call_id=block.call_id
            )
        except ConcurrencyExhaustedError:
            # A second same-operation basis-hash mismatch (ADR-073 decision
            # 4) — the run ends here, translated by `_drive_loop` via
            # `_terminate`; never a self-correction retry (issue #1172).
            return _ToolCallOutcome.CONCURRENCY_EXHAUSTED
        except ToolExecutionUnrecoverableError:
            # A ledger row this run's fail-closed verify-then-decide could
            # not resolve (ADR-073 decision 3) — same terminal treatment as
            # above, distinct stop_reason (issue #1172).
            return _ToolCallOutcome.UNRECOVERABLE_TOOL_ERROR
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
        retryable: bool = False,
    ) -> None:
        """Record a refused `ToolCallBlock` — never dispatched to
        `ToolExecutor` — as one assistant proposal plus one error tool
        result, in the same `{"error": {"category", "message", "retryable"}}`
        shape `guard_inbound_tool_result` uses for a sanitizer hit, so the
        conversation has one error shape to reason about regardless of which
        seam produced it.

        `retryable` defaults to `False` (the safe direction: never invite a
        retry that cannot succeed) and is raised only by the malformed-params
        caller — see that call site for what the live smoke observed.

        **Both events, not just the completion.** A refusal emits
        `tool.started` before `tool.completed`, even though nothing is
        dispatched. The stream's consumers pair the two by `tool_call_id` —
        a UI opens a running-tool card on `tool.started` and closes it on
        `tool.completed` — so a lone completion is a close with no open. The
        refusal is still fully distinguishable on the stream by the
        completion's own `ok: false` and `summary`, which is where a
        consumer should read the outcome from; `tool.started` says only that
        the model proposed this call, which is true of a refusal too.
        """
        state.conversation_window.append(self._tool_call_message(block))
        await self._emit(
            workflow_run_id,
            state,
            ToolStartedEvent,
            ToolStartedPayload(tool_call_id=block.call_id, tool_name=block.tool_name),
        )
        envelope = to_error_envelope(
            TranslatedError(
                category=ExecutionErrorCategory.VALIDATION,
                message=message,
                retryable=retryable,
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

    async def _pause_pending_confirmation(
        self, workflow_run_id: uuid.UUID, state: RunState, block: ToolCallBlock
    ) -> None:
        """Record a validated CONFIRM-policy `ToolCallBlock` as this run's
        pending confirmation (issue #1123) — the proposal is appended to the
        conversation exactly like an AUTO call's, but `ToolExecutor.execute`
        is never reached from here; `resume` is what dispatches it once
        approved.

        `expires_at` is computed from `self._playbook.termination_policy
        .approval_timeout_h` (ADR-073 decision 2's `approval_timeout_h`,
        never a literal) — the reaper's 4h expiry sweep (#1130) is what
        actually enforces it; this module only surfaces the deadline on the
        `workflow.approval_required` event.
        """
        state.conversation_window.append(self._tool_call_message(block))
        state.pending_confirmation = {
            "call_id": block.call_id,
            "tool_name": block.tool_name,
            "arguments": dict(block.arguments),
        }
        policy = self._playbook.termination_policy
        expires_at = datetime.now(UTC) + timedelta(hours=policy.approval_timeout_h)
        await self._emit(
            workflow_run_id,
            state,
            WorkflowApprovalRequiredEvent,
            WorkflowApprovalRequiredPayload(
                tool_call_id=block.call_id,
                tool_name=block.tool_name,
                proposed_change=dict(block.arguments),
                expires_at=expires_at,
            ),
        )

    async def _pause_for_confirmation(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        version_str: str,
        sha256: str,
    ) -> RunResult:
        """Build the `RunResult` for a run ending at `waiting_approval`
        (issue #1123). No further event is emitted here — the
        `workflow.approval_required` event `_pause_pending_confirmation`
        already emitted at the pause site is the client-facing signal;
        unlike `_terminate`/`_give_up`, this is not a failure-class status
        (`status.py`'s total mapping: `paused_for_confirmation` ->
        `waiting_approval`), so no `workflow.failed` follows it either.
        """
        stop_reason = StopReason.PAUSED_FOR_CONFIRMATION
        return RunResult(
            stop_reason=stop_reason,
            status=status_for(stop_reason),
            final_response=None,
            prompt_version=version_str,
            prompt_sha256=sha256,
            iteration_count=state.iteration_count,
        )

    async def _finalize(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        block: FinalResponse,
        version_str: str,
        sha256: str,
    ) -> RunResult:
        # A guard hit is a KNOWN outcome, not a crash (issue #1210). Letting it
        # propagate out of run() meant the row was never written terminal -- the
        # reaper then stamped `worker_lost`, which is a lie (no worker was lost)
        # and sends an operator after infrastructure. It also skipped the state
        # persist, discarding the conversation and with it the offending text,
        # so the hit could not be diagnosed after the fact.
        #
        # Terminating through `_terminate` instead gives it the accurate
        # `output_validation_failed` stop_reason (already in the vocabulary) via
        # the same path #1172 used for the other five collaborator exceptions.
        # The blocked content is still never recorded: `_terminate` runs before
        # the append below, so the response body does not reach the conversation
        # or the event stream. Recovery (repair retry, rules-template fallback,
        # ADR-070 d.6(b)) stays out of scope -- #994's deferral is unchanged.
        try:
            guard_outbound_agent_output(
                {"content": block.content, "structured_output": block.structured_output}
            )
        except BannedPatternGuardFailure:
            return await self._terminate(
                workflow_run_id,
                state,
                StopReason.OUTPUT_VALIDATION_FAILED,
                version_str,
                sha256,
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

    def _required_steps_completed(self, state: RunState) -> bool:
        """The `required_steps_completed` outcome fact (issue #1220,
        ADR-073 decision 2) for `state` right now.

        Always recomputed fresh from `state.conversation_window` — the one
        durable record `resume()` also inherits unchanged across a CONFIRM
        pause — against the active `Playbook`'s own
        `termination_policy.required_steps`, never a second bookkeeping
        structure this class would have to keep in sync itself. Called at
        every terminal `persist(..., status=..., stop_reason=...)` call
        site, alongside those two fields, never in place of either of
        them — see `termination.required_steps_completed`'s own docstring
        for what counts as "completed".
        """
        return required_steps_completed(
            state.conversation_window, self._playbook.termination_policy.required_steps
        )

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


__all__ = ["NoPendingConfirmationError", "RunResult", "WorkflowRunner"]
