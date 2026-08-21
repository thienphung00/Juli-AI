"""Payload models for the eight `workflow_run_events` event types (ADR-074
decision 2, #1125 / AGT-W3B).

Each payload carries exactly the fields ADR-074 d.2 names for its event
type — no more, no less (`extra="forbid"`, every field required). Pairing
these with `envelope.py`'s per-type envelope classes is what makes
`assistant.text.delta` (ADR-071 reserved, never implemented here)
structurally unconstructable: there is no payload model, no envelope class,
and no discriminant literal for it anywhere in this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from juli_backend.services.agent.status import (
    STOP_REASON_TO_STATUS,
    StopReason,
    WorkflowRunStatus,
)

# The failure-class `stop_reason` members `workflow.failed` may carry --
# every `StopReason` whose ADR-073 total mapping targets a failure-shaped
# `WorkflowRunStatus` (`cancelled`, `timed_out`, `failed`). Derived from the
# mapping itself (not hand-duplicated) so it can never drift from
# `STOP_REASON_TO_STATUS` -- ADR-073 stays the single authority for the
# precision (ADR-074 d.2).
_FAILURE_STATUSES = frozenset(
    {WorkflowRunStatus.CANCELLED, WorkflowRunStatus.TIMED_OUT, WorkflowRunStatus.FAILED}
)
FAILURE_STOP_REASONS: frozenset[StopReason] = frozenset(
    reason for reason, status in STOP_REASON_TO_STATUS.items() if status in _FAILURE_STATUSES
)


class _EventPayload(BaseModel):
    """Shared config: forbid unknown fields so a typo or scope-creep field
    fails loudly instead of round-tripping silently."""

    model_config = ConfigDict(extra="forbid")


class WorkflowStartedPayload(_EventPayload):
    workflow_key: str
    product_ref: str
    prompt_version: str


class WorkflowStatusPayload(_EventPayload):
    """`phase_narration` is VI-locale copy describing the run's current
    phase. The runner also emits this same event type (same single field)
    to make an iteration-cap extension grant visible on the stream
    (ADR-073 decision 2 / ADR-074 d.2) -- there is no separate "extension"
    field; the grant is narrated through this one free-text field."""

    phase_narration: str


class AssistantTextPayload(_EventPayload):
    text: str


class ToolStartedPayload(_EventPayload):
    tool_call_id: str
    tool_name: str


class ToolCompletedPayload(_EventPayload):
    tool_call_id: str
    tool_name: str
    ok: bool
    summary: str


class WorkflowApprovalRequiredPayload(_EventPayload):
    tool_call_id: str
    tool_name: str
    proposed_change: dict[str, Any]
    expires_at: datetime


class WorkflowCompletedPayload(_EventPayload):
    stop_reason: StopReason


class WorkflowFailedPayload(_EventPayload):
    """The failure-class terminal covering `failed`/`cancelled`/`timed_out`
    (ADR-074 d.2) -- `status` is the client-rendered terminal shape,
    `stop_reason` carries the precision. ADR-073's total `stop_reason` ->
    `WorkflowRunStatus` mapping stays the single authority: both the
    stop_reason's membership in the failure class and its exact mapped
    status are enforced here, not re-derived."""

    status: WorkflowRunStatus
    stop_reason: StopReason

    @model_validator(mode="after")
    def _stop_reason_is_failure_class_and_matches_status(self) -> WorkflowFailedPayload:
        if self.stop_reason not in FAILURE_STOP_REASONS:
            raise ValueError(
                "workflow.failed stop_reason must be one of the failure-class "
                f"members {sorted(r.value for r in FAILURE_STOP_REASONS)}, got "
                f"{self.stop_reason!r}"
            )
        expected_status = STOP_REASON_TO_STATUS[self.stop_reason]
        if self.status != expected_status:
            raise ValueError(
                f"workflow.failed status {self.status!r} does not match "
                f"ADR-073's mapped status {expected_status!r} for stop_reason "
                f"{self.stop_reason!r}"
            )
        return self
