"""Agent run transport routes -- the SSE event stream, cancel, and the
reserved confirmations shape (ADR-074 decisions 3 and 5, #1128 / AGT-W3B).

`GET /v1/demo/runs/{run_id}/events` streams a `workflow_runs` row's event
history over SSE. Mechanics, in the exact order ADR-074 decision 3 fixes:

1. Resolve `after_seq` from the `Last-Event-ID` header, else `?after=`,
   else `0`.
2. A run already terminal at connect time has no more live events coming --
   never subscribes, just replays its full history and closes (late joiners
   are free).
3. Otherwise: **subscribe before replay** -- this closes the gap a naive
   replay-then-subscribe implementation has between "replay ends" and
   "subscribe starts," where a concurrently-published live event would be
   lost forever (no buffering on the publish side once the message has
   gone out to zero subscribers). Subscribing first means any event
   committed and published from this point on is captured, whether replay's
   own Postgres read happens to catch it too (server-side dedupe drops the
   live redelivery) or not (the live leg delivers it once replay finishes).
4. Replay from Postgres in order, everything `> after_seq`.
5. Stream live events from the subscription, server-side deduped against a
   `last_sent` high-water mark -- clients never deduplicate; a failure here
   is this endpoint's bug, not a client's problem.
6. Heartbeat comment (`: heartbeat`) on an otherwise-idle stream, on the
   injected interval (15s default, ADR-074 decision 3).
7. A terminal event (`workflow.completed` or `workflow.failed`) closes the
   stream, from either leg.
8. If the subscribe call itself fails, degrade to polling Postgres on the
   injected interval (2s default) instead of failing the request -- Redis
   is optional for availability, not just correctness.

`POST /v1/demo/runs/{run_id}/cancel` returns `202` unconditionally once the
run is resolved under the caller's shop -- idempotent by construction (no
state read gates the response), so a repeat call or a call after the run is
already terminal never errors. The actual checkpoint-cancellation signal
into the `WorkflowRunner`'s run-state blob / a Celery task is W3-A/P9's
concern (`services/agent/runner/`, `workers/` are off-limits to this
slice) -- this route proves only the transport contract ADR-074 decision 5
fixes.

`POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}` is a **reserved
shape only**: it exists, tenant-scopes the run, and accepts a `{decision}`
body, but always answers `501` -- decision validation, consent binding and
any `run_confirmations` write are W4-A's authorization slice (ADR-074
decision 5). This route never authorizes and never mutates state.

Every route resolves the run under `get_active_shop` (`api/dependencies.py`,
the same idiom `api/routes/products.py` uses) and returns **404, never
403**, for a run belonging to another shop -- a 403 would confirm the run
exists at all (no existence oracle).
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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow

# This module deliberately never imports `services.agent.events.*` or
# `services.agent.runner.*`: the import-boundary contract (MMU-2/#552,
# `.importlinter.toml`) caps a cross-package import from `api` at
# `juli_backend.<top>.<direct_child>` (depth 2) -- `services.agent.events`
# is depth 3 and `services.agent.events.persisting_sink`/`.subscriber` or
# `services.agent.runner.status` are depth 4, all forbidden. The three
# small things this route would otherwise reach into that subtree for
# (the Redis channel name format, the terminal-status vocabulary, and the
# live-subscription seam) are reproduced locally below instead -- exactly
# the "prefer the route module" steer in this slice's own write-path
# constraints. Cross-checked for drift against the real definitions in
# `tests/unit/test_agent_run_events_stream.py` and
# `test_agent_run_events_api.py` (unscanned by the import-boundary
# checker, which only scans `backend/src/juli_backend`).

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/runs", tags=["agent-runs"])

# The two terminal event types (ADR-074 decision 2) -- either closes the
# stream, from replay, poll fallback or the live leg alike.
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"workflow.completed", "workflow.failed"})

# The `workflow_runs.status` values a run never leaves once reached --
# mirrors `services.agent.runner.status.WorkflowRunStatus` minus the two
# pre-stop members `QUEUED`/`RUNNING`, and minus `WAITING_APPROVAL` which is
# mid-run, not terminal. `workflow_runs.status` is a plain check-constrained
# string column (not a native DB enum), so these are exactly the values
# ever stored there for a finished run.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "timed_out", "failed"})

DEFAULT_HEARTBEAT_INTERVAL_S = 15.0
DEFAULT_POLL_INTERVAL_S = 2.0


def _run_events_channel(run_id: uuid.UUID) -> str:
    """Mirrors `services.agent.events.persisting_sink.run_events_channel`'s
    format exactly (not imported -- see the module-level import-boundary
    note above)."""
    return f"run_events:{run_id}"


# ---------------------------------------------------------------------------
# The live-subscription seam (ADR-074 decision 3). Structurally typed, the
# same pattern `events.sink.EventSink` and `events.persisting_sink.
# EventPublisher` use -- defined here rather than in `services/agent/
# events/` because the import-boundary contract makes that subtree
# unreachable from `api` beyond depth 2 (see the note above).
# ---------------------------------------------------------------------------


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
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return data

    async def close(self) -> None:
        await self._pubsub.aclose()


class _RedisEventSubscriber:
    """Production `EventSubscriber`: a fresh `redis.asyncio` client per
    subscribe call -- an SSE connection is comparatively rare and
    long-lived, so no connection-pool/singleton lifecycle to manage here."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def subscribe(self, channel: str) -> EventSubscription:
        import redis.asyncio as redis

        client = redis.from_url(self._redis_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        return _RedisEventSubscription(pubsub)


def _resolve_redis_event_subscriber() -> EventSubscriber | None:
    """`None` when `REDIS_URL` is unset -- Redis is optional for
    availability (ADR-074 decision 3): a caller seeing `None` degrades
    straight to Postgres polling without ever attempting a subscribe
    call."""
    url = (os.getenv("REDIS_URL", "") or "").strip()
    if not url:
        return None
    return _RedisEventSubscriber(url)


def _resolve_async_database_url() -> str:
    """Mirrors `workers/tasks/database.py::get_async_database_url` (not
    imported -- `workers.tasks.database` is a depth-3 cross-package import
    the import-boundary contract forbids from `api`; see the module-level
    note above): falls back to the same `sqlite+aiosqlite:///:memory:`
    unit-test default, and applies the same `postgresql://` ->
    `postgresql+asyncpg://` conversion."""
    raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    if raw_url.startswith("postgresql://"):
        raw_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw_url


# ---------------------------------------------------------------------------
# Dependencies -- every one overridable in tests, matching this codebase's
# `app.dependency_overrides[get_session] = ...` idiom.
# ---------------------------------------------------------------------------


async def get_run_events_session_factory() -> async_sessionmaker[AsyncSession]:
    """Production default: a worker-style session factory bound to
    `DATABASE_URL` (falls back to the `sqlite+aiosqlite:///:memory:` unit
    -test default when unset, `workers/tasks/database.py`'s existing
    convention). A per-request `Depends(get_session)` session is cleaned up
    before a `StreamingResponse` body finishes streaming (a well-known
    FastAPI gotcha), so the stream's ongoing replay/poll reads open their
    own sessions from this factory instead -- each read is a fresh session,
    same pattern `PersistingEventSink`'s own reads use.
    """
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_resolve_async_database_url())


