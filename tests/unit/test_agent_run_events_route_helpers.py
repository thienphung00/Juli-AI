"""`api/routes/agent_runs.py`'s small locally-reproduced helpers -- ADR-074
decision 3, #1128 / AGT-W3B.

`agent_runs.py` never imports `services.agent.events.*` or
`services.agent.runner.*` (the import-boundary contract, MMU-2/#552,
`.importlinter.toml`, caps a cross-package import from `api` at depth 2;
those modules sit at depth 3-4). Three small things it would otherwise
reach into that subtree for -- the Redis channel name format, the
`DATABASE_URL` resolution `workers/tasks/database.py` already does, and the
Redis-subscriber-or-None seam -- are reproduced locally in the route module
instead. This file (unscanned by the import-boundary checker, which only
scans `backend/src/juli_backend`) cross-checks those reproductions against
the real definitions so they cannot silently drift.
"""

from __future__ import annotations

import uuid

from juli_backend.api.routes.agent_runs import (
    EventSubscriber,
    _RedisEventSubscriber,
    _resolve_async_database_url,
    _resolve_redis_event_subscriber,
    _run_events_channel,
)
from juli_backend.services.agent.events.persisting_sink import run_events_channel
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
