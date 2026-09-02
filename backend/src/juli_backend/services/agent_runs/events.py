"""The SSE event stream for one ``workflow_runs`` row (ADR-074 decision 3).

The ordering contract, in the order the code below applies it:

1. The replay cursor comes from ``Last-Event-ID``, else ``?after=``, else 0
   (:func:`resolve_after_seq`). A malformed or out-of-domain cursor degrades
   to the next source rather than erroring: ``StreamingResponse`` has already
   sent a 200 by the time the generator runs, so a raise there is a silently
   truncated body the client cannot detect or retry (#1142).
2. A run that is already terminal at connect time has no live events coming:
   replay its history and close. Never subscribe.
3. Otherwise **subscribe before replay**. A replay-then-subscribe order has a
   gap in which a live event published to zero subscribers is lost forever.
   Subscribing first captures anything committed from that point on; a live
   redelivery of an event replay also returned is dropped server-side by the
   ``seq <= last_sent`` check, never left to the client.
4. Replay everything ``> after_seq`` from Postgres, the replay authority.
5. Then the live leg: Redis pub/sub when available, else poll Postgres.
   Redis is optional for availability -- ``None`` subscriber means degrade
   straight to polling.
6. Either terminal event type closes the stream from any leg.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.core.async_db import async_database_url
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.envelope import WorkflowCompletedEvent, WorkflowFailedEvent
from juli_backend.services.agent.events.persisting_sink import run_events_channel
from juli_backend.services.agent.status import NON_TERMINAL_STATUSES, WorkflowRunStatus

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL_S = 15.0
DEFAULT_POLL_INTERVAL_S = 2.0

# Either terminal event closes the stream, whichever leg delivers it.
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        WorkflowCompletedEvent.model_fields["event_type"].default,
        WorkflowFailedEvent.model_fields["event_type"].default,
    }
)

# Statuses a run never leaves. WAITING_APPROVAL is mid-run (a CONFIRM pause),
# so it is neither in NON_TERMINAL_STATUSES nor terminal.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    status.value
    for status in WorkflowRunStatus
    if status not in NON_TERMINAL_STATUSES and status is not WorkflowRunStatus.WAITING_APPROVAL
)

# `workflow_run_events.sequence_number` is int4. A cursor above this overflows
# at asyncpg bind time inside the generator (see module docstring, point 1).
_INT4_MAX = 2_147_483_647


# -- live-subscription seam --------------------------------------------------


@runtime_checkable
class EventSubscription(Protocol):
    async def get_message(self, timeout: float) -> str | None: ...
    async def close(self) -> None: ...


@runtime_checkable
class EventSubscriber(Protocol):
    async def subscribe(self, channel: str) -> EventSubscription: ...


class _RedisEventSubscription:
    def __init__(self, pubsub: Any) -> None:
        self._pubsub = pubsub

    async def get_message(self, timeout: float) -> str | None:
        message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if message is None:
            return None
        data = message.get("data")
        return data.decode("utf-8") if isinstance(data, bytes) else data

    async def close(self) -> None:
        await self._pubsub.aclose()


class RedisEventSubscriber:
    """Production subscriber: a fresh ``redis.asyncio`` client per subscribe.

    SSE connections are rare and long-lived, so there is no pool or singleton
    to manage -- unlike the KPI caches' shared client.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def subscribe(self, channel: str) -> EventSubscription:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(self._redis_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        return _RedisEventSubscription(pubsub)


def resolve_redis_event_subscriber() -> EventSubscriber | None:
    """``None`` when ``REDIS_URL`` is unset: callers degrade to Postgres polling."""
    url = (os.getenv("REDIS_URL", "") or "").strip()
    return RedisEventSubscriber(url) if url else None


def run_events_database_url() -> str:
    """Async ``DATABASE_URL`` for the stream's own sessions; in-memory SQLite when unset.

    The stream cannot use the request-scoped session: FastAPI closes it before
    a ``StreamingResponse`` body finishes, so replay and poll open their own
    short sessions from a factory bound to this URL.
    """
    return async_database_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:"))


# -- cursor resolution -------------------------------------------------------


def clamp_sequence_cursor(value: int) -> int | None:
    """Bring a client cursor into int4's domain, or ``None`` if it cannot be used.

    Negative clamps to 0 (too low, still usable). Above int4 max returns
    ``None``: clamping *to* the max would replay nothing and look like
    success, which is the failure this exists to avoid.
    """
    if value > _INT4_MAX:
        return None
    return max(value, 0)


def resolve_after_seq(last_event_id: str | None, after: int | None) -> int:
    """``Last-Event-ID`` header, else ``?after=``, else 0 -- each degrading to the next."""
    if last_event_id is not None:
        try:
            resolved = clamp_sequence_cursor(int(last_event_id))
        except ValueError:
            resolved = None
        if resolved is not None:
            return resolved
    if after is not None:
        resolved = clamp_sequence_cursor(after)
        if resolved is not None:
            return resolved
    return 0


