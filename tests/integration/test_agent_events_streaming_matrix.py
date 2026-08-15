"""AGT-W3B integration matrix -- ADR-074 decision 6, issue #1131.

Every prior slice in this wave tested one side of the event-streaming
contract against a fake: #1125 (envelope/table) against nothing external,
#1127 (`PersistingEventSink`) against a fake Redis publisher, #1128 (the
SSE/cancel/confirmations routes) against sqlite and a fake pub/sub. This
file is the first place two real implementations meet: the real
`PersistingEventSink`, real Postgres (not sqlite), the real FastAPI route
wrapped in a real ASGI HTTP client, and a **scripted fake runner** standing
in for #1119's not-yet-wired `WorkflowRunner` (ADR-074 d.6 explicitly calls
for a scripted driver here, not the real runner -- the live wiring does not
exist on this branch and this slice does not build it).

Skips the entire module when `DATABASE_URL` is not a reachable Postgres
instance -- a skipped integration test proves nothing, and this module says
so loudly in its skip reason rather than passing vacuously.

Five ADR-074 d.6 matrix cases, one test (or tight group) apiece:

- ``test_exact_replay_after_k_yields_k_plus_1_through_n_ordered_no_gaps_no_duplicates``
- ``test_handoff_overlap_event_published_in_the_replay_subscribe_gap_arrives_exactly_once``
- ``test_redis_subscribe_failure_degrades_to_postgres_polling_and_still_delivers``
  paired with
  ``test_redis_loss_mid_stream_reconnect_via_last_event_id_replays_gaplessly``
- ``test_lifecycle_terminal_event_closes_the_live_stream_via_real_http``,
  ``test_lifecycle_late_joiner_on_already_terminal_run_gets_full_replay_and_never_subscribes``,
  ``test_lifecycle_cancel_at_checkpoint_is_visible_on_the_stream``
- ``test_crash_resume_twice_against_one_blob_no_dupe_events_one_completion``

Plus the explicit `Last-Event-ID` cases #1131's issue thread calls out
(raised by #1132's intent-review, verified against #1128's route, but never
proven against a real client/real Postgres until now):

- ``test_redis_loss_mid_stream_reconnect_via_last_event_id_replays_gaplessly``
  -- reconnect driven by the client's own cursor, end to end.
- ``test_last_event_id_header_takes_priority_over_after_query_param_via_real_stack``
- ``test_last_event_id_header_absent_falls_back_to_after_then_to_zero``
- ``test_last_event_id_header_non_numeric_should_degrade_not_500`` -- a
  **known production defect** (see its docstring): `int(last_event_id)` is
  unguarded in `api/routes/agent_runs.py`, so this is `xfail(strict=True)`,
  not a workaround. This test slice does not patch production code.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes import agent_runs
from juli_backend.api.routes.agent_runs import (
    get_heartbeat_interval_s,
    get_poll_interval_s,
    get_run_event_subscriber,
    get_run_events_session_factory,
)
from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.core.security import get_current_user
from juli_backend.database import get_session
from juli_backend.database.database import Base
from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.envelope import WorkflowRunEventAdapter
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink

# The four data-pipeline schemas some unrelated models declare
# (`silver.orders` etc.) -- irrelevant to this slice, translated to the
# default `public` schema for test setup exactly like `tests/unit/conftest.py`
# and `tests/integration/conftest.py`'s own `engine` fixtures already do for
# sqlite (`Base.metadata.create_all` otherwise tries to create schemas this
# suite has no reason to provision).
_SCHEMA_TRANSLATE_MAP = {"ops": None, "bronze": None, "gold": None, "silver": None}


# ---------------------------------------------------------------------------
# Postgres reachability -- ADR-074 d.6 requires real Postgres, not sqlite.
# Mirrors the `requires_postgres` pattern `tests/integration/test_migrations.py`
# and `test_restore_drill.py` already use.
# ---------------------------------------------------------------------------


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url),
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "AGT-W3B integration matrix (#1131) requires a reachable Postgres "
        "DATABASE_URL -- ADR-074 d.6 is explicit that this suite runs against "
        "real Postgres, not sqlite/mocked. A skipped run here proves nothing; "
        "see the executor's report for pass/skip counts with and without "
        "DATABASE_URL set."
    ),
)

pytestmark = [pytest.mark.asyncio, requires_postgres]


# ---------------------------------------------------------------------------
# Schema setup -- a plain SYNC engine (psycopg2), deliberately not async.
# pytest-asyncio's default fixture-loop scope is per-function here (no
# `asyncio_default_fixture_loop_scope` override in pytest.ini), so a
# session-scoped asyncpg connection would be reused across event loops --
# exactly the "Future attached to a different loop" failure mode
# `tests/unit/conftest.py` already documents for Redis. DDL runs once, via a
# loop-independent sync driver; every async fixture below is function-scoped.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _postgres_schema_ready() -> None:
    url = sync_database_url(_database_url())
    engine = create_engine(url, execution_options={"schema_translate_map": _SCHEMA_TRANSLATE_MAP})
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    engine.dispose()


@pytest_asyncio.fixture
async def pg_engine(_postgres_schema_ready: None):
    url = async_database_url(_database_url())
    engine = create_async_engine(
        url, execution_options={"schema_translate_map": _SCHEMA_TRANSLATE_MAP}
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session_factory(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Seeding helpers -- every row uses a fresh uuid4 so tests never collide
# despite sharing one disposable database for the whole session (dropped
# after the run by the executor, per #1131's constraints -- not by this
# fixture, since dropping the actual OS-level database from inside pytest
# would race the next test still using the same connection pool).
# ---------------------------------------------------------------------------


async def _seed_shop(session_factory: async_sessionmaker[AsyncSession]) -> tuple[User, Shop]:
    async with session_factory() as session:
        user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
        session.add(user)
        await session.flush()
        shop = Shop(user_id=user.id, shop_name=f"AGT-W3B-1131-{uuid.uuid4()}")
        session.add(shop)
        await session.flush()
        await session.commit()
        return user, shop


async def _seed_run(
    session_factory: async_sessionmaker[AsyncSession],
    shop: Shop,
    *,
    status: str = "running",
    state: dict[str, Any] | None = None,
) -> WorkflowRunRow:
    async with session_factory() as session:
        product = Product(
            shop_id=shop.id,
            tiktok_product_id=f"agt-w3b-1131-{uuid.uuid4()}",
            name="Integration Matrix Widget",
            status="active",
            # asyncpg rejects a tz-aware datetime on `update_time` -- that
            # column has no explicit `DateTime(timezone=True)`, so it is a
            # naive Postgres `timestamp` column; seed naive UTC (#1131 note).
            update_time=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(product)
        await session.flush()
        run = WorkflowRunRow(
            shop_id=shop.id,
            product_id=product.id,
            state=state if state is not None else {"next_sequence": 1},
            status=status,
            prompt_version="optimize_product.v1",
            prompt_sha256="b" * 64,
        )
        session.add(run)
        await session.flush()
        await session.commit()
        await session.refresh(run)
        return run


# ---------------------------------------------------------------------------
# The scripted fake runner (ADR-074 d.6) -- NOT #1119's real `WorkflowRunner`,
# which does not exist on this branch and is out of scope for this slice.
# Reproduces exactly the invariant the issue thread's crash-resume case
# exists to prove: `sequence_number` is minted ONLY from
# `workflow_runs.state["next_sequence"]` (ADR-074 decision 1; #1125 made the
# envelope field non-defaultable so nothing downstream can mint one instead),
# and that counter's persistence is what a pause/resume round trip (#1118)
# and a crash-replay both hinge on.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptedEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


def _standard_script(product_ref: str) -> list[ScriptedEvent]:
    """A representative 3-event happy path: started -> status -> completed."""
    return [
        ScriptedEvent(
            "workflow.started",
            {
                "workflow_key": "optimize_product",
                "product_ref": product_ref,
                "prompt_version": "optimize_product.v1",
            },
        ),
        ScriptedEvent("workflow.status", {"phase_narration": "Đang phân tích sản phẩm"}),
        ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
    ]


class ScriptedFakeRunner:
    """Mints `sequence_number` from an in-memory counter seeded from
    `starting_sequence` (standing in for reading `workflow_runs.state[
    "next_sequence"]`), builds a real `WorkflowRunEvent` union member via
    `WorkflowRunEventAdapter` for each scripted step (so every event this
    class emits satisfies the same Pydantic contract a real runner's emit
    would), and calls the real `EventSink.emit` -- never lets the sink mint
    a sequence number itself.

    `persist_state=False` is how a crash is modeled: the write that would
    have advanced `workflow_runs.state` never happens, so a second
    `ScriptedFakeRunner` constructed with the same `starting_sequence`
    reproduces exactly what a crash-redelivered Celery task (`acks_late=True`,
    ADR-074 d.4) would do -- replay the identical script against the same
    starting sequence, relying on the sink's unique-index no-op (ADR-074
    decisions 1/3) rather than any state this class would have to fabricate.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        sink: PersistingEventSink,
        run_id: uuid.UUID,
        starting_sequence: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._sink = sink
        self._run_id = run_id
        self._next_sequence = starting_sequence
        self._clock = clock

    async def run(
        self,
        script: list[ScriptedEvent],
        *,
        final_status: str | None = None,
        persist_state: bool = True,
    ) -> None:
        for scripted in script:
            seq = self._next_sequence
            self._next_sequence += 1
            envelope = WorkflowRunEventAdapter.validate_python(
                {
                    "workflow_run_id": self._run_id,
                    "sequence_number": seq,
                    "event_type": scripted.event_type,
                    "timestamp": self._clock(),
                    "payload": scripted.payload,
                    "v": 1,
                }
            )
            await self._sink.emit(envelope)

        if persist_state:
            async with self._session_factory() as session:
                run = await session.get(WorkflowRunRow, self._run_id)
                assert run is not None
                run.state = {"next_sequence": self._next_sequence}
                if final_status is not None:
                    run.status = final_status
                await session.commit()