def get_run_event_subscriber() -> EventSubscriber | None:
    return _resolve_redis_event_subscriber()


def get_heartbeat_interval_s() -> float:
    return DEFAULT_HEARTBEAT_INTERVAL_S


def get_poll_interval_s() -> float:
    return DEFAULT_POLL_INTERVAL_S


# ---------------------------------------------------------------------------
# Wire formatting and Postgres reads -- module-level functions so they are
# independently unit-testable without going through FastAPI at all.
# ---------------------------------------------------------------------------


def _row_to_envelope_json(row: WorkflowRunEventRow) -> str:
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


def _format_sse(sequence_number: int, event_type: str, data: str) -> str:
    return f"id: {sequence_number}\nevent: {event_type}\ndata: {data}\n\n"


async def _replay_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    after_seq: int,
) -> AsyncIterator[WorkflowRunEventRow]:
    """Everything `> after_seq` for `run_id`, strictly ordered, no gaps, no
    duplicates -- a fresh session per call (ADR-074 decision 1: Postgres is
    the replay authority)."""
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


async def _poll_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    since_seq: int,
    poll_interval_s: float,
) -> AsyncIterator[WorkflowRunEventRow]:
    """Redis-degraded fallback (ADR-074 decision 3, point 7): poll Postgres
    on `poll_interval_s` for anything new, forever, until a terminal event
    closes the stream (the caller stops iterating this generator then)."""
    last_seq = since_seq
    while True:
        async for row in _replay_events(session_factory, run_id, last_seq):
            yield row
            last_seq = row.sequence_number
            if row.event_type in TERMINAL_EVENT_TYPES:
                return
        await asyncio.sleep(poll_interval_s)


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
    """The SSE body generator -- independently testable without FastAPI or
    HTTP (see `tests/unit/test_agent_run_events_stream.py`)."""
    # A run already terminal at connect time can never produce another live
    # event: its terminal event already exists in the replay history.
    # Subscribing would be pure waste (and, per this slice's acceptance
    # criteria, must never even be attempted) -- replay in full and close.
    if run_is_terminal:
        async for row in _replay_events(session_factory, run_id, after_seq):
            yield _format_sse(row.sequence_number, row.event_type, _row_to_envelope_json(row))
        return

    channel = _run_events_channel(run_id)
    subscription: EventSubscription | None = None
    if subscriber is not None:
        try:
            subscription = await subscriber.subscribe(channel)
        except Exception:
            logger.warning(
                "run_events_subscribe_failed run_id=%s -- degrading to Postgres polling",
                run_id,
                exc_info=True,
            )
            subscription = None

    last_sent = after_seq
    terminal_reached = False
    try:
        async for row in _replay_events(session_factory, run_id, after_seq):
            yield _format_sse(row.sequence_number, row.event_type, _row_to_envelope_json(row))
            last_sent = row.sequence_number
            if row.event_type in TERMINAL_EVENT_TYPES:
                terminal_reached = True
                break

        if terminal_reached:
            return

        if subscription is None:
            async for row in _poll_events(session_factory, run_id, last_sent, poll_interval_s):
                yield _format_sse(row.sequence_number, row.event_type, _row_to_envelope_json(row))
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
            # Server-side dedupe (ADR-074 decision 3): a live event already
            # covered by replay, or already sent, is dropped here -- never
            # the client's job.
            if seq <= last_sent:
                continue
            yield _format_sse(seq, envelope["event_type"], raw)
            last_sent = seq
            if envelope["event_type"] in TERMINAL_EVENT_TYPES:
                return
    finally:
        if subscription is not None:
            await subscription.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


