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
state read gates the *response*), so a repeat call or a call after the run
is already terminal never errors. Issue #1145 Gap 3: it also sets
`workflow_runs.cancel_requested = True` -- the actual checkpoint-
cancellation signal. `WorkflowRunner.cancel_check` (constructor-injected,
`services/agent/runner/core.py`) is polled at every checkpoint
(`termination.evaluate_checkpoint`); `workers/tasks/agent_workflow.py::
_construct_runner` wires a `cancel_check` that reads this column fresh from
the database on every poll -- a cached read would defeat the mechanism,
since the API process writes the flag and the worker process reads it.

`POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}` authorizes and
resolves a seller's decision on a CONFIRM-policy pause (ADR-075 decision 2,
issue #1224 / AGT-W5A). The fail-closed, ordered ladder, each rung its own
status:

1. the run belongs to the caller's shop -- else `404` (never `403`; no
   existence oracle).
2. the run is `waiting_approval` -- else `409`.
3. `tool_call_id` names a `run_confirmations` row for this run -- else
   `404`; if that row is no longer `pending` (already decided) -- `409`;
   if it is `expired` -- `410`.
4. the confirmation has not passed its `expires_at` wall clock, even if
   the reaper (`workers/tasks/reaper.py`) has not yet swept it -- else
   `410`, and this endpoint leaves the run and the row alone for the
   reaper to finish (never force-terminates).

