"""`EventSink` protocol + `InMemoryEventSink` tests for #1125 / AGT-W3B
(ADR-074 decisions 1, 3, and 6).

No database, no network -- pure Python. Asserts the protocol is
structurally typed (an unrelated class satisfies it via `isinstance` with
no shared base class), that `InMemoryEventSink` satisfies it, that emit
order is preserved and queryable, and that `emit`'s signature takes only a
fully-constructed event -- nothing here mints or accepts a bare
`sequence_number` (ADR-074 decision 1: only the runner does that).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import UTC, datetime

from juli_backend.services.agent.events.envelope import AssistantTextEvent, WorkflowStatusEvent
from juli_backend.services.agent.events.payloads import AssistantTextPayload, WorkflowStatusPayload
from juli_backend.services.agent.events.sink import EventSink, InMemoryEventSink

RUN_ID = uuid.uuid4()


def _text_event(seq: int, text: str) -> AssistantTextEvent:
    return AssistantTextEvent(
        workflow_run_id=RUN_ID,
        sequence_number=seq,
        event_type="assistant.text",
        timestamp=datetime.now(UTC),
        payload=AssistantTextPayload(text=text),
        v=1,
    )


def _status_event(seq: int, narration: str) -> WorkflowStatusEvent:
    return WorkflowStatusEvent(
        workflow_run_id=RUN_ID,
        sequence_number=seq,
        event_type="workflow.status",
        timestamp=datetime.now(UTC),
        payload=WorkflowStatusPayload(phase_narration=narration),
        v=1,
    )


def test_in_memory_sink_satisfies_event_sink_protocol_via_isinstance():
    sink = InMemoryEventSink()
    assert isinstance(sink, EventSink)


def test_arbitrary_structurally_matching_class_satisfies_protocol_with_no_shared_base():
    """The whole point of a runtime_checkable Protocol: an unrelated class
    with no inheritance from EventSink still satisfies the isinstance check
    purely by having a matching `emit` method -- proving the runner and
    P8-3's PersistingEventSink can each depend on this independently."""

    class SomeUnrelatedSink:
        async def emit(self, event) -> None:
            pass

    assert isinstance(SomeUnrelatedSink(), EventSink)


def test_class_missing_emit_does_not_satisfy_protocol():
    class NotASink:
        async def not_emit(self, event) -> None:
            pass

    assert not isinstance(NotASink(), EventSink)


def test_in_memory_sink_records_events_in_emission_order():
    sink = InMemoryEventSink()
    e0 = _status_event(0, "starting")
    e1 = _text_event(1, "hello")
    e2 = _status_event(2, "finishing")

    asyncio.run(sink.emit(e0))
    asyncio.run(sink.emit(e1))
    asyncio.run(sink.emit(e2))

    assert sink.events == (e0, e1, e2)
    assert [e.payload.model_dump() for e in sink.events if e.event_type == "workflow.status"] == [
        {"phase_narration": "starting"},
        {"phase_narration": "finishing"},
    ]


def test_in_memory_sink_starts_empty():
    sink = InMemoryEventSink()
    assert sink.events == ()


def test_in_memory_sink_events_property_is_a_snapshot_not_the_live_list():
    sink = InMemoryEventSink()
    asyncio.run(sink.emit(_text_event(0, "a")))
    snapshot = sink.events
    asyncio.run(sink.emit(_text_event(1, "b")))
    assert snapshot == (snapshot[0],)
    assert len(sink.events) == 2


def test_emit_signature_takes_only_the_event_no_bare_sequence_number():
    """This layer never mints sequence numbers (ADR-074 decision 1) -- a
    sink whose `emit` signature invites a caller to pass one separately
    would be wrong. `emit` accepts exactly one caller-supplied argument:
    the already-numbered event."""
    params = list(inspect.signature(InMemoryEventSink.emit).parameters)
    assert params == ["self", "event"]
    assert "sequence_number" not in params
    assert "seq" not in params