# -- wire format and Postgres reads ------------------------------------------


def row_to_envelope_json(row: WorkflowRunEventRow) -> str:
    timestamp = row.timestamp
    return json.dumps(
        {
            "workflow_run_id": str(row.workflow_run_id),
            "sequence_number": row.sequence_number,
            "event_type": row.event_type,
            "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
            "payload": row.payload,
            "v": row.v,
        },
        separators=(",", ":"),
    )


def format_sse(sequence_number: int, event_type: str, data: str) -> str:
    return f"id: {sequence_number}\nevent: {event_type}\ndata: {data}\n\n"


def _sse_for_row(row: WorkflowRunEventRow) -> str:
    return format_sse(row.sequence_number, row.event_type, row_to_envelope_json(row))


async def replay_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    after_seq: int,
) -> AsyncIterator[WorkflowRunEventRow]:
    """Every event ``> after_seq`` for ``run_id`` in order, from a fresh session."""
    async with session_factory() as session:
        result = await session.execute(
            select(WorkflowRunEventRow)
            .where(
                WorkflowRunEventRow.workflow_run_id == run_id,
                WorkflowRunEventRow.sequence_number > after_seq,
            )
            .order_by(WorkflowRunEventRow.sequence_number)
        )
        for row in result.scalars():
            yield row


async def poll_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    since_seq: int,
    poll_interval_s: float,
) -> AsyncIterator[WorkflowRunEventRow]:
    """Redis-degraded live leg: re-read Postgres every ``poll_interval_s`` until terminal."""
    last_seq = since_seq
    while True:
        async for row in replay_events(session_factory, run_id, last_seq):
            yield row
            last_seq = row.sequence_number
            if row.event_type in TERMINAL_EVENT_TYPES:
                return
        await asyncio.sleep(poll_interval_s)


# -- the stream --------------------------------------------------------------


async def event_stream(
    *,
    run_id: uuid.UUID,
    after_seq: int,
    run_is_terminal: bool,
    session_factory: async_sessionmaker[AsyncSession],
    subscriber: EventSubscriber | None,
    heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> AsyncIterator[str]:
    """The SSE body. Testable without FastAPI; see the module docstring for the contract."""
    if run_is_terminal:
        async for row in replay_events(session_factory, run_id, after_seq):
            yield _sse_for_row(row)
        return

    # First byte before the subscribe call (#1292): if the subscriber hangs,
    # the client still receives something immediately, so nginx/Cloudflare do
    # not buffer an empty response until they time out. A comment is not an
    # event and does not disturb the sequence numbering.
    yield ": connected\n\n"

    subscription = await _try_subscribe(subscriber, run_id)
    last_sent = after_seq
    try:
        async for row in replay_events(session_factory, run_id, after_seq):
            yield _sse_for_row(row)
            last_sent = row.sequence_number
            if row.event_type in TERMINAL_EVENT_TYPES:
                return

        if subscription is None:
            async for row in poll_events(session_factory, run_id, last_sent, poll_interval_s):
                yield _sse_for_row(row)
                if row.event_type in TERMINAL_EVENT_TYPES:
                    return
            return

        while True:
            raw = await subscription.get_message(timeout=heartbeat_interval_s)
            if raw is None:
                yield ": heartbeat\n\n"
                continue
            envelope = json.loads(raw)
            seq = envelope["sequence_number"]
            if seq <= last_sent:  # already sent by replay, or a redelivery
                continue
            yield format_sse(seq, envelope["event_type"], raw)
            last_sent = seq
            if envelope["event_type"] in TERMINAL_EVENT_TYPES:
                return
    finally:
        if subscription is not None:
            await subscription.close()


async def _try_subscribe(
    subscriber: EventSubscriber | None, run_id: uuid.UUID
) -> EventSubscription | None:
    if subscriber is None:
        return None
    try:
        return await subscriber.subscribe(run_events_channel(run_id))
    except Exception:  # availability boundary: any subscribe failure degrades to polling
        logger.warning(
            "run_events_subscribe_failed run_id=%s -- degrading to Postgres polling",
            run_id,
            exc_info=True,
        )
        return None


__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_S",
    "DEFAULT_POLL_INTERVAL_S",
    "TERMINAL_EVENT_TYPES",
    "TERMINAL_RUN_STATUSES",
    "EventSubscriber",
    "EventSubscription",
    "RedisEventSubscriber",
    "clamp_sequence_cursor",
    "event_stream",
    "format_sse",
    "poll_events",
    "replay_events",
    "resolve_after_seq",
    "resolve_redis_event_subscriber",
    "row_to_envelope_json",
    "run_events_channel",
    "run_events_database_url",
]
