"""`api/routes/agent_runs.py`'s small locally-reproduced helpers -- ADR-074
decision 3, #1128 / AGT-W3B.

`agent_runs.py` never imports `services.agent.events.*` or
`services.agent.runner.*` (the import-boundary contract, MMU-2/#552,
`.importlinter.toml`, caps a cross-package import from `api` at depth 2;
those modules sit at depth 3-4). Four things it would otherwise reach into
that subtree for -- the Redis channel name format, the `DATABASE_URL`
resolution `workers/tasks/database.py` already does, and the
terminal-status/terminal-event-type vocabulary -- are reproduced locally in
the route module instead. This file (unscanned by the import-boundary
checker, which only scans `backend/src/juli_backend`) cross-checks all four
reproductions against their real, canonical definitions so they cannot
silently drift: each test below recomputes the expected value from the real
module and asserts equality against `agent_runs`'s local copy, so mutating
the canonical source (e.g. `NON_TERMINAL_STATUSES` in
`services/agent/runner/status.py`) turns the matching test red rather than
leaving it green on a stale hardcoded expectation.

The live-subscription seam (`EventSubscriber`/`_RedisEventSubscriber`) is
different in kind, not just missing a check: it is not a reproduction of an
existing canonical definition elsewhere in `services/agent/events/` (that
module was deleted from this slice once the import-boundary constraint was
understood -- see `agent_runs.py`'s module docstring) -- it *is* the
definition, now living here. There is nothing outside this file for it to
drift from, so only its externally-observable behavior (`None` when
`REDIS_URL` is unset, a real subscriber instance otherwise) is asserted
below, not a drift check against a second copy.
"""

from __future__ import annotations

import uuid

from juli_backend.api.routes.agent_runs import (
    TERMINAL_EVENT_TYPES,
    TERMINAL_RUN_STATUSES,
    EventSubscriber,
    _RedisEventSubscriber,
    _resolve_async_database_url,
    _resolve_redis_event_subscriber,
    _run_events_channel,
)
from juli_backend.services.agent.events.envelope import (
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
)
from juli_backend.services.agent.events.persisting_sink import run_events_channel
from juli_backend.services.agent.runner.status import (
    NON_TERMINAL_STATUSES,
    WorkflowRunStatus,
)
from juli_backend.workers.tasks.database import get_async_database_url


def test_run_events_channel_matches_persisting_sink_format():
    run_id = uuid.uuid4()

    assert _run_events_channel(run_id) == run_events_channel(run_id)


def test_resolve_async_database_url_matches_worker_task_helper(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _resolve_async_database_url() == get_async_database_url()

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    assert _resolve_async_database_url() == get_async_database_url()


def test_resolve_redis_event_subscriber_none_when_redis_url_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    assert _resolve_redis_event_subscriber() is None


def test_resolve_redis_event_subscriber_returns_subscriber_when_redis_url_set(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    subscriber = _resolve_redis_event_subscriber()

    assert isinstance(subscriber, _RedisEventSubscriber)
    assert isinstance(subscriber, EventSubscriber)


def test_terminal_run_statuses_match_canonical_vocabulary():
    """Recomputes the canonical terminal set from `WorkflowRunStatus` and
    `NON_TERMINAL_STATUSES` (the real source, `services/agent/runner/
    status.py`) rather than hardcoding it a second time here -- a run is
    terminal iff its status is neither a pre-stop member
    (`NON_TERMINAL_STATUSES` -- `QUEUED`/`RUNNING`) nor `WAITING_APPROVAL`
    (mid-run, not terminal). If that source is ever mutated (e.g.
    `CANCELLED` added to `NON_TERMINAL_STATUSES`, making it no longer
    terminal per the canonical vocabulary) and `agent_runs.
    TERMINAL_RUN_STATUSES` is not updated to match, this goes red."""
    non_terminal = {member.value for member in NON_TERMINAL_STATUSES}
    canonical_terminal = (
        {member.value for member in WorkflowRunStatus}
        - non_terminal
        - {WorkflowRunStatus.WAITING_APPROVAL.value}
    )

    assert TERMINAL_RUN_STATUSES == canonical_terminal


def test_terminal_event_types_match_envelope_definitions():
    """Recomputes the canonical terminal event-type pair from the real
    envelope classes' `event_type` `Literal` defaults (`services/agent/
    events/envelope.py`) rather than hardcoding them a second time here."""
    canonical_terminal_event_types = {
        WorkflowCompletedEvent.model_fields["event_type"].default,
        WorkflowFailedEvent.model_fields["event_type"].default,
    }

    assert TERMINAL_EVENT_TYPES == canonical_terminal_event_types
