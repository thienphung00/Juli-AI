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
ADR-073 decision 3's idempotent WRITE-path machinery), imported eagerly
below — unlike `core`/`tool_executor`, it has no import-cycle hazard with
`events/` (it only imports `models/models.py`). Basis-hash
compare-before-write is a later slice in this phase — do not add it here.

**Why `core`/`tool_executor` are exported lazily (`__getattr__`, PEP 562)
instead of imported at module scope like the rest of this file.**
`services/agent/events/payloads.py` (#1125) imports
`juli_backend.services.agent.runner.status` — a genuine, correct dependency
(event payloads carry `StopReason`/`WorkflowRunStatus`). Importing *any*
submodule of this package forces Python to run this `__init__.py` first. If
`core.py` (which imports `juli_backend.services.agent.events` right back)
were imported eagerly here too, that would be a real import cycle:
`events -> runner.status -> runner/__init__ -> runner.core -> events`
(caught mid-load, so it fails with an `ImportError` naming a "partially
initialized module"). Deferring the `core`/`tool_executor` imports until
`getattr(runner_package, name)` actually runs — i.e. after this
`__init__.py` has already finished executing — breaks the cycle without
touching `events/` or `status.py`, neither of which this slice may modify.
Importing the submodules directly (`from ...runner.core import
WorkflowRunner`, `from ...runner.tool_executor import ProductToolExecutor`)
works identically and is what this package's own tests do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from juli_backend.services.agent.runner.conversation_store import (
    ConversationStore,
    JsonbConversationStore,
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
from juli_backend.services.agent.runner.status import (
    NON_TERMINAL_STATUSES,
    STOP_REASON_TO_STATUS,
    StopReason,
    WorkflowRunStatus,
    status_for,
)
from juli_backend.services.agent.runner.termination import (
    IterationGate,
    IterationGateAction,
    accumulate_running_seconds,
    effective_iteration_cap,
    evaluate_checkpoint,
    evaluate_iteration_gate,
    extension_grant_narration,
    running_seconds_column_value,
)

if TYPE_CHECKING:  # pragma: no cover - type checkers import eagerly, safely
    from juli_backend.services.agent.runner.core import (
        NoPendingConfirmationError,
        RunResult,
        WorkflowRunner,
    )
    from juli_backend.services.agent.runner.tool_executor import (
        ProductToolExecutor,
        ToolExecutionError,
        ToolExecutor,
    )

_LAZY_CORE_EXPORTS = frozenset({"NoPendingConfirmationError", "RunResult", "WorkflowRunner"})
_LAZY_TOOL_EXECUTOR_EXPORTS = frozenset(
    {"ProductToolExecutor", "ToolExecutionError", "ToolExecutor"}
)


def __getattr__(name: str) -> object:
    if name in _LAZY_CORE_EXPORTS:
        from juli_backend.services.agent.runner import core

        return getattr(core, name)
    if name in _LAZY_TOOL_EXECUTOR_EXPORTS:
        from juli_backend.services.agent.runner import tool_executor

        return getattr(tool_executor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "NON_TERMINAL_STATUSES",
    "STOP_REASON_TO_STATUS",
    "ConversationMessage",
    "ConversationStore",
    "IterationGate",
    "IterationGateAction",
    "JsonbConversationStore",
    "LedgerStatus",
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
    "VerifyOutcome",
    "VerifyReadBack",
    "WorkflowRunStatus",
    "WorkflowRunner",
    "accumulate_running_seconds",
    "effective_iteration_cap",
    "evaluate_checkpoint",
    "evaluate_iteration_gate",
    "extension_grant_narration",
    "running_seconds_column_value",
    "status_for",
]