# ---------------------------------------------------------------------------
# A fake Redis: one in-memory bus playing BOTH roles the real implementations
# meet at -- `EventPublisher` (`persisting_sink.py`'s narrow `publish` seam)
# and `EventSubscriber` (`agent_runs.py`'s narrow `subscribe` seam). A single
# instance is handed to `PersistingEventSink` as `publisher` and to the route
# as `subscriber`, exactly like production where both sides are the same
# Redis deployment. Publishing to a channel with no live subscriber drops
# the message -- real Redis pub/sub semantics, the same realism #1128's unit-
# level `FakePubSub` established -- which is the property "handoff overlap"
# exists to prove does not cost a client an event.
# ---------------------------------------------------------------------------


class QueueSubscription:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def get_message(self, timeout: float) -> str | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def close(self) -> None:
        self.closed = True


class FakeRedisBus:
    def __init__(self) -> None:
        self._channels: dict[str, list[QueueSubscription]] = {}
        self._down = False
        self.publish_log: list[tuple[str, str]] = []
        self.subscribe_calls = 0

    async def publish(self, channel: str, message: str) -> int:
        self.publish_log.append((channel, message))
        if self._down:
            return 0
        subs = self._channels.get(channel, [])
        for sub in subs:
            sub.queue.put_nowait(message)
        return len(subs)

    async def subscribe(self, channel: str) -> QueueSubscription:
        self.subscribe_calls += 1
        if self._down:
            raise ConnectionError("simulated Redis outage")
        sub = QueueSubscription()
        self._channels.setdefault(channel, []).append(sub)
        return sub

    def simulate_outage(self) -> None:
        """From this point on: publish drops silently (no reachable
        subscriber), and any NEW subscribe attempt fails -- a live SSE
        connection made before the outage just stops receiving anything on
        its already-open `QueueSubscription` (indistinguishable, from the
        caller's side, from a real dead Redis TCP connection going quiet)."""
        self._down = True


