"""Agent execution-loop runner package (ADR-073, AGT-W3A).

#1117 shipped the `status` module (`WorkflowRunStatus`/`StopReason` and the
total mapping between them). #1118 adds `state` (`RunState`) and
`conversation_store` (`ConversationStore` protocol + its JSONB-blob
implementation) — state and storage only, no runner. `WorkflowRunner`
itself, the tool executor, termination-policy evaluation, and the
idempotency ledger are later slices in this phase (P1-3 and on) — do not
add them here.
"""

from __future__ import annotations

from juli_backend.services.agent.runner.conversation_store import (
    ConversationStore,
    JsonbConversationStore,
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

__all__ = [
    "NON_TERMINAL_STATUSES",
    "STOP_REASON_TO_STATUS",
    "ConversationMessage",
    "ConversationStore",
    "JsonbConversationStore",
    "RunState",
    "RunStateFieldMissingError",
    "StopReason",
    "WorkflowRunStatus",
    "status_for",
]
