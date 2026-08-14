"""`EventSink` protocol and an in-memory sink for tests/dev (ADR-074
decisions 1 and 3, #1125 / AGT-W3B).

This is the seam W3-A's `WorkflowRunner` (#1119) emits every
`WorkflowRunEvent` through, and P8-3's `PersistingEventSink` (INSERT +
commit, then best-effort Redis publish) implements independently against
the same protocol. Neither this module nor any caller mints
`sequence_number` -- the envelope already carries it (ADR-074 decision 1),
minted by the runner from its run-state blob; `emit` takes a
fully-constructed event, never a bare payload the sink would have to
number itself.

`emit` is async to match this codebase's async-first database access
pattern (`database/database.py`'s `AsyncSession`/`async_sessionmaker`, used
even by Celery workers via `ensure_worker_session_factory`, and
`LLMService.complete` in `services/agent/llm/service.py`) -- the production
sink's INSERT-then-commit-then-publish sequence is I/O-bound throughout.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from juli_backend.services.agent.events.envelope import WorkflowRunEvent


@runtime_checkable
class EventSink(Protocol):
    """One `emit`-shaped seam. Structurally typed (the `LLMService` pattern,
    `services/agent/llm/service.py`) so the runner and any concrete sink
    (this module's `InMemoryEventSink`, P8-3's `PersistingEventSink`) each
    satisfy it independently, with no shared base class."""

    async def emit(self, event: WorkflowRunEvent) -> None: ...


class InMemoryEventSink:
    """Records every emitted event in emission order, for tests and local
    dev -- not the persisting sink (P8-3 owns Postgres + Redis)."""

    def __init__(self) -> None:
        self._events: list[WorkflowRunEvent] = []

    async def emit(self, event: WorkflowRunEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> tuple[WorkflowRunEvent, ...]:
        return tuple(self._events)