class FailingSubscriber:
    async def subscribe(self, channel: str) -> QueueSubscription:
        raise ConnectionError("redis subscribe failed")


class CountingNullSubscriber:
    """Never delivers anything; records how many times `subscribe()` was
    called so a test can assert "never subscribed" without trusting a raise
    from inside `subscribe()` -- `event_stream`'s own subscribe-failure
    handling wraps that call in a blanket `except Exception`, so a raise
    would be silently swallowed and indistinguishable from a real failure."""

    def __init__(self) -> None:
        self.subscribe_calls = 0

    async def subscribe(self, channel: str) -> QueueSubscription:
        self.subscribe_calls += 1
        return QueueSubscription()


# ---------------------------------------------------------------------------
# App/client wiring -- one real ASGI app per test, every seam FastAPI already
# exposes for override (`app.dependency_overrides`) wired to real Postgres.
# ---------------------------------------------------------------------------


def _build_app(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    subscriber: Any,
    heartbeat_interval_s: float = 0.2,
    poll_interval_s: float = 0.03,
):
    app = create_app()

    async def _session_dep() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def _stream_session_factory_dep() -> async_sessionmaker[AsyncSession]:
        return session_factory

    app.dependency_overrides[get_session] = _session_dep
    app.dependency_overrides[get_run_events_session_factory] = _stream_session_factory_dep
    app.dependency_overrides[get_run_event_subscriber] = lambda: subscriber
    app.dependency_overrides[get_heartbeat_interval_s] = lambda: heartbeat_interval_s
    app.dependency_overrides[get_poll_interval_s] = lambda: poll_interval_s
    return app