On `approve`, `option_id` must name one of the confirmation's stored
options, and the resume path re-derives that option's `params_sha`
(`services.agent.runner.compute_params_sha`, re-exported at the runner
package's own depth-2-facade boundary -- never reimplemented here) from
the run's *reconstructed* state (`workflow_runs.state["pending_confirmation"]
["arguments"]`, the same raw blob `WorkflowRunner.resume` itself reads) --
a mismatch is a hard failure (`409`), and the tool is never dispatched: the
confirmation row is left `pending` and `resume_agent_workflow` is never
enqueued, so `ToolExecutor.execute` is structurally unreachable on this
path.

Single-use: the confirmation row's `pending -> approved(option_id) |
declined` transition is an atomic, conditional `UPDATE ... WHERE
status = 'pending'` -- a race between two concurrent decisions on the same
confirmation yields exactly one committed transition (rowcount 1) and one
loser (rowcount 0, translated to `409`, no enqueue). The transition is
always committed *before* `resume_agent_workflow` is enqueued -- never the
reverse, which would let a worker observe the row still `pending` mid-flight
(the exact `IntegrityError` #1221's review reproduced against a second,
sequential CONFIRM pause on the same run).

`POST /v1/demo/runs` was issue #1145's Gap 2 fix -- it created a
`workflow_runs` row directly from a caller-supplied `product_id`, with no
ActionCard involved. **Removed in #1222** (ADR-075 decision 1: "No 'create
run' endpoint and no `approval_id` parameter exist on the agent path" --
a standalone endpoint taking a bare `product_id` is exactly the
caller-supplied-authority-claim shape that decision forbids, independent of
whether it also required a card argument). `POST
/v1/demo/decisions/{action_card_id}/approve`
(`api/routes/demo_execution.py`) is now the only way a `workflow_runs` row
comes into existence; it reuses `_enqueue_run_agent_workflow` below (the one
piece of this removed section still worth sharing -- lazy-import-then-
`.delay()` is identical regardless of what created the row) via a plain
intra-package import, and derives its own `product_id` server-side
(ADR-082) rather than accepting one. `_build_initial_run_state`/
`_resolve_optimize_product_prompt_pin`, this route's other two Gap-2
helpers, are NOT reused here: services/agent/approval.py (the new
transaction module) cannot import this `api`-package module at all (the
import-boundary contract only allows `api -> services`, never the reverse),
so it carries its own equivalents, built directly from the ActionCard
already in hand rather than a heuristic re-query for "the most recent card
for this workflow".

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
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.models.models import Product, RunConfirmation
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent import abuse_limits as agent_abuse_limits

# This module deliberately never imports `services.agent.events.*` or
# `services.agent.runner.*`: the import-boundary contract (MMU-2/#552,
# `.importlinter.toml`) caps a cross-package import from `api` at
# `juli_backend.<top>.<direct_child>` (depth 2) -- `services.agent.events`
# is depth 3 and `services.agent.events.persisting_sink` or
# `services.agent.runner.core` are depth 4, all forbidden. (The
# `WorkflowRunStatus`/`StopReason` vocabulary relocated out of the runner to
# `services.agent.status` in #1139 — depth 3, so still forbidden here.) Four things
# this route would otherwise reach into that subtree for are reproduced
# locally below instead -- exactly the "prefer the route module" steer in
# this slice's own write-path constraints. Precisely what is guarded
# against drift, and how, in `tests/unit/test_agent_run_events_route_helpers.py`
# (unscanned by the import-boundary checker, which only scans
# `backend/src/juli_backend`):
#   - `_run_events_channel` -- cross-checked against
#     `persisting_sink.run_events_channel`'s real output.
#   - `_resolve_async_database_url` -- cross-checked against
#     `workers/tasks/database.py::get_async_database_url`'s real output.
#   - `TERMINAL_RUN_STATUSES` -- cross-checked against a value recomputed
#     from the real `WorkflowRunStatus`/`NON_TERMINAL_STATUSES`
#     (`services/agent/status.py`), not hardcoded a second time.
#   - `TERMINAL_EVENT_TYPES` -- cross-checked against the real
#     `WorkflowCompletedEvent`/`WorkflowFailedEvent` `event_type` literals
#     (`services/agent/events/envelope.py`).
#   - `EventSubscriber`/`_RedisEventSubscriber` (the live-subscription
#     seam) are NOT a reproduction of anything and have no drift check:
#     `services/agent/events/subscriber.py` was deleted from this slice
#     once this import-boundary constraint was understood, so this *is*
#     the definition, not a copy of one. Only its externally-observable
#     behavior (`None` when `REDIS_URL` is unset, a real subscriber
#     instance otherwise) is tested.

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo/runs", tags=["agent-runs"])

# The two terminal event types (ADR-074 decision 2) -- either closes the
# stream, from replay, poll fallback or the live leg alike.
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"workflow.completed", "workflow.failed"})

# The `workflow_runs.status` values a run never leaves once reached --
# mirrors `services.agent.status.WorkflowRunStatus` minus the two
# pre-stop members `QUEUED`/`RUNNING`, and minus `WAITING_APPROVAL` which is
# mid-run, not terminal. `workflow_runs.status` is a plain check-constrained
# string column (not a native DB enum), so these are exactly the values
# ever stored there for a finished run.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "timed_out", "failed"})

# `workflow_runs.status` value a run occupies while a CONFIRM-policy pause
# awaits a seller decision -- mirrors `services.agent.status
# .WorkflowRunStatus.WAITING_APPROVAL.value`, a plain literal for the same
# reason `TERMINAL_RUN_STATUSES` above is: `services.agent.status` is a
# depth-3 cross-package import from `api`, forbidden by
# `.importlinter.toml` (see the module docstring's import-boundary note).
WAITING_APPROVAL_RUN_STATUS = "waiting_approval"

# `run_confirmations.status` values (migration `039_run_confirmations`,
# `models.models.RunConfirmation`) -- same "plain literal, not an import"
# reasoning as `WAITING_APPROVAL_RUN_STATUS` above.
PENDING_CONFIRMATION_STATUS = "pending"

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

    # Issue #1292: emit the connected comment immediately BEFORE subscribing,
    # so that if the subscriber hangs or blocks, the first byte reaches the
    # client immediately, preventing the edge (nginx/Cloudflare) from buffering
    # indefinitely and timing out. This is safe because the comment is not an
    # event (does not increment sequence numbering) and does not disturb
    # ADR-074 decision 3's ordering guarantees (subscribe-before-replay still
    # happens for capturing live events; the comment just precedes the subscribe
    # call itself, not the actual subscribe completion that starts receiving).
    yield ": connected\n\n"

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
# Enqueue helper (issue #1145 Gap 2, originally). The row-creation half of
# Gap 2 (`create_run` / `POST /v1/demo/runs`, plus its
# `_resolve_optimize_product_prompt_pin` / `_build_initial_run_state`
# helpers) was REMOVED in #1222 -- see this module's own docstring, top of
# file, for why a standalone create-run endpoint is exactly what ADR-075
# decision 1 forbids. `_enqueue_run_agent_workflow` survives because it has
# nothing to do with where the row came from: `api/routes/demo_execution.py`
# (the sole remaining creator, via `POST
# /v1/demo/decisions/{action_card_id}/approve`) imports it directly from
# here rather than duplicating the lazy-import-then-`.delay()` idiom.
# ---------------------------------------------------------------------------


def _enqueue_run_agent_workflow(run_id: uuid.UUID) -> str:
    """Enqueue `run_agent_workflow` for `run_id` -- the same lazy-import-
    then-`.delay()` idiom `workers/dispatch_binding.py` uses for
    `refresh_action_cards.delay(...)` / `execute_approved_tool.delay(...)`.
    Reached via `from juli_backend.workers.tasks import agent_workflow as
    <alias>` rather than a direct submodule import: `api` and `workers` are
    different top-level packages, so the cross-package depth-2 cap
    (`.importlinter.toml`, `max_cross_package_depth = 2`) applies here in a
    way it does not for `dispatch_binding.py` (same package as its target).
    """
    from juli_backend.workers.tasks import agent_workflow as agent_workflow_tasks

    async_result = agent_workflow_tasks.run_agent_workflow.delay(str(run_id))
    return async_result.id


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


# `sequence_number` is Postgres `int4` (models.py). A cursor value outside
# that domain would either overflow when asyncpg binds it (a huge value --
# uncaught, and StreamingResponse has already committed HTTP 200 by the
# time the generator raises, so the client would see a silently truncated
# empty 200 body: undetectable, unretryable, #1142 rework) or is simply not
# a real cursor (negative -- sequence numbers start at 1).
_INT4_MAX = 2_147_483_647


def _clamp_sequence_cursor(value: int) -> int | None:
    """Bring a client-supplied replay cursor into `int4`'s domain, or signal
    that it cannot be used at all.

    - Negative clamps down to `0` (the lowest real cursor) -- the value is
      still usable, just too low, so the caller keeps it rather than
      falling through to the next cursor source.
    - Greater than `int4`'s max returns `None`: no real `sequence_number`
      is ever that large, and clamping it *to* the max would silently
      replay nothing (`sequence_number > _INT4_MAX` never matches) --
      exactly the wrong "recovered but empty" failure this issue exists to
      avoid. The honest degrade for an impossible-high value is the same
      as a malformed one: the caller falls through to the next cursor
      source, same as `int()` raising `ValueError`.
    """
    if value > _INT4_MAX:
        return None
    return max(value, 0)


async def _sse_stream_with_concurrency_slot(
    generator: AsyncIterator[str],
    *,
    gate: agent_abuse_limits.AbuseLimitGate,
    shop_id: str,
) -> AsyncIterator[str]:
    """Wraps `event_stream`'s generator so the SSE concurrency slot
    `stream_run_events` already acquired is always released -- ADR-075
    decision 4 / #1223: "SSE is concurrency, not rate."

    The `finally` below runs on every exit path a Python generator can
    take, which covers two of the three ways this slot needs to be
    released:

    - clean end -- `event_stream` returns normally, either after a terminal
      event or (the already-terminal-at-connect case) after a pure replay.
    - the run terminating mid-stream -- the same "clean end" path above;
      `event_stream` itself returns as soon as it sees a terminal event, no
      different signal needed here.

    **An abnormal client disconnect is the third path, and it does NOT run
    through a synchronous `.aclose()` call from Starlette.** Checked
    directly against the installed `starlette.responses.StreamingResponse`
    source (`inspect.getsource`) rather than assumed: it never calls
    `.aclose()` on its body iterator anywhere. What actually happens
    depends on the ASGI spec version the server negotiates:

    - **`spec_version >= (2, 4)`** (what a current uvicorn negotiates):
      `stream_response` does `async for chunk in self.body_iterator: ...
      await send(chunk)` -- note `send(chunk)` is OUTSIDE the `async for`'s
      own `__anext__()` call. A disconnected socket makes `send()` raise
      `OSError`, which is caught one level up in `__call__` and re-raised
      as `ClientDisconnect()`. This generator was never re-entered to
      receive that error -- it is simply abandoned, mid-suspension, at
      whatever `yield` it last returned from. The `finally` below does NOT
      fire synchronously with the disconnect in this path. Release then
      depends on CPython's async-generator GC finalizer eventually
      scheduling `.aclose()` once nothing references this generator object
      anymore (`sys.set_asyncgen_hooks`, wired up by asyncio) -- real, but
      indirect and not deterministic in timing.
    - **`spec_version < (2, 4)`** (the legacy anyio-task-group path):
      `listen_for_disconnect` returning cancels the sibling task running
      `stream_response` via `task_group.cancel_scope.cancel()`. If that
      cancellation lands while this generator is itself suspended inside
      `event_stream` (awaiting a message, a DB read, or the heartbeat
      timeout -- the common case), `asyncio.CancelledError` is raised at
      exactly that suspension point, propagates through the `async for`
      below, and the `finally` DOES fire synchronously, same as any other
      exception.

    So the disconnect path's release is guaranteed-synchronous under task
    cancellation, best-effort-and-eventual under the modern
    `OSError`-from-`send()` path. `RedisAbuseLimitGate`'s (and the test
    double's) 1-hour safety TTL on the concurrency counter exists
    specifically to bound that worst case -- a leaked slot self-heals
    within the TTL window even if GC finalization is slow or never runs
    (e.g. the process is killed before a GC pass). `test_agent_abuse_limits_routes.py`
    proves the synchronous-release path directly by cancelling the asyncio
    task consuming this generator while it is suspended inside `event_stream`
    (the real `CancelledError` mechanism above), not by calling `.aclose()`
    -- see that test's own docstring for why an `.aclose()`-based test would
    have proven a mechanism Starlette does not actually use on disconnect.
    """
    try:
        async for chunk in generator:
            yield chunk
    finally:
        await gate.release_stream(shop_id)


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

    # ADR-075 decision 4 / #1223: SSE is a concurrency limit, not a rate
    # window -- 10 concurrent streams per shop. Acquired AFTER tenant
    # scoping above (a 404 for someone else's run must never consume a
    # slot) and released in `_sse_stream_with_concurrency_slot` below on
    # every exit path -- clean end, run termination, and client disconnect
    # alike (see that helper's own docstring for the disconnect proof).
    stream_gate = agent_abuse_limits.get_agent_abuse_limit_gate()
    stream_limit_decision = await stream_gate.try_acquire_stream(str(shop.id))
    if not stream_limit_decision.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop.id),
            operation=agent_abuse_limits.OPERATION_SSE,
            retry_after_seconds=stream_limit_decision.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many concurrent event streams for this shop; "
                f"retry in {stream_limit_decision.retry_after_seconds}s"
            ),
            headers={"Retry-After": str(stream_limit_decision.retry_after_seconds)},
        )

    last_event_id = request.headers.get("last-event-id")
    after_seq: int | None = None
    if last_event_id is not None:
        try:
            parsed = int(last_event_id)
        except ValueError:
            # A malformed Last-Event-ID is a client-supplied header on the
            # reconnect path (proxy rewrite/truncation, empty string after a
            # failed connect, a foreign SSE client echoing a non-numeric id).
            # Raising here would 500, and #1132's retry helper retries 500s
            # by design -- turning a bad cursor into an unrecoverable retry
            # loop. Degrade instead: fall through to ?after=, then to 0,
            # matching the precedence used when the header is absent.
            after_seq = None
        else:
            # int() has arbitrary precision -- a syntactically valid but
            # out-of-domain value (negative, or bigger than int4) needs the
            # same degrade care as a non-numeric one; see
            # `_clamp_sequence_cursor`.
            after_seq = _clamp_sequence_cursor(parsed)
    if after_seq is None:
        # `?after=` has the identical hole: `Query(..., ge=0)` bounds the
        # low end but not the high end, so a huge `?after=` value hits the
        # same int4 overflow at bind time. Give it the same treatment --
        # it is the last explicit cursor source, so "fall through" lands on
        # the same `0` default an unusable value would reach anyway.
        after_seq = _clamp_sequence_cursor(after) if after is not None else 0
        if after_seq is None:
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
    released_generator = _sse_stream_with_concurrency_slot(
        generator, gate=stream_gate, shop_id=str(shop.id)
    )
    # Issue #1292: belt-and-braces edge buffering fix -- the first byte
    # (connected comment) is emitted before subscribe in event_stream above,
    # and this header tells nginx/Cloudflare not to buffer the response at all.
    # Both together ensure first byte reaches the client immediately.
    return StreamingResponse(
        released_generator,
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> None:
    """`202`, idempotent: resolving the run (404 for another shop's run) is
    the only gate on the *response* -- calling this twice, or after the run
    is already terminal, never errors, since no state read gates what
    status code comes back.

    Issue #1145 Gap 3: sets `workflow_runs.cancel_requested = True`
    unconditionally once the run resolves -- setting it again on a repeat
    call, or on an already-terminal run, is a harmless no-op write (the
    column is already `True`, or nothing reads it again for a terminal
    run). `workers/tasks/agent_workflow.py::_construct_runner` wires a
    `cancel_check` that reads this column fresh from the database on every
    `WorkflowRunner` checkpoint poll -- that is the seam this write feeds.

    ADR-075 decision 4 / #1223: deliberately calls no `agent_abuse_limits`
    gate anywhere in this function -- cancel is never throttled, by never
    asking the question, not by the gate always answering yes. See
    `services.agent.abuse_limits`'s module docstring, "Cancel is exempt,
    structurally."
    """
    run = await _resolve_owned_run(run_id, shop, session)
    run.cancel_requested = True
    await session.commit()
    # #1145 Review: the one state-mutating route in this module that
    # previously logged nothing -- run_id/shop_id are both server-resolved
    # identifiers (run_id is a path parameter, shop comes from
    # get_active_shop), never request-body content.
    logger.info(
        "agent_run_cancel_requested",
        extra={"shop_id": str(shop.id), "run_id": str(run_id)},
    )
    return None


class ConfirmationDecisionRequest(BaseModel):
    decision: str
    option_id: str | None = None


class ConfirmationDecisionResponse(BaseModel):
    decision: str
    status: str
    celery_task_id: str


# Machine-readable discriminators carried inside `HTTPException.detail` for
# every error this endpoint raises on its OWN logic (never `_resolve_owned_run`'s
# shared tenant-scoping 404, which `/events` and `/cancel` also raise --
# changing that shared shape is out of this endpoint's scope). #1224 review
# finding: three of this endpoint's conditions all surfaced as a bare-string
# 409 -- "run not waiting_approval" (benign, retry later), "already decided"
# (benign double-submit, single-use), and a `params_sha` divergence, which
# ADR-075 decision 2 calls "a hard failure, not a warning" -- with no way for
# a caller to tell them apart short of parsing free text. This is additive:
# every HTTP status code stays exactly what it already was; `error_code` is a
# new key riding alongside the existing human-readable `message`, not a
# reclassification. No error-envelope convention exists elsewhere in this
# codebase to conform to instead (`.cursor/rules/patterns.mdc`'s
# `{status, data, error, metadata}` shape is aspirational and unused by any
# real route -- adopting it here would mean restructuring every response,
# including this endpoint's own 202 success shape, which is out of scope);
# every other route's error body stays FastAPI's default bare-string
# `{"detail": "..."}`, unaffected.
#
# The sequential "already decided on read" (rung 3) and the concurrent race
# loser (`_transition_confirmation_or_none` returning `False`) share ONE code
# deliberately: both are the identical client-observable fact -- "someone
# already decided this confirmation" -- detected at two different code paths,
# never two different facts.
ERROR_RUN_NOT_AWAITING_CONFIRMATION = "run_not_awaiting_confirmation"
ERROR_CONFIRMATION_NOT_FOUND = "confirmation_not_found"
ERROR_CONFIRMATION_ALREADY_DECIDED = "confirmation_already_decided"
ERROR_CONFIRMATION_EXPIRED = "confirmation_expired"
ERROR_INVALID_DECISION = "invalid_decision"
ERROR_OPTION_ID_REQUIRED = "option_id_required"
ERROR_UNKNOWN_OPTION_ID = "unknown_option_id"
ERROR_PARAMS_SHA_MISMATCH = "params_sha_mismatch"
ERROR_RUN_STATE_NOT_RECONSTRUCTABLE = "run_state_not_reconstructable"


def _confirmation_error(status_code: int, error_code: str, message: str) -> HTTPException:
    """Build this endpoint's error shape: `{"detail": {"message": ..., "error_code": ...}}`.
    `error_code` is the stable, machine-readable discriminator (see the
    module-level constants above); `message` stays the existing
    human-readable text, unchanged in content from before this field existed.
    """
    return HTTPException(
        status_code=status_code, detail={"message": message, "error_code": error_code}
    )


def _enqueue_resume_agent_workflow(run_id: uuid.UUID, *, approved: bool) -> str:
    """Enqueue `resume_agent_workflow` for `run_id` -- the same lazy-import-
    then-`.delay()` idiom `_enqueue_run_agent_workflow` above uses (see that
    function's own docstring for why the depth-2 cross-package import is
    required here). `workers/tasks/agent_workflow.py::resume_agent_workflow`
    already exists end to end (`_resume_agent_workflow_async` ->
    `_construct_runner` -> `runner.resume(run.id, approved=...)` -> commit)
    and is already routed to the `agent_runs` Celery queue -- this is its
    first and only caller.
    """
    from juli_backend.workers.tasks import agent_workflow as agent_workflow_tasks

    async_result = agent_workflow_tasks.resume_agent_workflow.delay(str(run_id), approved)
    return async_result.id


def _as_aware_utc(value: datetime) -> datetime:
    """Normalize a DB-read datetime to aware UTC before comparing to `now`.

    Mirrors `workers/tasks/reaper.py::_as_aware_utc` (not imported --
    `juli_backend.workers.tasks.reaper` is a depth-3 cross-package import,
    forbidden by the same `.importlinter.toml` cap this module's own
    docstring already explains): `run_confirmations.expires_at` is declared
    `DateTime(timezone=True)`, but SQLite (the unit-test backend) hands
    naive datetimes back regardless of the column's declared timezone
    awareness. Every writer in this codebase seeds UTC, never a local
    timezone, so attaching UTC to a naive value restores information, it
    does not guess it.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _transition_confirmation_or_none(
    session: AsyncSession,
    confirmation_id: uuid.UUID,
    *,
    new_status: str,
    selected_option_id: str | None,
) -> bool:
    """Atomically flip a `run_confirmations` row out of `pending`, and
    report whether *this call* won that transition.

    A single conditional `UPDATE ... WHERE id = :id AND status = 'pending'`
    -- not a read-then-write -- is what makes this safe under a race: two
    concurrent decisions on the same confirmation both reach this function,
    but Postgres serializes the two `UPDATE`s against the same row (one
    blocks on the other's row lock until it commits or rolls back), so at
    most one can match `status = 'pending'` and return a matched rowcount
    of `1`; the loser matches zero rows and gets `False` back, never a
    second, silently-overwriting write. The caller commits (or does not)
    based on this return value -- this function itself never commits, so a
    losing caller's transaction has made no durable change to roll back.
    """
    stmt = (
        update(RunConfirmation)
        .where(
            RunConfirmation.id == confirmation_id,
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
        .values(
            status=new_status,
            selected_option_id=selected_option_id,
            decided_at=datetime.now(UTC),
        )
    )
    # `AsyncSession.execute` is typed generically as `Result[Any]`; an
    # `UPDATE` statement's real runtime result is a `CursorResult`, which is
    # where `.rowcount` actually lives -- the cast tells mypy what
    # SQLAlchemy itself guarantees for a DML statement, it does not change
    # runtime behavior.
    result = cast(CursorResult, await session.execute(stmt))
    return result.rowcount == 1


@router.post(
    "/{run_id}/confirmations/{tool_call_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ConfirmationDecisionResponse,
)
async def submit_confirmation_decision(
    run_id: uuid.UUID,
    tool_call_id: str,
    body: ConfirmationDecisionRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ConfirmationDecisionResponse:
    """Authorize and resolve a seller's decision on a CONFIRM-policy pause
    (ADR-075 decision 2, issue #1224 / AGT-W5A). See the module docstring
    for the full ladder, the consent-binding contract, and the single-use
    race guarantee -- this body is the implementation of exactly that.
    """
    # ADR-075 decision 4 / #1223: the "confirmations" bucket -- 30/hour, per
    # shop, checked before the run is even resolved (a caller probing
    # tool_call_ids on runs it does not own must still be throttled, not
    # just successful decisions). See `services.agent.abuse_limits`'s
    # docstring for the fail-closed-on-backend-outage decision and why
    # cancel is structurally exempt from this whole module.
    limit_decision = await agent_abuse_limits.get_agent_abuse_limit_gate().try_acquire_confirmation(
        str(shop.id)
    )
    if not limit_decision.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop.id),
            operation=agent_abuse_limits.OPERATION_CONFIRMATION,
            retry_after_seconds=limit_decision.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many confirmation decisions for this shop; "
                f"retry in {limit_decision.retry_after_seconds}s"
            ),
            headers={"Retry-After": str(limit_decision.retry_after_seconds)},
        )

    # Rung 1: tenant scoping -- 404, never 403, for another shop's run or a
    # nonexistent one (no existence oracle).
    run = await _resolve_owned_run(run_id, shop, session)

    # Rung 2: the run must actually be paused for a decision.
    if run.status != WAITING_APPROVAL_RUN_STATUS:
        raise _confirmation_error(
            status.HTTP_409_CONFLICT,
            ERROR_RUN_NOT_AWAITING_CONFIRMATION,
            f"Run {run_id} is not awaiting a confirmation decision (status={run.status!r}).",
        )

    # Rung 3 (+ single-use): the confirmation row for this exact
    # tool_call_id, whatever its current status. A `tool_call_id` this run
    # never paused on at all is a 404 (the ladder's "matches THE pending
    # confirmation" rung); one that already resolved (approved/declined) is
    # a 409 (single-use, second decision); one already flipped `expired` by
    # some future writer is a 410, same as the wall-clock check below.
    confirmation_result = await session.execute(
        select(RunConfirmation).where(
            RunConfirmation.workflow_run_id == run_id,
            RunConfirmation.tool_call_id == tool_call_id,
        )
    )
    confirmation = confirmation_result.scalars().first()
    if confirmation is None:
        raise _confirmation_error(
            status.HTTP_404_NOT_FOUND,
            ERROR_CONFIRMATION_NOT_FOUND,
            f"No confirmation for tool_call_id={tool_call_id!r} on run {run_id}.",
        )
    if confirmation.status == "expired":
        raise _confirmation_error(
            status.HTTP_410_GONE,
            ERROR_CONFIRMATION_EXPIRED,
            "This confirmation has expired; the run is left for the reaper.",
        )
    if confirmation.status != PENDING_CONFIRMATION_STATUS:
        raise _confirmation_error(
            status.HTTP_409_CONFLICT,
            ERROR_CONFIRMATION_ALREADY_DECIDED,
            f"Confirmation {tool_call_id!r} was already decided ({confirmation.status}).",
        )

    # Rung 4: the wall-clock deadline, checked directly against
    # `expires_at` -- independent of whether the reaper's periodic sweep
    # has run yet. Never force-terminates the run or the row; the reaper's
    # `confirmation_expired` sweep (`workers/tasks/reaper.py`) is the only
    # writer of that transition.
    if _as_aware_utc(confirmation.expires_at) <= datetime.now(UTC):
        raise _confirmation_error(
            status.HTTP_410_GONE,
            ERROR_CONFIRMATION_EXPIRED,
            "This confirmation has expired; the run is left for the reaper.",
        )

    if body.decision == "decline":
        selected_option_id: str | None = None
        approved = False
    elif body.decision == "approve":
        if body.option_id is None:
            raise _confirmation_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ERROR_OPTION_ID_REQUIRED,
                "An approve decision requires option_id.",
            )
        options = confirmation.options if isinstance(confirmation.options, list) else []
        selected = next(
            (option for option in options if option.get("option_id") == body.option_id),
            None,
        )
        if selected is None:
            raise _confirmation_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ERROR_UNKNOWN_OPTION_ID,
                f"option_id={body.option_id!r} is not one of this confirmation's options.",
            )

        # Consent binding (ADR-075 decision 2): re-derive the selected
        # option's params_sha from the run's RECONSTRUCTED state -- the
        # verbatim `pending_confirmation.arguments` blob `WorkflowRunner
        # .resume` itself reads (`services/agent/runner/state.py`,
        # `services/agent/runner/core.py::resume`) -- never from the
        # confirmation row's own `proposed_change` (that would only ever
        # prove the option is self-consistent, not that it still matches
        # what the run would actually execute). A mismatch is a hard
        # failure: the confirmation row is left `pending` and
        # `resume_agent_workflow` is never enqueued, so `ToolExecutor
        # .execute` is structurally unreachable on this path -- not a log
        # line, an absence of the only call site that could reach it.
        run_state = run.state if isinstance(run.state, dict) else {}
        pending_state = run_state.get("pending_confirmation")
        if not isinstance(pending_state, dict) or "arguments" not in pending_state:
            raise _confirmation_error(
                status.HTTP_409_CONFLICT,
                ERROR_RUN_STATE_NOT_RECONSTRUCTABLE,
                "Run has no reconstructable pending confirmation state.",
            )
        # Depth-2 facade import (see `_resolve_optimize_product_prompt_pin`
        # above for the identical idiom and the import-boundary rationale):
        # `runner/__init__.py` re-exports `compute_params_sha` for exactly
        # this caller (see that module's own docstring).
        from juli_backend.services.agent import runner as runner_module

        expected_params_sha = runner_module.compute_params_sha(pending_state["arguments"])
        if selected.get("params_sha") != expected_params_sha:
            logger.warning(
                "agent_confirmation_params_sha_mismatch",
                extra={
                    "shop_id": str(shop.id),
                    "run_id": str(run_id),
                    "tool_call_id": tool_call_id,
                    "option_id": body.option_id,
                },
            )
            raise _confirmation_error(
                status.HTTP_409_CONFLICT,
                ERROR_PARAMS_SHA_MISMATCH,
                "The proposed change no longer matches the run's current state; "
                "refusing to execute an unconsented change.",
            )
        # Freeze the confirmed params_sha onto the run's own reconstructable
        # state (ADR-075 decision 2, #1224 review round 2). `WorkflowRunner`
        # has no database access beyond `ConversationStore`
        # (`services/agent/runner/core.py`'s own docstring: "no direct
        # database access here") -- it cannot read
        # `run_confirmations.options[].params_sha` itself, so this is the
        # only channel that lets `resume()`'s approve branch independently
        # re-derive-and-compare before `ToolExecutor.execute`, entirely
        # from state it already loads, rather than trusting whichever
        # caller enqueued the task. Reassigned (not mutated in place) so
        # SQLAlchemy's JSON-column change detection actually sees it --
        # the same idiom `JsonbConversationStore.persist` uses for `run.state`.
        updated_pending_state = {**pending_state, "params_sha": expected_params_sha}
        run.state = {**run_state, "pending_confirmation": updated_pending_state}

        selected_option_id = body.option_id
        approved = True
    else:
        raise _confirmation_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ERROR_INVALID_DECISION,
            f"decision must be 'approve' or 'decline', got {body.decision!r}.",
        )

    new_status = "approved" if approved else "declined"
    won = await _transition_confirmation_or_none(
        session,
        confirmation.id,
        new_status=new_status,
        selected_option_id=selected_option_id,
    )
    if not won:
        # Lost a race to a concurrent decision on this same confirmation
        # between the read above and this UPDATE -- the identical
        # client-observable fact as the sequential single-use 409 above,
        # so it carries the SAME error_code (see the constant's own
        # docstring). Nothing was enqueued; nothing here needs rolling back.
        raise _confirmation_error(
            status.HTTP_409_CONFLICT,
            ERROR_CONFIRMATION_ALREADY_DECIDED,
            f"Confirmation {tool_call_id!r} was already decided.",
        )
    # The transition is committed BEFORE the enqueue, never after: enqueuing
    # first would let a worker observe the row still `pending` mid-flight --
    # the exact race that produced #1221's review-reproduced IntegrityError
    # against a second, sequential CONFIRM pause on the same run (the second
    # pause's INSERT collides with `uq_run_confirmations_pending_run` while
    # the first row still says `pending`).
    await session.commit()

    celery_task_id = _enqueue_resume_agent_workflow(run_id, approved=approved)

    logger.info(
        "agent_confirmation_decided",
        extra={
            "shop_id": str(shop.id),
            "run_id": str(run_id),
            "tool_call_id": tool_call_id,
            "decision": body.decision,
            "celery_task_id": celery_task_id,
        },
    )

    return ConfirmationDecisionResponse(
        decision=body.decision,
        status=new_status,
        celery_task_id=celery_task_id,
    )


# ---------------------------------------------------------------------------
# Run list (issue #1310) -- polled read model over persisted workflow_runs
# ---------------------------------------------------------------------------


class PendingDecisionSummary(BaseModel):
    """Summary of a pending decision for a waiting_approval run."""

    tool_call_id: str
    expires_at: str


class WorkflowRunListItem(BaseModel):
    """One run in the seller's polled read model."""

    id: uuid.UUID
    status: str
    stop_reason: str | None = None
    product_name: str
    created_at: str
    completed_at: str | None = None
    running_seconds_elapsed: int
    latest_narration: str | None = None
    decision_summary: PendingDecisionSummary | None = None


class WorkflowRunListResponse(BaseModel):
    """Polled read model response for GET /v1/demo/runs."""

    success: bool = True
    data: list[WorkflowRunListItem]


@router.get("", response_model=WorkflowRunListResponse)
async def list_demo_runs(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=1000),
) -> WorkflowRunListResponse:
    """Polled read model over the seller's workflow runs (ADR-083 T4, #1310).

    Returns the authenticated caller's shop's runs in order (newest first),
    paginated. Each run carries status, stop_reason (for terminal runs),
    bound product name, timestamps, running-time accounting, the latest
    persisted narration line (null if never emitted), and for waiting_approval
    runs, the pending decision summary and expiry read from the persisted
    confirmation row.

    A queued run (zero events) is visible. Terminal runs carry one of seven
    stop_reason values, all distinct. No tool names, playbook keys, or
    internal identifiers appear anywhere in the response.
    """
    shop_id = shop.id

    try:
        # Get all runs for this shop, ordered newest first
        result = await session.execute(
            select(WorkflowRunRow, Product)
            .where(WorkflowRunRow.shop_id == shop_id)
            .join(Product, WorkflowRunRow.product_id == Product.id)
            .order_by(WorkflowRunRow.created_at.desc())
            .limit(limit)
        )
        rows = result.all()

        items: list[WorkflowRunListItem] = []
        for run, product in rows:
            # Get latest narration from workflow.status events
            latest_narration = None
            narration_result = await session.execute(
                select(WorkflowRunEventRow.payload)
                .where(
                    WorkflowRunEventRow.workflow_run_id == run.id,
                    WorkflowRunEventRow.event_type == "workflow.status",
                )
                .order_by(WorkflowRunEventRow.sequence_number.desc())
                .limit(1)
            )
            narration_row = narration_result.scalars().first()
            if narration_row and isinstance(narration_row, dict):
                latest_narration = narration_row.get("phase_narration")

            # For waiting_approval runs, fetch the pending decision
            decision_summary = None
            if run.status == WAITING_APPROVAL_RUN_STATUS:
                confirmation_result = await session.execute(
                    select(RunConfirmation)
                    .where(
                        RunConfirmation.workflow_run_id == run.id,
                        RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
                    )
                    .limit(1)
                )
                confirmation = confirmation_result.scalars().first()
                if confirmation:
                    decision_summary = PendingDecisionSummary(
                        tool_call_id=confirmation.tool_call_id,
                        expires_at=confirmation.expires_at.isoformat()
                        if isinstance(confirmation.expires_at, datetime)
                        else str(confirmation.expires_at),
                    )

            # Build the item
            item = WorkflowRunListItem(
                id=run.id,
                status=run.status,
                stop_reason=run.stop_reason,
                product_name=product.name,
                created_at=run.created_at.isoformat() if run.created_at else "",
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
                running_seconds_elapsed=run.running_seconds_elapsed,
                latest_narration=latest_narration,
                decision_summary=decision_summary,
            )
            items.append(item)

        logger.info(
            "agent_runs_list_read",
            extra={"shop_id": str(shop_id), "count": len(items)},
        )
        return WorkflowRunListResponse(data=items)

    except Exception:
        logger.exception(
            "agent_runs_list_failed",
            extra={"shop_id": str(shop_id)},
        )
        # Degrade to empty list rather than error (rollback honesty per #1310)
        return WorkflowRunListResponse(data=[])