async def _resolve_owned_run(
    run_id: uuid.UUID, shop: Shop, session: AsyncSession
) -> WorkflowRunRow:
    """The shared tenant-scoping check every route in this module applies:
    a run belonging to another shop 404s, never 403s (no existence
    oracle -- ADR-074 decision 5)."""
    run = await session.get(WorkflowRunRow, run_id)
    if run is None or run.shop_id != shop.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_run_events_session_factory),
    subscriber: EventSubscriber | None = Depends(get_run_event_subscriber),
    heartbeat_interval_s: float = Depends(get_heartbeat_interval_s),
    poll_interval_s: float = Depends(get_poll_interval_s),
) -> StreamingResponse:
    run = await _resolve_owned_run(run_id, shop, session)

    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        after_seq = int(last_event_id)
    elif after is not None:
        after_seq = after
    else:
        after_seq = 0

    generator = event_stream(
        run_id=run_id,
        after_seq=after_seq,
        run_is_terminal=run.status in TERMINAL_RUN_STATUSES,
        session_factory=session_factory,
        subscriber=subscriber,
        heartbeat_interval_s=heartbeat_interval_s,
        poll_interval_s=poll_interval_s,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> None:
    """`202`, idempotent: resolving the run (404 for another shop's run) is
    the only gate. Calling this twice, or after the run is already
    terminal, never errors -- no state read decides the response."""
    await _resolve_owned_run(run_id, shop, session)
    return None


class ConfirmationDecisionRequest(BaseModel):
    decision: str


@router.post("/{run_id}/confirmations/{tool_call_id}")
async def submit_confirmation_decision(
    run_id: uuid.UUID,
    tool_call_id: str,
    body: ConfirmationDecisionRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Reserved shape only (ADR-074 decision 5). Tenant-scopes the run
    (404, never 403) and accepts a `{decision}` body, then always answers
    `501` -- decision validation, consent binding and any
    `run_confirmations` write are W4-A's. This route never authorizes and
    never mutates state."""
    await _resolve_owned_run(run_id, shop, session)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            f"Confirmation decisions for tool_call_id={tool_call_id!r} are not yet "
            "implemented -- decision authorization lands in a later slice (W4-A)."
        ),
    )