def _set_auth_overrides(app, user: User, shop: Shop) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop


def _authenticated_client(app, user: User, shop: Shop) -> AsyncClient:
    _set_auth_overrides(app, user, shop)
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


# ---------------------------------------------------------------------------
# A REAL uvicorn server on an OS-assigned loopback port -- needed for exactly
# one scenario: a genuine mid-stream client disconnect. `httpx.ASGITransport`
# cannot support that (verified by reading
# `httpx._transports.asgi.ASGITransport.handle_async_request`): it `await`s
# the entire ASGI app call to completion before returning any `Response`
# object at all, so an infinite live SSE generator (still-running run, no
# terminal event yet) means that `await` never returns and the test hangs
# forever -- not a production bug, a limitation of the in-process test
# transport. Every other test in this module reads a full (finite) response
# through the lighter `ASGITransport` path above, which never hits this.
# `uvicorn` is already a direct dependency (`backend/pyproject.toml`) --
# nothing new added for this.
# ---------------------------------------------------------------------------


class _LiveUvicornServer:
    def __init__(self, app) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
        self._server = uvicorn.Server(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> str:
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            await asyncio.sleep(0.01)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            await self._task


@pytest_asyncio.fixture
async def live_client_factory():
    """Yields a callable `(app) -> AsyncClient` bound to a real, running
    uvicorn server for that app -- a genuine TCP connection a test can
    disconnect mid-stream, unlike the in-process `ASGITransport` path."""
    servers: list[_LiveUvicornServer] = []
    clients: list[AsyncClient] = []

    async def _start(app) -> AsyncClient:
        server = _LiveUvicornServer(app)
        base_url = await server.start()
        servers.append(server)
        client = AsyncClient(base_url=base_url)
        clients.append(client)
        return client

    yield _start

    for client in clients:
        await client.aclose()
    for server in servers:
        await server.stop()


# ---------------------------------------------------------------------------
# SSE parsing + a minimal real-cursor client. Not #1132's TypeScript
# fetch-streaming client (`apps/demo/src/lib/` is outside this backend
# slice's write path) -- this is only the piece of that contract this
# slice's route owns and must prove end to end: track the last observed
# `id:` and never deduplicate (ADR-074 decisions 3/5 -- dedupe is server-
# side only), reconnecting via `Last-Event-ID` rather than a hand-set
# `?after=`.
# ---------------------------------------------------------------------------


def _parse_sse_block(block: str) -> dict[str, str] | None:
    if not block or block.startswith(":"):
        return None
    record: dict[str, str] = {}
    for line in block.split("\n"):
        key, _, value = line.partition(": ")
        record[key] = value
    return record


def _record_ids(body: str) -> list[int]:
    ids = []
    for block in body.strip("\n").split("\n\n"):
        record = _parse_sse_block(block)
        if record is not None:
            ids.append(int(record["id"]))
    return ids


def _is_terminal_record(record: dict[str, str]) -> bool:
    return record.get("event") in {"workflow.completed", "workflow.failed"}


class RealCursorClient:
    def __init__(self, client: AsyncClient, url: str) -> None:
        self._client = client
        self._url = url
        self.last_event_id: int | None = None
        self.received: list[dict[str, str]] = []

    async def read_until(
        self,
        predicate: Callable[[dict[str, str]], bool],
        *,
        max_records: int | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Connects (sending `Last-Event-ID` if this client already has a
        cursor -- never a hand-set `?after=`), and reads records until
        `predicate` is satisfied, `max_records` new records have arrived, or
        the server closes the stream on its own. Returning early inside the
        `async with` block below cancels the underlying read, simulating a
        client walking away / a network blip -- exactly the disconnect a
        reconnect test needs to provoke."""
        headers = {}
        if self.last_event_id is not None:
            headers["Last-Event-ID"] = str(self.last_event_id)

        async def _drain() -> None:
            async with self._client.stream("GET", self._url, headers=headers) as resp:
                assert resp.status_code == 200
                buffer = ""
                seen_this_call = 0
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        record = _parse_sse_block(block)
                        if record is None:
                            continue
                        self.received.append(record)
                        self.last_event_id = int(record["id"])
                        seen_this_call += 1
                        if predicate(record) or (
                            max_records is not None and seen_this_call >= max_records
                        ):
                            return

        await asyncio.wait_for(_drain(), timeout=timeout)


# ---------------------------------------------------------------------------
# AC (ADR-074 d.6) -- exact replay: after=k yields exactly k+1..N.
# ---------------------------------------------------------------------------


async def test_exact_replay_after_k_yields_k_plus_1_through_n_ordered_no_gaps_no_duplicates(
    pg_session_factory,
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="completed")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    runner = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    script = [
        ScriptedEvent(
            "workflow.started",
            {"workflow_key": "optimize_product", "product_ref": "p1", "prompt_version": "v1"},
        ),
        ScriptedEvent("workflow.status", {"phase_narration": "a"}),
        ScriptedEvent("tool.started", {"tool_call_id": "tc1", "tool_name": "update_price"}),
        ScriptedEvent(
            "tool.completed",
            {"tool_call_id": "tc1", "tool_name": "update_price", "ok": True, "summary": "done"},
        ),
        ScriptedEvent("workflow.status", {"phase_narration": "b"}),
        ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
    ]
    await runner.run(script, final_status="completed")

    app = _build_app(pg_session_factory, subscriber=None)
    async with _authenticated_client(app, user, shop) as client:
        full = await client.get(f"/v1/demo/runs/{run.id}/events")
        tail = await client.get(f"/v1/demo/runs/{run.id}/events", params={"after": 3})

    all_ids = _record_ids(full.text)
    assert all_ids == [1, 2, 3, 4, 5, 6]
    assert len(set(all_ids)) == len(all_ids), "no duplicates in a full replay"

    tail_ids = _record_ids(tail.text)
    assert tail_ids == [4, 5, 6], "after=3 must yield exactly 4..6, ordered, no gaps"


# ---------------------------------------------------------------------------
# AC (ADR-074 d.6) -- handoff overlap: an event published during replay
# arrives exactly once. Deterministic race control via a monkeypatched
# `_replay_events` -- the same technique #1128's unit test proved this
# property with, now backed by real Postgres, the real `PersistingEventSink`
# (INSERT-commit-then-publish, for real), the real `FakeRedisBus` playing
# both publisher and subscriber, and the real ASGI `StreamingResponse`
# boundary -- none of which the unit-level version exercised.
# ---------------------------------------------------------------------------


async def test_handoff_overlap_event_published_in_the_replay_subscribe_gap_arrives_exactly_once(
    pg_session_factory, monkeypatch
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    opening = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await opening.run(
        [
            ScriptedEvent(
                "workflow.started",
                {"workflow_key": "optimize_product", "product_ref": "p1", "prompt_version": "v1"},
            ),
            ScriptedEvent("workflow.status", {"phase_narration": "opening"}),
        ],
        persist_state=True,
    )

    original_replay = agent_runs._replay_events

    async def hooked_replay(session_factory_arg, run_id_arg, after_seq_arg):
        async for row in original_replay(session_factory_arg, run_id_arg, after_seq_arg):
            yield row
        # By construction this runs strictly after `event_stream` has already
        # subscribed (subscribe-before-replay, ADR-074 decision 3) and
        # strictly before it starts consuming the live subscription -- the
        # exact window a naive replay-then-subscribe implementation would
        # still be racing. These two events are committed AND published for
        # real, through the real sink and the real bus, never yielded from
        # this generator itself -- they must arrive via the live leg, or not
        # at all.
        gap_runner = ScriptedFakeRunner(
            session_factory=session_factory_arg, sink=sink, run_id=run_id_arg, starting_sequence=3
        )
        await gap_runner.run(
            [
                ScriptedEvent("workflow.status", {"phase_narration": "in the gap"}),
                ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
            ],
            final_status="completed",
        )

    monkeypatch.setattr(agent_runs, "_replay_events", hooked_replay)

    app = _build_app(pg_session_factory, subscriber=bus)
    async with _authenticated_client(app, user, shop) as client:
        resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0)

    assert resp.status_code == 200
    ids = _record_ids(resp.text)
    assert ids == [1, 2, 3, 4], (
        "event 3, published in the replay-end/subscribe-start gap, must arrive "
        "exactly once -- lost (naive replay-then-subscribe) or duplicated "
        "(no dedupe) are both a regression"
    )
    assert bus.publish_log, "the real bus's publish() must actually have been exercised"


# ---------------------------------------------------------------------------
# AC (ADR-074 d.6) -- Redis loss: fallback polling delivers.
# ---------------------------------------------------------------------------


async def test_redis_subscribe_failure_degrades_to_postgres_polling_and_still_delivers(
    pg_session_factory,
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running")
    bus = FakeRedisBus()  # publisher only in this test -- subscriber always fails
    sink = PersistingEventSink(pg_session_factory, bus)

    async def _emit_shortly() -> None:
        await asyncio.sleep(0.1)
        runner = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await runner.run(_standard_script("p1"), final_status="completed")

    app = _build_app(pg_session_factory, subscriber=FailingSubscriber(), poll_interval_s=0.02)
    task = asyncio.create_task(_emit_shortly())
    try:
        async with _authenticated_client(app, user, shop) as client:
            resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0)
    finally:
        await task

    assert resp.status_code == 200
    assert _record_ids(resp.text) == [1, 2, 3], (
        "subscribe failure must degrade to Postgres polling, not drop the run's events"
    )


# ---------------------------------------------------------------------------
# AC (ADR-074 d.6) -- Redis loss: reconnect replays gaplessly, driven by the
# client's own `Last-Event-ID` cursor. This is also the flagship "reconnect
# via the real header, end to end" case the #1131 issue thread asks for.
# ---------------------------------------------------------------------------


async def test_redis_loss_mid_stream_reconnect_via_last_event_id_replays_gaplessly(
    pg_session_factory, live_client_factory
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    runner = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await runner.run(
        [
            ScriptedEvent(
                "workflow.started",
                {"workflow_key": "optimize_product", "product_ref": "p1", "prompt_version": "v1"},
            ),
            ScriptedEvent("workflow.status", {"phase_narration": "opening"}),
        ],
        persist_state=True,
    )

    # A genuine mid-stream client disconnect (below) needs a real TCP
    # connection -- `httpx.ASGITransport` cannot support it (see the
    # `_LiveUvicornServer` docstring above).
    app = _build_app(pg_session_factory, subscriber=bus, poll_interval_s=0.02)
    _set_auth_overrides(app, user, shop)
    client = await live_client_factory(app)

    reader = RealCursorClient(client, f"/v1/demo/runs/{run.id}/events")

    # First connection: replay 1, 2 (nothing more exists yet), then the
    # client walks away -- simulating exactly the network blip / Redis loss
    # this case is about, from the client's point of view.
    await reader.read_until(lambda r: False, max_records=2)
    assert [int(r["id"]) for r in reader.received] == [1, 2]

    # Redis is now down for good. Two more events land -- one non-terminal,
    # one terminal -- while nobody is live-subscribed.
    bus.simulate_outage()
    await runner.run(
        [
            ScriptedEvent("workflow.status", {"phase_narration": "closing"}),
            ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
        ],
        final_status="completed",
    )

    # Reconnect driven by the client's own last-observed cursor
    # (`Last-Event-ID: 2`), never a hand-set `?after=`. subscribe() now fails
    # (Redis is down), so this exercises the polling fallback too.
    await reader.read_until(_is_terminal_record)

    ids = [int(r["id"]) for r in reader.received]
    assert ids == [1, 2, 3, 4], "reconnect via Last-Event-ID must replay the gap gaplessly"
    assert len(set(ids)) == len(ids), "no duplicates across the reconnect boundary"


# ---------------------------------------------------------------------------
# Last-Event-ID cases (#1131 issue thread) -- precedence, absent-header
# fallback, and the malformed-header defect.
# ---------------------------------------------------------------------------


async def test_last_event_id_header_takes_priority_over_after_query_param_via_real_stack(
    pg_session_factory,
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="completed")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    runner = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await runner.run(
        [
            ScriptedEvent("workflow.status", {"phase_narration": "a"}),
            ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
        ],
        final_status="completed",
    )

    app = _build_app(pg_session_factory, subscriber=None)
    async with _authenticated_client(app, user, shop) as client:
        resp = await client.get(
            f"/v1/demo/runs/{run.id}/events",
            params={"after": 0},
            headers={"Last-Event-ID": "1"},
        )

    assert _record_ids(resp.text) == [2], "Last-Event-ID must win over ?after= when both present"


async def test_last_event_id_header_absent_falls_back_to_after_then_to_zero(pg_session_factory):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="completed")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    runner = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await runner.run(
        [
            ScriptedEvent("workflow.status", {"phase_narration": "a"}),
            ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
        ],
        final_status="completed",
    )

    app = _build_app(pg_session_factory, subscriber=None)
    async with _authenticated_client(app, user, shop) as client:
        via_after = await client.get(f"/v1/demo/runs/{run.id}/events", params={"after": 1})
        via_default = await client.get(f"/v1/demo/runs/{run.id}/events")

    assert _record_ids(via_after.text) == [2], "no header -> falls back to ?after="
    assert _record_ids(via_default.text) == [1, 2], "no header, no ?after= -> falls back to 0"


async def test_last_event_id_header_non_numeric_should_degrade_not_500(pg_session_factory):
    """**Production defect, found by this slice, deliberately not fixed
    here** (this is a test-only slice -- see the executor's report).

    `api/routes/agent_runs.py::stream_run_events` does
    ``after_seq = int(last_event_id)`` with no `try`/`except` around it. The
    #1131 issue thread asks explicitly: "confirm what an absent or
    non-numeric header does -- `int(last_event_id)` is unguarded, so check
    it degrades rather than 500s." It does not degrade: a non-numeric
    `Last-Event-ID` raises `ValueError` inside the route handler, which
    `api/middleware.py::install_error_boundary`'s catch-all turns into a
    real HTTP 500 (`{"detail": "Internal server error"}`) -- proven against
    the real ASGI stack here, not inferred from reading the source.

    `xfail(strict=True)`: if a future change to the route (not this test
    slice, per the hard constraint against touching production code here)
    makes this degrade correctly, this test flips to an unexpected pass and
    CI fails loudly until the marker is removed -- it cannot silently rot
    into a false green.
    """
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="completed")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    runner = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await runner.run(
        [
            ScriptedEvent("workflow.status", {"phase_narration": "a"}),
            ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
        ],
        final_status="completed",
    )

    app = _build_app(pg_session_factory, subscriber=None)
    async with _authenticated_client(app, user, shop) as client:
        resp = await client.get(
            f"/v1/demo/runs/{run.id}/events",
            headers={"Last-Event-ID": "not-a-number"},
        )

    assert resp.status_code != 500, (
        "a non-numeric Last-Event-ID header must degrade (per the #1131 issue "
        f"thread), never 500 -- got {resp.status_code}: {resp.text!r}"
    )


test_last_event_id_header_non_numeric_should_degrade_not_500 = pytest.mark.xfail(
    reason=(
        "PRODUCTION DEFECT (#1131 finding, not fixed by this test slice): "
        "api/routes/agent_runs.py stream_run_events does "
        "`after_seq = int(last_event_id)` unguarded. A non-numeric "
        "Last-Event-ID 500s via install_error_boundary's catch-all instead "
        "of degrading to ?after=/0 as the issue thread specifies."
    ),
    strict=True,
)(test_last_event_id_header_non_numeric_should_degrade_not_500)


# ---------------------------------------------------------------------------
# AC (ADR-074 d.6) -- lifecycle: terminal close, late joiner, cancel at
# checkpoint visible on the stream.
# ---------------------------------------------------------------------------


async def test_lifecycle_terminal_event_closes_the_live_stream_via_real_http(pg_session_factory):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)

    async def _emit_shortly() -> None:
        await asyncio.sleep(0.1)
        runner = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await runner.run(_standard_script("p1"), final_status="completed")

    app = _build_app(pg_session_factory, subscriber=bus)
    task = asyncio.create_task(_emit_shortly())
    try:
        async with _authenticated_client(app, user, shop) as client:
            # Bounded well under the heartbeat interval: if the terminal
            # event failed to close the stream, this would hang past the
            # timeout instead of the request naturally completing.
            resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0)
    finally:
        await task

    ids = _record_ids(resp.text)
    assert ids == [1, 2, 3]
    records = [b for b in resp.text.strip("\n").split("\n\n") if b and not b.startswith(":")]
    assert "workflow.completed" in records[-1]


async def test_lifecycle_late_joiner_on_already_terminal_run_gets_full_replay_and_never_subscribes(
    pg_session_factory,
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    runner = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await runner.run(_standard_script("p1"), final_status="completed")

    counting_subscriber = CountingNullSubscriber()
    app = _build_app(pg_session_factory, subscriber=counting_subscriber)
    async with _authenticated_client(app, user, shop) as client:
        # A "late joiner": connects only after the run is already terminal.
        resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=2.0)

    assert _record_ids(resp.text) == [1, 2, 3]
    assert counting_subscriber.subscribe_calls == 0, (
        "a run already terminal at connect must never attempt to subscribe -- "
        "late joiners are free (ADR-074 decision 3)"
    )


async def test_lifecycle_cancel_at_checkpoint_is_visible_on_the_stream(pg_session_factory):
    """`POST /cancel`'s own contract (202, idempotent, transport-only) is
    already proven at unit level (`test_agent_run_events_api.py`) -- the
    actual checkpoint-cancellation signal into a runner's run-state blob is
    W3-A/P9's concern, out of this route's and this slice's scope (see
    `api/routes/agent_runs.py`'s module docstring). What this test proves
    instead, end to end: once a run reaches a cancellation checkpoint (here,
    simulated by the scripted runner emitting the failure-class terminal the
    real runner would), that event is visible on an already-open SSE stream
    and closes it -- the one piece of "cancel is visible on the stream" this
    slice's transport layer actually owns.
    """
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running")
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)

    app = _build_app(pg_session_factory, subscriber=bus)
    async with _authenticated_client(app, user, shop) as client:
        cancel_resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")
        assert cancel_resp.status_code == 202

        async def _reach_checkpoint_shortly() -> None:
            await asyncio.sleep(0.1)
            runner = ScriptedFakeRunner(
                session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
            )
            await runner.run(
                [
                    ScriptedEvent(
                        "workflow.failed",
                        {"status": "cancelled", "stop_reason": "cancelled_by_seller"},
                    )
                ],
                final_status="cancelled",
            )

        task = asyncio.create_task(_reach_checkpoint_shortly())
        try:
            resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0)
        finally:
            await task

    records = [_parse_sse_block(b) for b in resp.text.strip("\n").split("\n\n")]
    records = [r for r in records if r]
    assert len(records) == 1
    assert records[0]["event"] == "workflow.failed"
    assert "cancelled_by_seller" in records[0]["data"]

    async with pg_session_factory() as session:
        refreshed = await session.get(WorkflowRunRow, run.id)
        assert refreshed.status == "cancelled"


# ---------------------------------------------------------------------------
# AC (ADR-074 d.6) -- crash-resume: the task run twice against one blob
# produces no duplicate events and exactly one completion. This is where
# #1118's "next_sequence survives a pause/resume round trip" guarantee and
# #1125's "sequence_number is non-defaultable" guarantee are exercised
# together for the first time (#1131 issue thread).
# ---------------------------------------------------------------------------


async def test_crash_resume_twice_against_one_blob_no_dupe_events_one_completion(
    pg_session_factory,
):
    user, shop = await _seed_shop(pg_session_factory)
    run = await _seed_run(pg_session_factory, shop, status="running", state={"next_sequence": 1})
    bus = FakeRedisBus()
    sink = PersistingEventSink(pg_session_factory, bus)
    script = _standard_script("crash-resume-ref")

    # Attempt 1: the task runs to completion and persists the advanced blob.
    attempt_1 = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await attempt_1.run(script, final_status="completed", persist_state=True)

    async with pg_session_factory() as session:
        after_attempt_1 = await session.get(WorkflowRunRow, run.id)
        assert after_attempt_1.state == {"next_sequence": 4}
        assert after_attempt_1.status == "completed"

    # Attempt 2: a crash-redelivered Celery task (acks_late=True, ADR-074
    # d.4) that never observed attempt 1's write -- it reconstructs from the
    # SAME starting next_sequence attempt 1 began with (not the now-advanced
    # DB value) and re-emits the byte-identical script.
    attempt_2 = ScriptedFakeRunner(
        session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
    )
    await attempt_2.run(script, final_status="completed", persist_state=False)

    async with pg_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(WorkflowRunEventRow)
                    .where(WorkflowRunEventRow.workflow_run_id == run.id)
                    .order_by(WorkflowRunEventRow.sequence_number)
                )
            )
            .scalars()
            .all()
        )

    assert [r.sequence_number for r in rows] == [1, 2, 3], (
        "two full task attempts against the same starting sequence must leave no duplicate rows"
    )
    completed_rows = [r for r in rows if r.event_type == "workflow.completed"]
    assert len(completed_rows) == 1, (
        "exactly one completion must survive the crash-replayed attempt"
    )
    assert completed_rows[0].payload == {"stop_reason": "final_response"}

    # Direct proof this is a REAL Postgres constraint, not app-level
    # idempotency logic alone: a raw duplicate INSERT for the same
    # (workflow_run_id, sequence_number) must be rejected by the database.
    async with pg_session_factory() as session:
        session.add(
            WorkflowRunEventRow(
                workflow_run_id=run.id,
                sequence_number=1,
                event_type="workflow.status",
                timestamp=datetime.now(UTC),
                payload={"phase_narration": "duplicate probe"},
                v=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
