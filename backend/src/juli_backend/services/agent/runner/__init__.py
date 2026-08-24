"""Agent execution-loop runner package (ADR-073, AGT-W3A).

#1117 shipped the `status` module (`WorkflowRunStatus`/`StopReason` and the
total mapping between them). #1118 added `state` (`RunState`) and
`conversation_store` (`ConversationStore` protocol + its JSONB-blob
implementation) — state and storage only, no runner. #1119 adds `core`
(`WorkflowRunner`, the block-dispatch loop) and `tool_executor`
(`ToolExecutor` protocol + `ProductToolExecutor`). #1120 adds `termination`
(iteration cap / extensions, the paused wall clock, the shared checkpoint
function) and wires it into `core`. #1123 adds the CONFIRM-policy
pause/resume round trip (`WorkflowRunner.resume`, `NoPendingConfirmationError`)
inside `core` — no new module. #1121 adds `ledger` (`ToolExecutionLedger`,
ADR-073 decision 3's idempotent WRITE-path machinery). #1122 adds
`concurrency` (`ConcurrencyGuard`, ADR-073 decision 4's basis-hash
compare-before-write). This completes ADR-073's runner slices.

**#1139 (AGT-W3A) deletes the lazy `__getattr__` (PEP 562) export this file
used to need for `core`/`tool_executor`.** The vocabulary that used to live
in `runner/status.py` (`WorkflowRunStatus`/`StopReason`/
`STOP_REASON_TO_STATUS`) has moved to the neutral leaf module
`services/agent/status.py`, imported directly by both this package and
`services/agent/events/`. `events/payloads.py` no longer imports anything
from `services.agent.runner` at all — so importing any submodule of this
package no longer has any bearing on how `events/` loads, in either
direction. `core.py` (which imports `services.agent.events`) can therefore
be imported eagerly, at module scope, exactly like every other submodule in
this file: there is no path left from `events` back into `runner`, so there
is nothing left to cycle. `WorkflowRunner`, `RunResult`, and
`NoPendingConfirmationError` (from `core`) and `ProductToolExecutor`,
`ToolExecutor`, `ToolExecutionError` (from `tool_executor`) are ordinary
eager exports below, importable the same way as everything else in
`__all__`.

**#1224 (AGT-W5A) adds `compute_params_sha` to this package's exports.**
`api/routes/agent_runs.py`'s confirmation-decision endpoint re-derives an
approved option's params fingerprint from the run's reconstructed state
(ADR-075 decision 2's consent binding) and must call the *real* hash
function, never a reimplementation (`runner/confirmation.py`'s own
docstring: "byte-for-byte ... including #1224"). `api` cannot import
`juli_backend.services.agent.runner.confirmation` directly — that is a
depth-3 cross-package import, forbidden by `.importlinter.toml`'s
`max_cross_package_depth = 2` (see `agent_runs.py`'s own module docstring)
— but `from juli_backend.services.agent import runner as runner_module`
is exactly depth 2 and already this module's own established idiom
(`_resolve_optimize_product_prompt_pin`'s `playbooks_module`,
`_enqueue_run_agent_workflow`'s `agent_workflow_tasks`). Re-exporting
`compute_params_sha` here — rather than relying on the incidental fact
that `core.py`'s own `from ...confirmation import build_confirmation_options`
happens to set `confirmation` as an attribute of this package as a Python
import side effect — makes that reach a deliberate, documented part of
this package's public surface instead of a fragile accident of import
order.
"""

from __future__ import annotations

from juli_backend.services.agent.runner.concurrency import (
    FIELD_SCOPE_BY_OPERATION,
    MUTABLE_FIELD_NAMES,
    ConcurrencyConflict,
    ConcurrencyExhaustedError,
    ConcurrencyGuard,
    ConcurrencyMatch,
    MutableProductFields,
    UnknownConcurrencyScopedOperationError,
    capture_basis_snapshot,
    extract_mutable_fields,
    field_scope_for,
)
from juli_backend.services.agent.runner.confirmation import compute_params_sha
from juli_backend.services.agent.runner.conversation_store import (
    ConversationStore,
    JsonbConversationStore,
)
from juli_backend.services.agent.runner.core import (
    NoPendingConfirmationError,
    RunResult,
    WorkflowRunner,
)
from juli_backend.services.agent.runner.ledger import (
    LedgerStatus,
    ToolExecutionLedger,
    ToolExecutionUnrecoverableError,
    VerifyOutcome,
    VerifyReadBack,
)
from juli_backend.services.agent.runner.state import (
    ConversationMessage,
    RunState,
    RunStateFieldMissingError,
)
from juli_backend.services.agent.runner.termination import (
    IterationGate,
    IterationGateAction,
    accumulate_running_seconds,
    effective_iteration_cap,
    evaluate_checkpoint,
    evaluate_iteration_gate,
    extension_grant_narration,
    required_steps_completed,
    running_seconds_column_value,
)
from juli_backend.services.agent.runner.tool_executor import (
    ProductToolExecutor,
    ToolExecutionError,
    ToolExecutor,
)
from juli_backend.services.agent.status import (
    NON_TERMINAL_STATUSES,
    STOP_REASON_TO_STATUS,
    StopReason,
    WorkflowRunStatus,
    status_for,
)

__all__ = [
    "FIELD_SCOPE_BY_OPERATION",
    "MUTABLE_FIELD_NAMES",
    "NON_TERMINAL_STATUSES",
    "STOP_REASON_TO_STATUS",
    "ConcurrencyConflict",
    "ConcurrencyExhaustedError",
    "ConcurrencyGuard",
    "ConcurrencyMatch",
    "ConversationMessage",
    "ConversationStore",
    "IterationGate",
    "IterationGateAction",
    "JsonbConversationStore",
    "LedgerStatus",
    "MutableProductFields",
    "NoPendingConfirmationError",
    "ProductToolExecutor",
    "RunResult",
    "RunState",
    "RunStateFieldMissingError",
    "StopReason",
    "ToolExecutionError",
    "ToolExecutionLedger",
    "ToolExecutionUnrecoverableError",
    "ToolExecutor",
    "UnknownConcurrencyScopedOperationError",
    "VerifyOutcome",
    "VerifyReadBack",
    "WorkflowRunStatus",
    "WorkflowRunner",
    "accumulate_running_seconds",
    "capture_basis_snapshot",
    "compute_params_sha",
    "effective_iteration_cap",
    "evaluate_checkpoint",
    "evaluate_iteration_gate",
    "extension_grant_narration",
    "extract_mutable_fields",
    "field_scope_for",
    "required_steps_completed",
    "running_seconds_column_value",
    "status_for",
]
