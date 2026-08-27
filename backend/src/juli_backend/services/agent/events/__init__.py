"""Agent event contracts -- the envelope, the typed 8-event union, and the
`EventSink` protocol (ADR-074, #1125 / AGT-W3B).

Public interface: import from here, not the submodules directly (the
`services/agent/llm` public-facade pattern this repo's ownership registry
`doNotImport` guidance names). Importing this package has no side effects
and makes no network access -- it is pure Pydantic model/Protocol
definitions.
"""

from __future__ import annotations

from juli_backend.services.agent.events.envelope import (
    EVENT_TYPES,
    AssistantTextEvent,
    ToolCompletedEvent,
    ToolStartedEvent,
    WorkflowApprovalRequiredEvent,
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
    WorkflowRunEvent,
    WorkflowRunEventAdapter,
    WorkflowStartedEvent,
    WorkflowStatusEvent,
)
from juli_backend.services.agent.events.payloads import (
    FAILURE_STOP_REASONS,
    AssistantTextPayload,
    ConfirmationOptionPayload,
    ToolCompletedPayload,
    ToolStartedPayload,
    WorkflowApprovalRequiredPayload,
    WorkflowCompletedPayload,
    WorkflowFailedPayload,
    WorkflowStartedPayload,
    WorkflowStatusPayload,
)
from juli_backend.services.agent.events.persisting_sink import (
    EventPublisher,
    PersistingEventSink,
    publish_event_best_effort,
    run_events_channel,
)
from juli_backend.services.agent.events.sink import EventSink, InMemoryEventSink

__all__ = [
    "EVENT_TYPES",
    "FAILURE_STOP_REASONS",
    "AssistantTextEvent",
    "AssistantTextPayload",
    "ConfirmationOptionPayload",
    "EventPublisher",
    "EventSink",
    "InMemoryEventSink",
    "PersistingEventSink",
    "publish_event_best_effort",
    "ToolCompletedEvent",
    "ToolCompletedPayload",
    "ToolStartedEvent",
    "ToolStartedPayload",
    "WorkflowApprovalRequiredEvent",
    "WorkflowApprovalRequiredPayload",
    "WorkflowCompletedEvent",
    "WorkflowCompletedPayload",
    "WorkflowFailedEvent",
    "WorkflowFailedPayload",
    "WorkflowRunEvent",
    "WorkflowRunEventAdapter",
    "WorkflowStartedEvent",
    "WorkflowStartedPayload",
    "WorkflowStatusEvent",
    "WorkflowStatusPayload",
    "run_events_channel",
]
