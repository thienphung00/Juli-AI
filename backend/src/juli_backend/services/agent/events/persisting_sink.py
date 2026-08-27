"""`PersistingEventSink` -- the production `EventSink` (ADR-074 decision 3,
#1127 / AGT-W3B).

Order is the whole slice: INSERT the row, COMMIT it, THEN publish to
`run_events:{workflow_run_id}` on Redis. Postgres is the replay authority
(ADR-074 decision 1); Redis only makes delivery fast. A publish failure is
logged and swallowed -- liveness degrades (a live subscriber falls back to
polling/replay, a later slice's concern), correctness never does (the row
is already durable truth by the time publish is even attempted).

A replayed emit that collides on P8-1's unique
`(workflow_run_id, sequence_number)` index (`uq_workflow_run_events_run_sequence`,
`models/models.py`) is a no-op, not an error: a crash-replayed Celery task
(or a retried runner step) can call `emit` twice for the same sequence
number and get the same net effect as calling it once (ADR-074 decisions 1
and 3). On that collision this sink never reaches publish at all -- the
first (successful) emit already published the row's contents, and this
attempt contributed nothing new.

Redis wiring: `redis` is already a declared dependency
(`backend/pyproject.toml`), but this module never imports `redis.asyncio`
directly -- `PersistingEventSink` depends on the narrow `EventPublisher`
protocol below, satisfied structurally by `redis.asyncio.Redis` (its
`publish(channel, message)` coroutine matches the shape) with no adapter
class required. Concrete Redis-client wiring into the runner/Celery task
belongs to a later slice; this slice's unit tests inject a fake publisher
and need no real Redis connection, matching the InMemoryEventSink pattern
in `sink.py`.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.envelope import WorkflowRunEvent

logger = logging.getLogger(__name__)


@runtime_checkable
class EventPublisher(Protocol):
    """The narrow seam `PersistingEventSink` publishes through. Satisfied
    structurally by `redis.asyncio.Redis` (its `publish` coroutine matches)
    with no adapter required, and by any test fake exposing a matching
    `publish` method -- the same structurally-typed pattern `EventSink`
    itself uses (`sink.py`)."""

    async def publish(self, channel: str, message: str) -> Any: ...


def run_events_channel(workflow_run_id: Any) -> str:
    """The Redis channel name for a run's events (ADR-074 decision 3)."""
    return f"run_events:{workflow_run_id}"


class PersistingEventSink:
    """The production `EventSink`: INSERT + commit first -- the event now
    durably exists -- then best-effort publish (ADR-074 decision 3).
    Satisfies `events.sink.EventSink` structurally, no shared base class,
    the same way `InMemoryEventSink` does.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: EventPublisher,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher

    async def emit(self, event: WorkflowRunEvent) -> None:
        row = WorkflowRunEventRow(
            workflow_run_id=event.workflow_run_id,
            sequence_number=event.sequence_number,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=event.payload.model_dump(mode="json"),
            v=event.v,
        )
        async with self._session_factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                # Crash-replayed emit colliding on the unique
                # (workflow_run_id, sequence_number) index -- ADR-074
                # decisions 1/3: a no-op, not an error. The winning emit's
                # row is already committed and already published (or is
                # about to be, on its own call); this attempt contributed
                # nothing durable, so there is nothing left here to
                # publish either.
                await session.rollback()
                return

        # This line only runs after `await session.commit()` above has
        # returned successfully -- the row is now durably committed and
        # visible to any other session/connection before PUBLISH is ever
        # reached. From here on, publish is best-effort: a publish failure
        # is logged and swallowed, never re-raised and never a reason to
        # touch the row that already committed (ADR-074 decision 3).
        await publish_event_best_effort(self._publisher, event)


async def publish_event_best_effort(publisher, event: WorkflowRunEvent) -> None:
    """PUBLISH an already-committed event; never raise.

    Extracted from `PersistingEventSink.emit` so the crash handler in
    `workers/tasks/agent_workflow.py` publishes identically (#1396). That
    handler writes its own terminal `workflow.failed` row in one transaction
    with the run-status and action-card updates, so it cannot reuse `emit`
    (which commits its own session) — but it must not reimplement the publish,
    because two copies are how the two paths silently diverged: the crash path
    committed its event and never published it, leaving every connected SSE
    stream on heartbeats forever while the run was already dead.

    Call ONLY after the row is durably committed. Publish is best-effort by
    contract (ADR-074 decision 3): a failure is logged and swallowed, never
    re-raised, and never a reason to touch a row that already committed.
    Liveness degrades, correctness does not.
    """
    channel = run_events_channel(event.workflow_run_id)
    message = event.model_dump_json()
    try:
        await publisher.publish(channel, message)
    except Exception:
        logger.warning(
            "publish failed for workflow_run_id=%s sequence_number=%s "
            "(event already durably committed; liveness degrades, "
            "correctness does not)",
            event.workflow_run_id,
            event.sequence_number,
            exc_info=True,
        )
