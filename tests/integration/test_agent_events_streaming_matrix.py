"""Real-Postgres, real-HTTP proof of the event-streaming contract (ADR-074 d.6, #1131).

Every prior slice tested one side against a fake: #1125 (envelope/table) against
nothing external, #1127 (``PersistingEventSink``) against a fake publisher, #1128
(the SSE/cancel/confirmations routes) against sqlite and a fake pub/sub. This is
the first place two real implementations meet: the real ``PersistingEventSink``,
real Postgres, the real FastAPI route behind a real ASGI client, and a
**scripted fake runner** standing in for #1119's not-yet-wired ``WorkflowRunner``
(ADR-074 d.6 asks for a scripted driver here, not the real runner).

Skips the whole module without a reachable Postgres ``DATABASE_URL`` -- a skipped
integration test proves nothing, and `tests.support.postgres.requires_postgres`
says so in its skip reason. Lifecycle and crash-resume cases live in the sibling
module `test_agent_events_lifecycle.py`, which imports this module's Postgres
fixtures and doubles rather than redefining them.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.api.app import create_app
from juli_backend.api.dependencies import get_active_shop
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
from juli_backend.models.models import Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.events.envelope import WorkflowRunEventAdapter
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent_runs import events as stream_events
from tests.support.builders import make_tenant, make_workflow_run
from tests.support.event_stream import QueueSubscription
from tests.support.postgres import database_url, requires_postgres

pytestmark = requires_postgres

# ---------------------------------------------------------------------------
# A throwaway Postgres database, created from `DATABASE_URL`'s own connection
# parameters (own name, same server/credentials) and dropped at session
# teardown -- never DATABASE_URL's own database. `tests/integration/test_migrations.py`
# and `test_schema_parity.py` run a full Alembic downgrade/upgrade round trip
# against that database; a session-scoped `Base.metadata.create_all` run straight
# against it collides (`DuplicateTable`). Mirrors #1121's
# `tests/unit/test_agent_runner_ledger.py` fix: one disposable database per test
# session, dropped via an admin connection to the `postgres` maintenance database.
# DDL setup is a plain sync engine (psycopg2) -- pytest-asyncio's fixture-loop
# scope is per-function here, so a session-scoped asyncpg connection would be
# reused across event loops (the same "Future attached to a different loop"
# failure `tests/unit/conftest.py` documents for Redis).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _disposable_postgres_url():
    base_url = database_url()
    admin_url = make_url(sync_database_url(base_url)).set(database="postgres")
    db_name = f"juli_agt_w3b_1131_{uuid.uuid4().hex[:12]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    disposable_url = make_url(sync_database_url(base_url)).set(database=db_name)
    try:
        # `str(URL)` masks the password as `***` -- render it explicitly or the
        # connection authenticates with a literal `***` (#1121 carried this too).
        yield disposable_url.render_as_string(hide_password=False)
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


@pytest.fixture(scope="session")
def _postgres_schema_ready(_disposable_postgres_url: str) -> None:
    engine = create_engine(_disposable_postgres_url, pool_pre_ping=True)
    # `models/models.py` schema-qualifies some tables that only exist in a
    # fully Alembic-migrated database -- a fresh `CREATE DATABASE` never has
    # them (mirrors #1121's `_build_postgres_engine`).
    with engine.begin() as conn:
        for schema_name in ("bronze", "silver", "gold", "ops"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        Base.metadata.create_all(conn, checkfirst=True)
    engine.dispose()


@pytest_asyncio.fixture
async def pg_engine(_disposable_postgres_url: str, _postgres_schema_ready: None):
    engine = create_async_engine(async_database_url(_disposable_postgres_url))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session_factory(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Seeding -- tests/support/builders.py, wrapped only to open+commit against
# this module's disposable session factory (builders themselves only flush;
# the caller owns the transaction, same contract as everywhere else).
# ---------------------------------------------------------------------------


async def seed_shop(session_factory: async_sessionmaker[AsyncSession]) -> tuple[User, Shop]:
    async with session_factory() as session:
        user, shop = await make_tenant(session)
        await session.commit()
        return user, shop


async def seed_run(
    session_factory: async_sessionmaker[AsyncSession],
    shop: Shop,
    *,
    status: str = "running",
) -> WorkflowRunRow:
    """A run whose ``state["next_sequence"]`` starts at 1 -- the only counter
    `sequence_number` is ever minted from (ADR-074 decision 1)."""
    async with session_factory() as session:
        run = await make_workflow_run(session, shop, status=status, state={"next_sequence": 1})
        await session.commit()
        await session.refresh(run)
        return run


# ---------------------------------------------------------------------------
# The scripted fake runner (ADR-074 d.6) -- NOT #1119's real `WorkflowRunner`,
# which does not exist on this branch. Mints `sequence_number` from an
# in-memory counter seeded from `starting_sequence` (standing in for reading
# `workflow_runs.state["next_sequence"]`), builds a real envelope via
# `WorkflowRunEventAdapter` for each step, and calls the real `EventSink.emit`.
# `persist_state=False` models a crash: the write that would have advanced
# `workflow_runs.state` never happens, so a second runner built with the same
# `starting_sequence` reproduces a crash-redelivered Celery task
# (`acks_late=True`, ADR-074 d.4) -- relying on the sink's unique-index no-op,
# never on any state this class would have to fabricate.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptedEvent:
    event_type: str
    payload: dict = field(default_factory=dict)


def standard_script(product_ref: str) -> list[ScriptedEvent]:
    """A representative happy path: started -> status -> completed."""
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
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        sink: PersistingEventSink,
        run_id: uuid.UUID,
        starting_sequence: int,
    ) -> None:
        self._session_factory = session_factory
        self._sink = sink
        self._run_id = run_id
        self._next_sequence = starting_sequence

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
                    "timestamp": datetime.now(UTC),
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
# A fake Redis playing both roles the real implementations meet at --
# `EventPublisher` (`persisting_sink.py`) and `EventSubscriber`
# (`agent_runs.py`). Publishing to a channel with no live subscriber drops the
# message, real Redis pub/sub semantics and the property the handoff-overlap
# test depends on. `QueueSubscription` is `tests/support/event_stream.py`'s;
# the outage simulation and the subscribed-signal below are specific to
# proving a real Redis publisher/subscriber pair, so they stay local.
# ---------------------------------------------------------------------------


class FakeRedisBus:
    def __init__(self) -> None:
        self._channels: dict[str, list[QueueSubscription]] = {}
        self._subscribed: dict[str, asyncio.Event] = {}
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
        self._subscribed.setdefault(channel, asyncio.Event()).set()
        return sub

    async def wait_until_subscribed(self, channel: str, *, timeout: float = 2.0) -> None:
        """Block until something has subscribed to ``channel`` -- the
        deterministic trigger a background writer waits on instead of
        sleeping a fixed duration and hoping the SSE route has connected."""
        event = self._subscribed.setdefault(channel, asyncio.Event())
        await asyncio.wait_for(event.wait(), timeout=timeout)

    def simulate_outage(self) -> None:
        """From here: publish drops silently, any NEW subscribe fails --
        indistinguishable, from an already-open SSE stream's side, from a
        real dead Redis connection going quiet."""
        self._down = True


class SignalingFailingSubscriber:
    """Always fails to subscribe, but signals the attempt -- the deterministic
    trigger a background writer waits on instead of sleeping a fixed duration
    before assuming the route has already tried Redis and fallen back to
    polling."""

    def __init__(self) -> None:
        self.attempted = asyncio.Event()

    async def subscribe(self, channel: str) -> QueueSubscription:
        self.attempted.set()
        raise ConnectionError("redis subscribe failed")


# ---------------------------------------------------------------------------
# App/client wiring -- every seam FastAPI already exposes for override,
# wired to real Postgres.
# ---------------------------------------------------------------------------


def build_app(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    subscriber,
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


def set_auth_overrides(app, user: User, shop: Shop) -> None:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop


def authenticated_client(app, user: User, shop: Shop) -> AsyncClient:
    set_auth_overrides(app, user, shop)
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


# ---------------------------------------------------------------------------
# A REAL uvicorn server on an OS-assigned loopback port -- needed for exactly
# one scenario: a genuine mid-stream client disconnect. `httpx.ASGITransport`
# `await`s the entire ASGI app call to completion before returning any
# `Response` (verified by reading `httpx._transports.asgi.ASGITransport.
# handle_async_request`), so an infinite live SSE generator (still-running
# run) means that `await` never returns -- not a production bug, a limitation
# of the in-process test transport. Every other test reads a full (finite)
# response through the lighter `ASGITransport` path above.
# ---------------------------------------------------------------------------


class _LiveUvicornServer:
    def __init__(self, app) -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
        self._server = uvicorn.Server(config)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> str:
        self._task = asyncio.create_task(self._server.serve())
        await asyncio.wait_for(self._wait_started(), timeout=5.0)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def _wait_started(self) -> None:
        while not self._server.started:
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            await self._task


@pytest_asyncio.fixture
async def live_client_factory():
    """Yields a callable ``(app) -> AsyncClient`` bound to a real, running
    uvicorn server -- a genuine TCP connection a test can disconnect
    mid-stream, unlike the in-process ``ASGITransport`` path."""
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
# SSE parsing + a minimal real-cursor client -- the piece of #1132's
# fetch-streaming contract this route owns: track the last observed `id:` and
# never deduplicate client-side (ADR-074 d.3/d.5), reconnecting via
# `Last-Event-ID` rather than a hand-set `?after=`.
# ---------------------------------------------------------------------------


def parse_sse_block(block: str) -> dict[str, str] | None:
    if not block or block.startswith(":"):
        return None
    record: dict[str, str] = {}
    for line in block.split("\n"):
        key, _, value = line.partition(": ")
        record[key] = value
    return record


def record_ids(body: str) -> list[int]:
    blocks = (parse_sse_block(b) for b in body.strip("\n").split("\n\n"))
    return [int(record["id"]) for record in blocks if record is not None]


def is_terminal_record(record: dict[str, str]) -> bool:
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
        """Connects with ``Last-Event-ID`` set to this client's own cursor
        (never a hand-set ``?after=``) and reads until ``predicate`` is met,
        ``max_records`` new records have arrived, or the server closes the
        stream. Returning early inside the ``async with`` below cancels the
        read -- a client walking away / a network blip, the exact disconnect
        a reconnect test needs."""
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
                        record = parse_sse_block(block)
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
# Tests
# ---------------------------------------------------------------------------


class TestReplay:
    """``after=k`` replays exactly ``k+1..N``, ordered, with no gaps or duplicates."""

    async def test_full_and_tail_replay_are_exact(self, pg_session_factory):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="completed")
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

        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, user, shop) as client:
            full = await client.get(f"/v1/demo/runs/{run.id}/events")
            tail = await client.get(f"/v1/demo/runs/{run.id}/events", params={"after": 3})

        all_ids = record_ids(full.text)
        assert all_ids == [1, 2, 3, 4, 5, 6]
        assert len(set(all_ids)) == len(all_ids), "no duplicates in a full replay"
        assert record_ids(tail.text) == [4, 5, 6], "after=3 must yield exactly 4..6"


class TestHandoffOverlap:
    """An event published in the replay-end/subscribe-start gap arrives exactly once."""

    async def test_event_published_in_the_gap_arrives_exactly_once(
        self, pg_session_factory, monkeypatch
    ):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        opening = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await opening.run(
            [
                ScriptedEvent(
                    "workflow.started",
                    {
                        "workflow_key": "optimize_product",
                        "product_ref": "p1",
                        "prompt_version": "v1",
                    },
                ),
                ScriptedEvent("workflow.status", {"phase_narration": "opening"}),
            ],
        )

        original_replay = stream_events.replay_events

        async def hooked_replay(session_factory_arg, run_id_arg, after_seq_arg):
            async for row in original_replay(session_factory_arg, run_id_arg, after_seq_arg):
                yield row
            # By construction this runs strictly after `event_stream` has
            # already subscribed (subscribe-before-replay, ADR-074 d.3) and
            # strictly before it consumes the live subscription -- the exact
            # window a naive replay-then-subscribe implementation would still
            # be racing. Committed AND published for real; must arrive via
            # the live leg, or not at all.
            gap_runner = ScriptedFakeRunner(
                session_factory=session_factory_arg,
                sink=sink,
                run_id=run_id_arg,
                starting_sequence=3,
            )
            await gap_runner.run(
                [
                    ScriptedEvent("workflow.status", {"phase_narration": "in the gap"}),
                    ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
                ],
                final_status="completed",
            )

        monkeypatch.setattr(stream_events, "replay_events", hooked_replay)

        app = build_app(pg_session_factory, subscriber=bus)
        async with authenticated_client(app, user, shop) as client:
            resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0)

        assert resp.status_code == 200
        assert record_ids(resp.text) == [1, 2, 3, 4], (
            "event 3, published in the replay-end/subscribe-start gap, must arrive "
            "exactly once -- lost or duplicated are both a regression"
        )
        assert bus.publish_log, "the real bus's publish() must actually have been exercised"


class TestRedisLoss:
    """A subscribe failure, or Redis going quiet mid-stream, still delivers every event."""

    async def test_subscribe_failure_degrades_to_polling_and_still_delivers(
        self, pg_session_factory
    ):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        subscriber = SignalingFailingSubscriber()

        async def _emit_after_subscribe_attempted() -> None:
            await subscriber.attempted.wait()
            runner = ScriptedFakeRunner(
                session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
            )
            await runner.run(standard_script("p1"), final_status="completed")

        app = build_app(pg_session_factory, subscriber=subscriber, poll_interval_s=0.02)
        task = asyncio.create_task(_emit_after_subscribe_attempted())
        try:
            async with authenticated_client(app, user, shop) as client:
                resp = await asyncio.wait_for(
                    client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0
                )
        finally:
            await task

        assert resp.status_code == 200
        assert record_ids(resp.text) == [1, 2, 3], (
            "subscribe failure must degrade to Postgres polling, not drop events"
        )

    async def test_mid_stream_loss_reconnect_via_last_event_id_replays_gaplessly(
        self, pg_session_factory, live_client_factory
    ):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        runner = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await runner.run(
            [
                ScriptedEvent(
                    "workflow.started",
                    {
                        "workflow_key": "optimize_product",
                        "product_ref": "p1",
                        "prompt_version": "v1",
                    },
                ),
                ScriptedEvent("workflow.status", {"phase_narration": "opening"}),
            ],
        )

        # A genuine mid-stream client disconnect needs a real TCP connection
        # (see `_LiveUvicornServer` above).
        app = build_app(pg_session_factory, subscriber=bus, poll_interval_s=0.02)
        set_auth_overrides(app, user, shop)
        client = await live_client_factory(app)
        reader = RealCursorClient(client, f"/v1/demo/runs/{run.id}/events")

        # First connection: replay 1, 2 (nothing more exists yet), then the
        # client walks away -- the network blip / Redis loss this case is about.
        await reader.read_until(lambda r: False, max_records=2)
        assert [int(r["id"]) for r in reader.received] == [1, 2]

        # Redis is down for good. Two more events land while nobody is live-subscribed.
        bus.simulate_outage()
        await runner.run(
            [
                ScriptedEvent("workflow.status", {"phase_narration": "closing"}),
                ScriptedEvent("workflow.completed", {"stop_reason": "final_response"}),
            ],
            final_status="completed",
        )

        # Reconnect driven by the client's own cursor (`Last-Event-ID: 2`),
        # never a hand-set `?after=`. subscribe() now fails, exercising the
        # polling fallback too.
        await reader.read_until(is_terminal_record)

        ids = [int(r["id"]) for r in reader.received]
        assert ids == [1, 2, 3, 4], "reconnect via Last-Event-ID must replay the gap gaplessly"
        assert len(set(ids)) == len(ids), "no duplicates across the reconnect boundary"


class TestCursorResolution:
    """``Last-Event-ID`` beats ``?after=`` beats ``0``; a malformed or
    out-of-``int4``-range cursor degrades to the next source instead of
    500ing or silently replaying nothing (#1131 issue thread, #1142 rework).
    """

    @pytest_asyncio.fixture
    async def two_event_completed_run(self, pg_session_factory):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="completed")
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
        return user, shop, run

    @pytest.mark.parametrize(
        ("params", "headers", "expected_ids"),
        [
            pytest.param({"after": 0}, {"Last-Event-ID": "1"}, [2], id="header-outranks-after"),
            pytest.param({"after": 1}, {}, [2], id="after-used-without-a-header"),
            pytest.param({}, {}, [1, 2], id="zero-used-without-header-or-after"),
            pytest.param(
                {"after": 1},
                {"Last-Event-ID": "not-a-number"},
                [2],
                id="non-numeric-header-degrades-to-after",
            ),
            pytest.param(
                {},
                {"Last-Event-ID": "not-a-number"},
                [1, 2],
                id="non-numeric-header-degrades-to-zero",
            ),
            pytest.param(
                {"after": 1},
                {"Last-Event-ID": str(2**200)},
                [2],
                id="huge-header-degrades-to-after-not-overflow",
            ),
            pytest.param(
                {},
                {"Last-Event-ID": str(2**200)},
                [1, 2],
                id="huge-header-degrades-to-zero-not-overflow",
            ),
            pytest.param(
                {"after": 1},
                {"Last-Event-ID": "-5"},
                [1, 2],
                id="negative-header-clamps-to-zero-still-outranks-after",
            ),
            pytest.param(
                {"after": 2**200}, {}, [1, 2], id="huge-after-degrades-to-zero-not-overflow"
            ),
        ],
    )
    async def test_cursor_source_and_degrade(
        self, pg_session_factory, two_event_completed_run, params, headers, expected_ids
    ):
        user, shop, run = two_event_completed_run
        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, user, shop) as client:
            resp = await client.get(
                f"/v1/demo/runs/{run.id}/events", params=params, headers=headers
            )

        assert resp.status_code == 200, resp.text
        assert record_ids(resp.text) == expected_ids
