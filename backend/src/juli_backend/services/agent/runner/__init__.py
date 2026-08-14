"""Agent execution-loop runner package (ADR-073, AGT-W3A).

This slice (#1117 / AGT-W3A) ships only the `status` module: the
`WorkflowRunStatus`/`StopReason` vocabulary and the total mapping between
them. `WorkflowRunner` itself, run state, the conversation store, the tool
executor, termination-policy evaluation, and the idempotency ledger are
later slices in this phase (P1-2 and on) — do not add them here.
"""

from __future__ import annotations

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
    "StopReason",
    "WorkflowRunStatus",
    "status_for",
]
