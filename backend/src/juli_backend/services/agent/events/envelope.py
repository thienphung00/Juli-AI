"""The `workflow_run_events` Pydantic envelope and the typed 8-event union
(ADR-074 decision 2, #1125 / AGT-W3B).

`{workflow_run_id, sequence_number, event_type, timestamp, payload, v: 1}`
-- `v` is required and pinned to the literal `1` (no default): a missing or
mismatched `v` fails validation rather than silently defaulting, since this
is the field a client uses to detect a protocol version it doesn't
understand (ADR-074 consequences).

Sequence numbers are minted by the `WorkflowRunner` from its run-state blob
(ADR-074 decision 1) -- nothing in this module assigns one; every envelope
class here takes `sequence_number` as a plain required field, same as every
other field on the envelope.

`assistant.text.delta` was reserved by ADR-071 decision 3 and is now a
member (ADR-071 amendment, D71.3 / P61-C): a persisted, coalesced preview of
a streamed turn's text that the following `assistant.text` supersedes. It
is additive -- a client that does not know it skips it, every other
member's shape is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from juli_backend.services.agent.events.payloads import (
    AssistantTextDeltaPayload,
    AssistantTextPayload,
    ToolCompletedPayload,
    ToolStartedPayload,
    WorkflowApprovalRequiredPayload,
    WorkflowCompletedPayload,
    WorkflowFailedPayload,
    WorkflowStartedPayload,
    WorkflowStatusPayload,
)


class _EventEnvelope(BaseModel):
    """Fields common to every envelope, minus the per-type discriminant
    (`event_type`) and payload -- each subclass below adds those two."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: uuid.UUID
    sequence_number: int
    timestamp: datetime
    v: Literal[1]


class WorkflowStartedEvent(_EventEnvelope):
    event_type: Literal["workflow.started"] = "workflow.started"
    payload: WorkflowStartedPayload


class WorkflowStatusEvent(_EventEnvelope):
    event_type: Literal["workflow.status"] = "workflow.status"
    payload: WorkflowStatusPayload


class AssistantTextEvent(_EventEnvelope):
    event_type: Literal["assistant.text"] = "assistant.text"
    payload: AssistantTextPayload


class AssistantTextDeltaEvent(_EventEnvelope):
    event_type: Literal["assistant.text.delta"] = "assistant.text.delta"
    payload: AssistantTextDeltaPayload


class ToolStartedEvent(_EventEnvelope):
    event_type: Literal["tool.started"] = "tool.started"
    payload: ToolStartedPayload


class ToolCompletedEvent(_EventEnvelope):
    event_type: Literal["tool.completed"] = "tool.completed"
    payload: ToolCompletedPayload


class WorkflowApprovalRequiredEvent(_EventEnvelope):
    event_type: Literal["workflow.approval_required"] = "workflow.approval_required"
    payload: WorkflowApprovalRequiredPayload


class WorkflowCompletedEvent(_EventEnvelope):
    event_type: Literal["workflow.completed"] = "workflow.completed"
    payload: WorkflowCompletedPayload


class WorkflowFailedEvent(_EventEnvelope):
    event_type: Literal["workflow.failed"] = "workflow.failed"
    payload: WorkflowFailedPayload


# The discriminated union -- the complete, closed set of nine event types.
# `assistant.text.delta` joined by the ADR-071 amendment (D71.3 / P61-C);
# any further member is a renegotiation of the protocol shape, not a bugfix.
WorkflowRunEvent = Annotated[
    WorkflowStartedEvent
    | WorkflowStatusEvent
    | AssistantTextEvent
    | AssistantTextDeltaEvent
    | ToolStartedEvent
    | ToolCompletedEvent
    | WorkflowApprovalRequiredEvent
    | WorkflowCompletedEvent
    | WorkflowFailedEvent,
    Field(discriminator="event_type"),
]

WorkflowRunEventAdapter: TypeAdapter[WorkflowRunEvent] = TypeAdapter(WorkflowRunEvent)

EVENT_TYPES: tuple[str, ...] = (
    "workflow.started",
    "workflow.status",
    "assistant.text",
    "assistant.text.delta",
    "tool.started",
    "tool.completed",
    "workflow.approval_required",
    "workflow.completed",
    "workflow.failed",
)
