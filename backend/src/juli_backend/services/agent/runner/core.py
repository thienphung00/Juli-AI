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

import logging
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
from juli_backend.services.agent.prompts.composer import (
    compose,
    production_version,
    prompt_sha256,
    prompt_version,
)
from juli_backend.services.agent.runner.concurrency import (
    ConcurrencyExhaustedError,
    ConcurrencyGuard,
)
from juli_backend.services.agent.runner.confirmation import (
    build_confirmation_options,
    compute_params_sha,
)
from juli_backend.services.agent.runner.conversation_store import (
    ConversationStore,
    PendingConfirmationWrite,
)
from juli_backend.services.agent.runner.ledger import ToolExecutionUnrecoverableError
from juli_backend.services.agent.runner.state import ConversationMessage, RunState
from juli_backend.services.agent.runner.termination import (
    IterationGateAction,
    accumulate_running_seconds,
    completed_required_steps,
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
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry, ToolSpec, UnknownToolError
from juli_backend.services.execution.types import ExecutionErrorCategory

logger = logging.getLogger(__name__)


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
        concurrency_guard: ConcurrencyGuard | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._tool_executor = tool_executor
        # Issue #1382. The guard holds the compare-before-write basis in
        # memory; `RunState.basis_snapshots` is what survives a pause. The
        # runner is given the SAME guard instance the ToolExecutor got, purely
        # so it can copy that basis into state before each persist. Without
        # this the basis is captured on the first leg, discarded at the pause,
        # and the resume leg -- where every CONFIRM write happens by
        # construction -- compares against an empty basis and refuses the
        # write as a conflict. Optional so the many tests that construct a
        # runner without a guard keep working; when absent, `_sync_basis` is
        # a no-op and behaviour is unchanged.
        self._concurrency_guard = concurrency_guard
        self._event_sink = event_sink
        self._conversation_store = conversation_store
        self._registry = registry
        self._playbook = playbook
        self._llm_config = llm_config if llm_config is not None else LLMConfig()
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._cancel_check: Callable[[], bool] = (
            cancel_check if cancel_check is not None else (lambda: False)
        )
        # Build allowed tool names from playbook steps and terminal tools.
        # Terminal tools are side-effect-free tools that can end a run without
        # proposing changes (ADR-088 decision 1).
        step_tools = {tool_name for step in playbook.steps for tool_name in step.tools}
        terminal_tools = set(playbook.termination_policy.terminal_tools)
        self._allowed_tool_names: frozenset[str] = frozenset(step_tools | terminal_tools)

    def _compose_prompt(self) -> tuple[str, str, str]:
        """Compose the system prompt and its stamp from the PRODUCTION prompt
        version, never the playbook's own `version`.

        `approval.py::_resolve_prompt_pin` writes `workflow_runs.prompt_version`
        from `production_version()`. Composing here from `self._playbook.version`
        instead let the two diverge silently: run `ac992b92` was recorded as
        `optimize_product.v2` while actually executing v1 (#1359), defeating
        ADR-072 decision 4's "what runs is what was reviewed". A playbook's
        `version` describes its steps and policies; it does not decide which
        prompt text runs.
        """
        version = production_version(self._playbook.workflow_key)
        return (
            compose(self._playbook.workflow_key, version),
            prompt_version(self._playbook.workflow_key, version),
            prompt_sha256(self._playbook.workflow_key, version),
        )

    def _compose_prompt_at_version(self, prompt_version_str: str) -> tuple[str, str, str]:
        """Compose the system prompt from a specific, already-stamped version
        string (issue #1359, ADR-075 decision 2).

        Used by `resume()` to ensure the resumed run executes the same prompt
        version it was originally stamped with, even if production_version has
        bumped between pause and resume — preserving consent binding.

        `prompt_version_str` is in the format "workflow_key_binding.vN" (e.g.,
        "optimize_product.v1"), from which we extract the version number N.
        Supports both dot and slash separators for robustness in test/legacy data.
        """
        # Extract version number: find the rightmost 'v' followed by digits
        # Format is typically "optimize_product.v1" or "optimize_product_2/v1"
        if ".v" in prompt_version_str:
            version_str = prompt_version_str.split(".v")[-1]
        elif "/v" in prompt_version_str:
            version_str = prompt_version_str.split("/v")[-1]
        else:
            raise ValueError(
                f"Cannot parse version from prompt_version string {prompt_version_str!r}; "
                "expected format 'workflow_key_binding.vN' or 'workflow_key_binding/vN'"
            )
        version = int(version_str)
        return (
            compose(self._playbook.workflow_key, version),
            prompt_version(self._playbook.workflow_key, version),
            prompt_sha256(self._playbook.workflow_key, version),
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

        system_prompt, version_str, sha256 = self._compose_prompt()
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
        **Consent binding is re-verified here too (ADR-075 decision 2,
        #1224 review round 2), not only at that endpoint** — see the inline
        comment right before the approve branch's `ToolExecutor.execute`
        call for the full rationale (why this method, not only the caller,
        must independently refuse an unconsented change) and for why a
        divergence stops the run with its own dedicated, individually-named
        member of `status.py`'s total `StopReason` vocabulary (review round
        3) rather than reusing `CONCURRENCY_CONFLICT` — a different failure
        class with an opposite operational meaning, not a mechanically
        similar one.
        A declined confirmation is a conversation, not a kill (ADR-075
        decision 2, issue #1225 / AGT-W5A): it never calls `ToolExecutor
        .execute`, but it is not a silent stop either. The decline is
        appended to the conversation exactly like an ordinary tool result,
        then `_closing_turn_after_decline` gives the model one more `LLM
        Service.complete()` turn — never `_drive_loop` itself, so the model
        cannot propose a further tool dispatch — to produce the honest
        wrap-up text the seller actually sees; a `ToolCallBlock` in that one
        turn is refused exactly like an unlisted tool, never dispatched. The
        run still ends on the dedicated `stop_reason=confirmation_declined`
        (`status.py`'s total mapping: `completed`) — never `final_response`,
        which would erase the approval-rate metric's ability to distinguish
        "declined, then wrapped up" from an ordinary completion — carrying
        whatever closing text the model produced (or `None`, if it said
        nothing) as `RunResult.final_response`. An approved confirmation
        dispatches the pending call through the same `ToolExecutor.execute`
        -> `guard_inbound_tool_result` -> append path `_dispatch_tool_call`
        uses for an AUTO tool, then re-enters `_drive_loop` — the same
        block-dispatch loop `run()` uses — to drive the rest of the
        scripted scenario to completion.

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

        **Entry transition off `waiting_approval` (issue #1181 / AGT-W5A,
        review finding 1178-R2; `durable=True` added in review round 2).**
        Before either branch below does anything else — no tool dispatch, no
        `LLM` call, not even the decline branch's `_emit` calls — this
        method persists `status=RUNNING` through the `ConversationStore`
        seam, with `durable=True`. A crash anywhere in the rest of this
        method (the approve branch's synchronous `ToolExecutor.execute`, in
        particular, is the case #1178's review called out) then leaves the
        row at `running`, not `waiting_approval`: `workers/tasks/reaper.py::
        _reap_expired_waiting_approval` selects rows by `status ==
        WAITING_APPROVAL` alone, so this write drops the run out of that
        sweep's selection immediately, regardless of how stale
        `waiting_approval_since` (never cleared here — `JsonbConversation
        Store.persist` only ever stamps it, never unsets it) is left
        sitting. The same write makes the row newly eligible for
        `_reap_stale_running_and_queued` (`status in (QUEUED, RUNNING)`),
        so an abandoned resume is reaped as `worker_lost`/`failed` by the
        5-minute sweep instead of silently owned by nobody. `RUNNING` is
        the existing, already-total vocabulary member for "a run is
        actively being worked" (`status.py`'s `NON_TERMINAL_STATUSES`) —
        no new `StopReason`/`WorkflowRunStatus` member, and no
        `stop_reason` is recorded here (this is not a loop exit, so
        ADR-073 decision 2's "every exit records exactly one stop_reason"
        does not apply). This call passes no `stop_reason`,
        `required_steps_completed`, or `pending_confirmation` — all three
        stay `None`, the same true no-op every ordinary per-iteration
        persist relies on.

        **Why `durable=True` here and nowhere else in this module (review
        round 2, 2026-08-21).** `workers/tasks/agent_workflow.py::
        _resume_agent_workflow_async` builds this runner's `ConversationStore`
        from one `AsyncSession` it commits exactly once, *after*
        `resume()` returns — every other `persist` call in this module
        (every per-iteration write, and every terminal-exit write) rides
        that same not-yet-committed transaction, by design (ADR-074
        decision 4's `acks_late, max_retries=1`: a crash is meant to be
        absorbed by Celery redelivery replaying from the last *committed*
        state, not by a partially-committed one). Review round 1 missed
        that this entry write inherits the same fate: without
        `durable=True` it is only ever `flush()`-ed, so a crash in the
        approve branch's `ToolExecutor.execute` — the exact scenario this
        docstring opened with — rolls it back along with everything else
        when the caller's session closes uncommitted, leaving the row at
        `waiting_approval` regardless of this method ever having run.
        `durable=True` makes `JsonbConversationStore.persist` call
        `self._session.commit()` immediately after this one write, so it
        survives independently of whatever happens next. Nothing else in
        `resume()`/`_drive_loop`'s transaction semantics changes: the
        commit ends the transaction that covered `load()`'s read plus this
        one write; every write from here on (the approve branch's own
        per-iteration/terminal persists, the decline branch's terminal
        persist) begins a new transaction on first use (SQLAlchemy
        autobegin) and is still covered by the caller's own single final
        `await session.commit()` exactly as before — this method still
        commits nothing else itself.
        """
        state = await self._conversation_store.load(workflow_run_id)
        if state.pending_confirmation is None:
            raise NoPendingConfirmationError(
                f"WorkflowRunner.resume: run {workflow_run_id} has no "
                "pending_confirmation to resume from."
            )

        await self._conversation_store.persist(
            workflow_run_id,
            state,
            status=WorkflowRunStatus.RUNNING,
            running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
            durable=True,
        )

        # Use the stored prompt version from when the run was originally created
        # (issue #1359, ADR-075 decision 2). A production bump between pause and
        # resume must not switch prompts mid-run — the seller consented to the
        # original prompt, not a newer one. state.prompt_version is loaded from
        # the workflow_runs row by ConversationStore.load().
        # Fail-closed (ADR-072 d.4): do not execute if the version is unrecoverable,
        # to preserve "what runs is what was reviewed".
        if state.prompt_version is None or state.prompt_sha256 is None:
            logger.warning(
                "prompt_version_missing_on_resume: run_id=%s reason=pre_fix_run_or_missing_data",
                workflow_run_id,
            )
            stop = await self._terminate(
                workflow_run_id,
                state,
                StopReason.PROMPT_VERSION_UNRECOVERABLE,
                version_str="",
                sha256="",
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

        try:
            system_prompt, version_str, sha256 = self._compose_prompt_at_version(
                state.prompt_version
            )
        except (ValueError, IndexError) as exc:
            logger.warning(
                "prompt_version_unparseable_on_resume: run_id=%s "
                "reason=corrupt_or_malformed_version prompt_version=%s error=%s",
                workflow_run_id,
                state.prompt_version,
                str(exc),
            )
            stop = await self._terminate(
                workflow_run_id,
                state,
                StopReason.PROMPT_VERSION_UNRECOVERABLE,
                version_str="",
                sha256="",
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
            try:
                final_response = await self._closing_turn_after_decline(
                    workflow_run_id,
                    state,
                    system_prompt=system_prompt,
                    tool_definitions=tool_definitions,
                )
            except BannedPatternGuardFailure:
                # Mirrors `_finalize`'s own handling of this exact guard
                # (#1210), reused here for the identical reason (review
                # finding, issue #1225 round 2): this method's own entry-
                # transition persist (#1181, `durable=True`, top of this
                # method) has already committed `status=RUNNING` before
                # either branch runs, so leaving this uncaught would strand
                # the row at RUNNING for `_reap_stale_running_and_queued` to
                # mislabel `worker_lost` five minutes later -- infrastructure
                # death for what is actually a guard correctly refusing the
                # model's closing-turn output. Reuses `_finalize`'s own
                # `StopReason.OUTPUT_VALIDATION_FAILED` -- the vocabulary
                # already covers this failure class; no new member.
                stop = await self._terminate(
                    workflow_run_id,
                    state,
                    StopReason.OUTPUT_VALIDATION_FAILED,
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
                final_response=final_response,
                prompt_version=version_str,
                prompt_sha256=sha256,
                iteration_count=state.iteration_count,
            )

        spec = self._registry.get(tool_name)
        params = spec.input_model.model_validate(arguments)

        # Consent binding, re-verified here (ADR-075 decision 2, #1224
        # review round 2) -- not only at the confirmation-authorization
        # endpoint. ADR-075 attributes this check to "the resume task"
        # itself; before this, it lived solely in `api/routes/agent_runs.py`,
        # which happened to be `resume_agent_workflow`'s only enqueuer but
        # was never a structural guarantee of it -- #1225 adds a second
        # driver of this method next (the decline branch, which never
        # reaches this line), and a control that holds only because there
        # is exactly one caller today is not a control at all. `pending`
        # (`state.pending_confirmation`) is the ONLY channel this method
        # has: `WorkflowRunner` has no direct database access beyond
        # `ConversationStore` (this module's own opening docstring), so it
        # cannot read `run_confirmations.options[].params_sha` itself --
        # the confirmation endpoint stamps the value it already validated
        # onto `pending_confirmation["params_sha"]` before enqueueing
        # (`agent_runs.py`'s approve branch) specifically so this method can
        # independently re-derive-and-compare from state alone, without
        # trusting whichever caller got it here. Absent entirely (every
        # existing caller that resumes a pause it constructed directly,
        # never through that endpoint -- this module's own test suite
        # included) is a true no-op, matching every other optional
        # `pending_confirmation` extension this codebase has added so far;
        # once present, a mismatch is unconditionally a hard failure, never
        # a warning, and `compute_params_sha` -- imported, never
        # reimplemented, see that function's own canonicalization contract
        # -- is computed over `arguments` verbatim, the same raw dict the
        # endpoint hashed, not `params` (the validated `input_model`).
        confirmed_params_sha = pending.get("params_sha")
        params_sha_diverged = (
            confirmed_params_sha is not None
            and compute_params_sha(arguments) != confirmed_params_sha
        )
        if params_sha_diverged:
            # A DEDICATED stop_reason (ADR-073 amendment, ADR-075 decision 2,
            # #1224 review round 3) -- not a reuse of `CONCURRENCY_CONFLICT`.
            # Round 2 of this review reused that member on the reasoning that
            # both are compare-before-write guards; round 3 corrected that:
            # `concurrency_conflict` (ADR-073 decision 4) means a stale
            # PRODUCT snapshot -- someone else edited the listing, routine
            # and retryable in spirit. A `params_sha` divergence means the
            # write about to execute does NOT match what the seller
            # consented to -- rare, alarming, and the exact signal the
            # execution-quality metric (which reads this total vocabulary,
            # ADR-073 decision 2) must never conflate with "a seller edited
            # concurrently". Same reasoning extends to any seller-facing
            # copy that ever renders a stop_reason: reusing
            # `concurrency_conflict` here would say "someone else edited
            # your product" for what is actually Juli refusing to run
            # something the seller never approved. Both still map to
            # `FAILED` (an integrity failure, not a benign seller decision),
            # but as two distinct, individually-named members of the total
            # mapping (`services/agent/status.py`), not one overloaded one --
            # this is that member's one sanctioned producer, guarded by
            # `tests/unit/test_workflow_run_status_mapping.py
            # ::test_confirmation_diverged_is_produced_only_by_the_resume_consent_check`.
            stop = await self._terminate(
                workflow_run_id, state, StopReason.CONFIRMATION_DIVERGED, version_str, sha256
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
            # #1382: the guard just updated its in-memory basis (on a read, or
            # via the post-write refresh). Mirror it into state now, while we
            # are still on this leg — after the pause it is unrecoverable.
            self._sync_basis(state)
            # #1389: if a product was read (for the concurrency basis), persist
            # the raw detail to state so it survives the pause.
            self._sync_product_detail(state)
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
        # ADR-088: the forced retry rides the main loop rather than nesting its
        # own dispatch. `next_tool_choice` applies to exactly the next
        # provider call and is cleared as soon as it is spent, and
        # `forced_retry_used` bounds it to one per run. Riding the loop is what
        # keeps the top-of-iteration checkpoint and the iteration gate ahead of
        # it, so `iteration_cap_exceeded` and `wall_clock_timeout` keep their
        # precedence instead of being masked by `required_steps_unfulfilled`.
        forced_retry_used = False
        next_tool_choice: str | None = None

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
                    tool_choice=next_tool_choice,
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
            # Whatever forced choice was set, the call above has spent it.
            next_tool_choice = None

            stop = None
            for block in turn.blocks:
                if isinstance(block, TextBlock):
                    consecutive_malformed = 0
                    await self._append_text_block(workflow_run_id, state, block)
                elif isinstance(block, FinalResponse):
                    consecutive_malformed = 0
                    # ADR-088: this — not a text-only turn — is how "the model
                    # narrated instead of acting" actually arrives. The real
                    # adapter emits a bare TextBlock ONLY alongside tool calls;
                    # with no function_call items it emits a FinalResponse
                    # (llm/openai_adapter.py). Gating the forced retry on a
                    # TextBlock-only turn therefore made it unreachable in
                    # production while every fake-LLM test passed, because the
                    # fake emits TextBlock directly. Run 2c961380 terminated
                    # final_response with required_steps incomplete and no
                    # retry attempted.
                    #
                    # So intercept the FinalResponse once: append the narration
                    # for continuity, arm one re-invocation with
                    # tool_choice="required", and let the main loop make it, so
                    # the top-of-iteration checkpoint and the iteration gate
                    # keep precedence over required_steps_unfulfilled.
                    # `policy.terminal_tools` is a precondition, not a
                    # convenience: forcing tool_choice="required" when the
                    # model has no legitimate "nothing to do" call available
                    # would coerce a bogus write on a run that genuinely has
                    # nothing to propose — the exact hazard ADR-088 names as
                    # its reason for introducing a terminal tool at all. A
                    # playbook that declares required_steps but no terminal
                    # tool therefore keeps the old terminate-on-final
                    # behaviour.
                    if policy.terminal_tools and not self._required_steps_completed(state):
                        if not forced_retry_used:
                            # Guard BEFORE the interception appends or emits
                            # anything. `_finalize` runs this same chokepoint,
                            # but the retry path bypasses `_finalize` entirely,
                            # so without this a banned-pattern narration would
                            # reach the conversation window and the event
                            # stream unchecked (ADR-070). Terminating here
                            # keeps the blocked body out of both, exactly as
                            # `_finalize` does.
                            try:
                                guard_outbound_agent_output(
                                    {
                                        "content": block.content,
                                        "structured_output": block.structured_output,
                                    }
                                )
                            except BannedPatternGuardFailure:
                                stop = await self._terminate(
                                    workflow_run_id,
                                    state,
                                    StopReason.OUTPUT_VALIDATION_FAILED,
                                    version_str,
                                    sha256,
                                )
                                break
                            forced_retry_used = True
                            next_tool_choice = "required"
                            await self._append_text_block(
                                workflow_run_id, state, TextBlock(text=block.content)
                            )
                            break
                        # The retry was spent and the model narrated again.
                        #
                        # #1383: which terminal this is depends on whether the
                        # run did ANY required work, not whether it did ALL of
                        # it. `required_steps_unfulfilled` is the ADR-088 d.2
                        # defect signal for a run that took no qualifying
                        # action at all. A run that acted on some required
                        # steps and honestly declined the rest is what ADR-073
                        # d.2 protects — "honest outcome data ... not a
                        # synthetic failure" — and ends `final_response`. Gate
                        # #1226 walk run 675bb11e did the listing change and
                        # declined the price change because inventory is 0, a
                        # correct judgement, and was recorded failed.
                        #
                        # The partial fact is not lost: `required_steps_completed`
                        # is still persisted False (#1220), so the
                        # execution-quality metric keeps it without the stop
                        # reason having to carry two meanings.
                        if completed_required_steps(
                            state.conversation_window,
                            self._playbook.termination_policy.required_steps,
                        ):
                            stop = await self._finalize(
                                workflow_run_id, state, block, version_str, sha256
                            )
                            break
                        stop = await self._terminate(
                            workflow_run_id,
                            state,
                            StopReason.REQUIRED_STEPS_UNFULFILLED,
                            version_str,
                            sha256,
                        )
                        break
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
                        # Not MALFORMED: handle SUCCESS (terminal tool check)
                        # and reset malformed streak for all other outcomes
                        if outcome is _ToolCallOutcome.SUCCESS:
                            # Check if this was the terminal tool
                            if block.tool_name == "conclude_without_changes":
                                stop = await self._finalize_with_conclude_without_changes(
                                    workflow_run_id, state, version_str, sha256
                                )
                                break
                        consecutive_malformed = 0
                else:  # pragma: no cover - Block is a closed union, this is defensive
                    raise TypeError(f"WorkflowRunner cannot dispatch block type {type(block)!r}")

            # --- forced retry for incomplete required_steps (ADR-088) --------
            # NOTE: the forced retry is armed in the FinalResponse branch
            # above, not here. An earlier revision gated it on a text-only turn
            # (`saw_text and not saw_actionable`), which is a block shape the
            # real adapter never produces when the model declines to act — it
            # emits FinalResponse instead — so the retry was unreachable in
            # production while every fake-LLM test passed.

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
            await self._pause_pending_confirmation(workflow_run_id, state, block, spec)
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
            self._sync_basis(state)  # #1382 — see the sibling dispatch site
            self._sync_product_detail(state)  # #1389 — product persists across pause
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
        self, workflow_run_id: uuid.UUID, state: RunState, block: ToolCallBlock, spec: ToolSpec
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

        **Decision request recording (issue #1221 / AGT-W5A, ADR-075
        decision 2).** `build_confirmation_options` (`confirmation.py`)
        builds the `options[]` list exactly once here — binary confirm's
        N=1 case, `spec.description` as the placeholder rationale (a
        genuinely reasoned, per-option rationale is P12's prompt-content
        concern, not this module's) — and the *same* list is both emitted
        on `WorkflowApprovalRequiredPayload.options` and written to a new
        `run_confirmations` row via a dedicated
        `self._conversation_store.persist(..., pending_confirmation=...)`
        call, deliberately separate from the per-iteration
        `status=WAITING_APPROVAL` persist call `_drive_loop` already makes
        a few lines after this method returns. Two consequences of that
        separation, both intentional:

        - `state.pending_confirmation` (the JSONB-blob bookkeeping dict
          `resume()` reads `call_id`/`tool_name`/`arguments` back off of)
          stays exactly the three keys it always was — the new options/
          expires_at data never lands there, so it can never leak into
          that dict's exact-equality test coverage or `resume()`'s own
          reads of it.
        - This method calls `persist` with no `status`/`stop_reason` —
          `JsonbConversationStore.persist`'s existing `waiting_approval_
          since` stamping stays entirely `_drive_loop`'s job, unchanged;
          this call's only effect is the `run_confirmations` INSERT.
        """
        state.conversation_window.append(self._tool_call_message(block))
        state.pending_confirmation = {
            "call_id": block.call_id,
            "tool_name": block.tool_name,
            "arguments": dict(block.arguments),
        }
        policy = self._playbook.termination_policy
        expires_at = datetime.now(UTC) + timedelta(hours=policy.approval_timeout_h)
        options = build_confirmation_options(
            rationale=spec.description,
            arguments=block.arguments,
        )
        await self._emit(
            workflow_run_id,
            state,
            WorkflowApprovalRequiredEvent,
            WorkflowApprovalRequiredPayload(
                tool_call_id=block.call_id,
                tool_name=block.tool_name,
                proposed_change=dict(block.arguments),
                expires_at=expires_at,
                options=options,
            ),
        )
        await self._conversation_store.persist(
            workflow_run_id,
            state,
            running_seconds_elapsed=running_seconds_column_value(state.running_seconds_elapsed),
            pending_confirmation=PendingConfirmationWrite(
                tool_call_id=block.call_id,
                options=options,
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

    async def _closing_turn_after_decline(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        *,
        system_prompt: str,
        tool_definitions: tuple[ToolDefinition, ...],
    ) -> str | None:
        """One `LLMService.complete()` turn after a decline is already in
        the conversation (issue #1225 / AGT-W5A, ADR-075 decision 2): "the
        model is told the seller declined, wraps up honestly". This is what
        makes `resume()`'s decline branch "resume the loop", not just record
        a decision — the seller who declined a price change still gets the
        analysis and reasoning the run already produced, restated in the
        model's own words for this response.

        Deliberately never `_drive_loop` — the run's terminal outcome is
        already decided (`stop_reason=confirmation_declined`, the dedicated
        vocabulary member #1224 made reachable), so this is exactly one
        turn, not an open-ended continuation. A `TextBlock` is appended and
        emitted exactly like an ordinary mid-run one. A `FinalResponse` runs
        through the same `guard_outbound_agent_output` chokepoint
        `_finalize` uses before anything about it is recorded, then its
        `content` becomes this call's return value — `resume`'s caller
        threads that straight onto `RunResult.final_response`. A
        `ToolCallBlock` is refused exactly like `_dispatch_tool_call`
        refuses a call outside the active playbook's allowlist (`_refuse`,
        never `ToolExecutor.execute`) — the seller already declined; this
        turn is for wrapping up, not for proposing new action. Returns
        `None` when the model's one turn produced no `FinalResponse` block
        at all (e.g. only `TextBlock`s, or a refused `ToolCallBlock`) —
        `resume()`'s decline branch still ends `confirmation_declined`
        either way, this only ever affects `RunResult.final_response`.

        Raises `BannedPatternGuardFailure`, uncaught here, on a guard hit —
        deliberately NOT swallowed to `None` in this method, the same way
        `_finalize` does not swallow its own identical guard call. `resume`'s
        decline branch is what catches it (review finding, issue #1225 round
        2) and translates it through `_terminate`/`StopReason
        .OUTPUT_VALIDATION_FAILED` — the same terminal member `_finalize`
        already uses for this exact failure (#1210), never a new one — for
        the same reason #1210 exists at all: this method's caller has
        already durably committed `status=RUNNING` (#1181's entry-transition
        persist, before either branch runs), so an exception left to
        propagate all the way out of `resume()` leaves the row stuck at
        `RUNNING` for `_reap_stale_running_and_queued` to reap as
        `worker_lost` five minutes later — a lie (no worker was lost) for
        what is actually a guard correctly refusing the model's output.
        """
        turn = await self._llm_service.complete(
            messages=state.conversation_window_for_llm(),
            system=system_prompt,
            tools=tool_definitions,
            config=self._llm_config,
        )
        final_response: str | None = None
        for block in turn.blocks:
            if isinstance(block, TextBlock):
                await self._append_text_block(workflow_run_id, state, block)
            elif isinstance(block, FinalResponse):
                guard_outbound_agent_output(
                    {"content": block.content, "structured_output": block.structured_output}
                )
                state.conversation_window.append({"role": "assistant", "content": block.content})
                final_response = block.content
                break
            elif isinstance(block, ToolCallBlock):
                await self._refuse(
                    workflow_run_id,
                    state,
                    block,
                    message=(
                        "The seller declined this change; the run is wrapping up "
                        "without dispatching any further tool calls."
                    ),
                )
        return final_response

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

    async def _finalize_with_conclude_without_changes(
        self,
        workflow_run_id: uuid.UUID,
        state: RunState,
        version_str: str,
        sha256: str,
    ) -> RunResult:
        """Terminal outcome when conclude_without_changes tool is successfully
        called (ADR-088 decision 1). The tool itself has no side effects; this
        method emits the completion event and returns with the appropriate
        stop_reason."""
        stop_reason = StopReason.CONCLUDED_WITHOUT_CHANGES
        await self._emit(
            workflow_run_id,
            state,
            WorkflowCompletedEvent,
            WorkflowCompletedPayload(stop_reason=stop_reason),
        )
        return RunResult(
            stop_reason=stop_reason,
            status=status_for(stop_reason),
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
        own allowlist plus terminal tools — the same source `_dispatch_tool_call`
        enforces against, so what the model is told it can call and what the
        executor accepts cannot disagree (ADR-072 decision 2, ADR-088 decision 1)."""
        seen: set[str] = set()
        definitions: list[ToolDefinition] = []
        # Add step tools first
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
        # Then add terminal tools (ADR-088 decision 1)
        for tool_name in self._playbook.termination_policy.terminal_tools:
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

    def _sync_basis(self, state: RunState) -> None:
        """Copy the guard's in-memory compare-before-write basis into
        `RunState`, so it survives the pause/resume boundary (issue #1382).

        `ConcurrencyGuard` is the working copy; `RunState.basis_snapshots` is
        the persisted one that `workers/tasks/agent_workflow.py` reads back to
        seed a fresh guard on resume. Nothing wrote to it before this, so the
        resume leg always started empty and every seller-confirmed write was
        refused as a conflict.
        """
        if self._concurrency_guard is None:
            return
        state.basis_snapshots = dict(self._concurrency_guard.basis_snapshot)

    def _sync_product_detail(self, state: RunState) -> None:
        """Copy the guard's captured product detail into `RunState`, so it
        survives the pause/resume boundary (issue #1389).

        When get_product_information reads the product for the concurrency
        basis, the raw product is stored in the guard and must be persisted
        to state.product_detail before the pause. The resume leg then
        retrieves it and passes it to a fresh executor, so
        update_product_listing can access the full product detail without
        a second vendor call.
        """
        if self._concurrency_guard is None:
            return
        product_detail = self._concurrency_guard.get_product_detail()
        if product_detail is not None:
            state.product_detail = dict(product_detail)

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
