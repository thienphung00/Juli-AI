"""`WorkflowRunStatus` and the `stop_reason` vocabulary — ADR-073 decision 2,
plus the 2026-08-12 `worker_lost` amendment (ADR-074).

This module is deliberately narrow: the vocabulary and the TOTAL
`StopReason -> WorkflowRunStatus` mapping, nothing else. The runner that
reads/writes `workflow_runs.status`/`stop_reason` (block dispatch, iteration
count, checkpoints) lands in a later slice (P1-2 and on) — this slice ships
schema plus vocabulary only.

Every loop exit records exactly one `stop_reason` (ADR-073 decision 2: "no
silent exits"). `STOP_REASON_TO_STATUS` is that mapping, and it is TOTAL over
`StopReason`: every member has an entry. It is not, and cannot be, total
*onto* `WorkflowRunStatus` in the naive sense — `QUEUED` and `RUNNING` are
states a run occupies *before* any loop iteration has stopped, so no
`stop_reason` ever targets them structurally, by definition of what a
`stop_reason` records. `NON_TERMINAL_STATUSES` names exactly those two
members; every *other* `WorkflowRunStatus` member (the five ADR-073's
decision-2 table actually lists as targets) has at least one `StopReason`
mapping to it, and the mapping test in
`tests/unit/test_workflow_run_status_mapping.py` asserts that precise shape
in both directions — not a vacuous "some status somewhere" check.

`OUTPUT_VALIDATION_FAILED` is reserved for P7 (structured output) per ADR-073
decision 5: present in the enum and mapped to `FAILED` now, so P7 adds no new
vocabulary later, but no code in this slice (or any slice before P7)
constructs it. `tests/unit/test_workflow_run_status_mapping.py` also guards
that this module is the *only* place the member is referenced within
`services/agent/runner/`, so a future accidental "producer" trips a test
instead of silently breaking the P7 deferral.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType


class WorkflowRunStatus(StrEnum):
    """The seven states a `workflow_runs` row can occupy (ADR-073, amending
    ADR-068's original eight-state list by dropping `created` — a run row is
    only ever inserted already `queued`)."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class StopReason(StrEnum):
    """Why a `WorkflowRunner` loop stopped — recorded exactly once per run,
    on every exit path (ADR-073 decision 2)."""

    FINAL_RESPONSE = "final_response"
    CONFIRMATION_DECLINED = "confirmation_declined"
    PAUSED_FOR_CONFIRMATION = "paused_for_confirmation"
    CANCELLED_BY_SELLER = "cancelled_by_seller"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"
    WALL_CLOCK_TIMEOUT = "wall_clock_timeout"
    TOOL_ERROR_UNRECOVERABLE = "tool_error_unrecoverable"
    LLM_ERROR = "llm_error"
    CONCURRENCY_CONFLICT = "concurrency_conflict"
    # Reserved for P7 (structured output) — ADR-073 decision 5. Present and
    # mapped below so P7 adds no vocabulary later; unreachable until then.
    OUTPUT_VALIDATION_FAILED = "output_validation_failed"
    # ADR-074 amendment (2026-08-12): assigned by the reaper to runs whose
    # worker died twice (crash + failed redelivery).
    WORKER_LOST = "worker_lost"


# The TOTAL stop_reason -> status mapping, reproducing ADR-073 decision 2's
# table exactly, plus the worker_lost amendment row. `MappingProxyType` keeps
# this read-only — the vocabulary is fixed at import time, not mutated by
# callers.
STOP_REASON_TO_STATUS: MappingProxyType[StopReason, WorkflowRunStatus] = MappingProxyType(
    {
        StopReason.FINAL_RESPONSE: WorkflowRunStatus.COMPLETED,
        StopReason.CONFIRMATION_DECLINED: WorkflowRunStatus.COMPLETED,
        StopReason.PAUSED_FOR_CONFIRMATION: WorkflowRunStatus.WAITING_APPROVAL,
        StopReason.CANCELLED_BY_SELLER: WorkflowRunStatus.CANCELLED,
        StopReason.CONFIRMATION_EXPIRED: WorkflowRunStatus.CANCELLED,
        StopReason.ITERATION_CAP_EXCEEDED: WorkflowRunStatus.TIMED_OUT,
        StopReason.WALL_CLOCK_TIMEOUT: WorkflowRunStatus.TIMED_OUT,
        StopReason.TOOL_ERROR_UNRECOVERABLE: WorkflowRunStatus.FAILED,
        StopReason.LLM_ERROR: WorkflowRunStatus.FAILED,
        StopReason.CONCURRENCY_CONFLICT: WorkflowRunStatus.FAILED,
        StopReason.OUTPUT_VALIDATION_FAILED: WorkflowRunStatus.FAILED,
        StopReason.WORKER_LOST: WorkflowRunStatus.FAILED,
    }
)

# QUEUED/RUNNING are pre-stop states: no stop_reason can structurally target
# them (a stop_reason records how a loop ENDED). Named explicitly so the
# reverse-totality test can assert this is *exactly* the exception set, not
# an accident that also swallows a real regression (e.g. FAILED silently
# losing every mapped reason).
NON_TERMINAL_STATUSES: frozenset[WorkflowRunStatus] = frozenset(
    {WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING}
)


def status_for(reason: StopReason) -> WorkflowRunStatus:
    """The `WorkflowRunStatus` a run lands in for a given `stop_reason`.

    Raises `KeyError` for anything not in `STOP_REASON_TO_STATUS` — callers
    must not guess a fallback status; an unmapped `stop_reason` is a defect
    the total-mapping test is designed to catch before this ever runs.
    """
    return STOP_REASON_TO_STATUS[reason]
