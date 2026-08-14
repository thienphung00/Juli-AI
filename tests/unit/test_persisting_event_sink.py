"""`PersistingEventSink` tests -- #1127 / AGT-W3B (ADR-074 decisions 1
and 3).

Proves the whole slice, in order: INSERT the row, COMMIT it, THEN publish
to `run_events:{workflow_run_id}`; a publish failure is logged and
swallowed (never re-raised, never rolls back the already-committed row); a
replayed emit colliding on the unique `(workflow_run_id, sequence_number)`
index is a no-op, not an error, with no duplicate publish either.

Every proof runs first against a real, disposable database engine so the
transactional-visibility mechanics are genuine, not mocked: an in-memory
SQLite engine (`tests/unit/conftest.py`'s `engine` fixture, a StaticPool
so every session opened from the same factory shares one underlying
connection -- see `test_api_demo_decisions.py`'s comment on the same
fixture) needs no `DATABASE_URL` and satisfies this slice's own acceptance
criterion that the suite runs with no real Postgres connection. The same
proofs are duplicated against a real, throwaway local Postgres
(`@requires_postgres`, skips cleanly without `DATABASE_URL`) because a
unique-index collision is a Postgres-level guarantee this sink leans on,
and the coordinating brief for this slice was explicit that behaviour
cannot be considered proven on a skip.

The ordering proof (`_assert_ordering_commit_before_publish`) is the load-
bearing one: the fake publisher does exactly what a real subscriber's
replay-from-Postgres read would do -- open a brand-new session against the
same database and query for the row directly, at the exact moment
`PersistingEventSink` invokes `publish()`. Under a naive sink that fired
publish before its own commit had actually landed (e.g. publish called
from inside the transaction before `await session.commit()`, or commit
kicked off as a fire-and-forget task), this independent read would race a
still-uncommitted transaction and see nothing -- an uncommitted row is
invisible to a separate session/connection under normal transaction
isolation, in SQLite and Postgres alike. The actual implementation awaits
`commit()` to completion before ever calling `publish()`, so this
independent read always finds the row.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.database.database import Base
from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.envelope import WorkflowStatusEvent
from juli_backend.services.agent.events.payloads import WorkflowStatusPayload
from juli_backend.services.agent.events.persisting_sink import (
    EventPublisher,
    PersistingEventSink,
    run_events_channel,
)
from juli_backend.services.agent.events.sink import EventSink

# ---------------------------------------------------------------------------
# Shared helpers -- event construction, seeding, fake publishers.
# ---------------------------------------------------------------------------


def _status_event(run_id: uuid.UUID, seq: int, narration: str) -> WorkflowStatusEvent:
    return WorkflowStatusEvent(
        workflow_run_id=run_id,
        sequence_number=seq,
        event_type="workflow.status",
        timestamp=datetime.now(UTC),
        payload=WorkflowStatusPayload(phase_narration=narration),
        v=1,
    )


async def _seed_shop_product_run(session: AsyncSession) -> WorkflowRunRow:
    """Minimal FK chain a `workflow_run_events` row needs: a user, a shop,
    a product, and the `workflow_runs` row the event's `workflow_run_id`
    references (matches `test_workflow_run_events_schema.py`'s seeding
    shape, made async for this sink's `AsyncSession` contract).

    ``Product.update_time`` has no ``DateTime(timezone=True)`` -- a naive
    column -- so it takes a naive datetime here. asyncpg (the real-Postgres
    path) is strict about the aware/naive mismatch a `datetime.now(UTC)`
    value would trigger there (unlike psycopg2 or SQLite, which tolerate
    it), so this stays naive for both engines rather than working by
    accident on one and not the other."""
    user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(user_id=user.id, shop_name="AGT-W3B P8-3 Test Shop")
    session.add(shop)
    await session.flush()
    product = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-w3b-p8-3-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        update_time=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(product)
    await session.flush()
    run = WorkflowRunRow(
        shop_id=shop.id,
        product_id=product.id,
        state={},
        status="running",
        prompt_version="optimize_product.v1",
        prompt_sha256="a" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run


class _NoopPublisher:
    async def publish(self, channel: str, message: str) -> None:
        return None


class _RecordingPublisher:
    """Records every publish call in order; raises nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.calls.append((channel, message))


class _RaisingPublisher:
    """Simulates Redis being down: every publish call raises."""

    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, channel: str, message: str) -> None:
        self.calls += 1
        raise RuntimeError("redis is down")


class _VisibilityCheckingPublisher:
    """The ordering proof's instrument: when `publish()` fires, it opens an
    independent session against the same database (never the session
    `PersistingEventSink` used to insert/commit) and queries directly for
    the row the event describes -- the same shape of read a real SSE
    subscriber's Postgres replay would issue."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.saw_committed_row: list[bool] = []

    async def publish(self, channel: str, message: str) -> None:
        envelope = json.loads(message)
        async with self._session_factory() as reader:
            result = await reader.execute(
                select(WorkflowRunEventRow).where(
                    WorkflowRunEventRow.workflow_run_id == uuid.UUID(envelope["workflow_run_id"]),
                    WorkflowRunEventRow.sequence_number == envelope["sequence_number"],
                )
            )
            self.saw_committed_row.append(result.scalar_one_or_none() is not None)


# ---------------------------------------------------------------------------
# The shared proofs -- parameterized over any `async_sessionmaker`, run once
# against SQLite (always) and once against real Postgres (`@requires_postgres`).
# ---------------------------------------------------------------------------


async def _assert_ordering_commit_before_publish(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        run = await _seed_shop_product_run(seed_session)
        run_id = run.id

    publisher = _VisibilityCheckingPublisher(session_factory)
    sink = PersistingEventSink(session_factory, publisher)

    await sink.emit(_status_event(run_id, 0, "ordering proof"))

    assert publisher.saw_committed_row == [True], (
        "publish() ran before an independent session could see the committed row -- "
        "a subscriber could have observed an uncommitted event"
    )


async def _assert_replayed_emit_is_a_noop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        run = await _seed_shop_product_run(seed_session)
        run_id = run.id

    publisher = _RecordingPublisher()
    sink = PersistingEventSink(session_factory, publisher)

    first = _status_event(run_id, 7, "first attempt")
    await sink.emit(first)

    # A crash-replayed emit of the SAME (workflow_run_id, sequence_number) --
    # deliberately a DIFFERENT payload, so an "upsert"-style bug that
    # silently overwrote the row instead of no-op'ing would also be caught.
    replay = _status_event(run_id, 7, "replayed attempt -- must not land")
    await sink.emit(replay)  # must not raise

    async with session_factory() as reader:
        result = await reader.execute(
            select(WorkflowRunEventRow).where(
                WorkflowRunEventRow.workflow_run_id == run_id,
                WorkflowRunEventRow.sequence_number == 7,
            )
        )
        rows = result.scalars().all()

    assert len(rows) == 1, "replayed emit produced a duplicate row"
    assert rows[0].payload["phase_narration"] == "first attempt", (
        "replayed emit overwrote the original row instead of no-op'ing"
    )
    assert len(publisher.calls) == 1, "replayed emit published again for a no-op collision"


async def _assert_publish_failure_is_swallowed_and_row_stays_committed(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with session_factory() as seed_session:
        run = await _seed_shop_product_run(seed_session)
        run_id = run.id

    publisher = _RaisingPublisher()
    sink = PersistingEventSink(session_factory, publisher)
    event = _status_event(run_id, 3, "publish will fail")

    with caplog.at_level(logging.WARNING):
        await sink.emit(event)  # must not raise -- publish failure is swallowed

    assert publisher.calls == 1
    assert any("publish failed" in record.message.lower() for record in caplog.records), (
        "publish failure was swallowed but never logged"
    )

    # Correctness is unaffected by the publish failure: a fresh session --
    # standing in for a client that replays from Postgres -- still returns
    # the event that failed to publish, and the row was never rolled back.
    async with session_factory() as reader:
        result = await reader.execute(
            select(WorkflowRunEventRow).where(
                WorkflowRunEventRow.workflow_run_id == run_id,
                WorkflowRunEventRow.sequence_number == 3,
            )
        )
        row = result.scalar_one()
    assert row.payload["phase_narration"] == "publish will fail"


# ---------------------------------------------------------------------------
# SQLite (in-memory, StaticPool) -- always run, no DATABASE_URL required.
# ---------------------------------------------------------------------------


async def test_persisting_event_sink_satisfies_event_sink_protocol(engine):
    """ADR-074 d.1: `PersistingEventSink` satisfies `EventSink` structurally,
    the same `isinstance` proof `InMemoryEventSink` gets in
    `test_workflow_run_event_sink.py` -- no shared base class required."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sink = PersistingEventSink(factory, _NoopPublisher())
    assert isinstance(sink, EventSink)


def test_arbitrary_class_with_matching_publish_satisfies_event_publisher_protocol():
    """`EventPublisher` is structurally typed the same way `EventSink` is --
    an unrelated class with no inheritance satisfies it purely by exposing a
    matching `publish` coroutine (the shape `redis.asyncio.Redis.publish`
    already has, with no adapter class required)."""

    class SomePublisher:
        async def publish(self, channel: str, message: str) -> None:
            pass

    assert isinstance(SomePublisher(), EventPublisher)


def test_class_missing_publish_does_not_satisfy_event_publisher_protocol():
    class NotAPublisher:
        async def not_publish(self, channel: str, message: str) -> None:
            pass

    assert not isinstance(NotAPublisher(), EventPublisher)


def test_run_events_channel_format():
    run_id = uuid.uuid4()
    assert run_events_channel(run_id) == f"run_events:{run_id}"


async def test_commit_lands_before_publish_is_ever_invoked(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _assert_ordering_commit_before_publish(factory)


async def test_replayed_emit_same_sequence_number_is_a_noop(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _assert_replayed_emit_is_a_noop(factory)


async def test_publish_failure_is_logged_and_swallowed_row_stays_committed(
    engine, caplog: pytest.LogCaptureFixture
):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _assert_publish_failure_is_swallowed_and_row_stays_committed(factory, caplog)


# ---------------------------------------------------------------------------
# Real, disposable local Postgres -- gated by `requires_postgres`, skips
# cleanly with no DATABASE_URL. Duplicates the three proofs above against
# a real database engine: the unique-index no-op collision and the
# cross-session commit-visibility ordering proof are guarantees this sink
# leans on at the database level, not just at the mock-call-order level.
# ---------------------------------------------------------------------------


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url:
        return False
    try:
        eng = create_engine(sync_database_url(url), pool_pre_ping=True)
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            eng.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="PersistingEventSink's real-Postgres proofs require a reachable DATABASE_URL",
)

_PG_TABLES: list[Any] = [
    User.__table__,
    Shop.__table__,
    Product.__table__,
    WorkflowRunRow.__table__,
    WorkflowRunEventRow.__table__,
]


@pytest_asyncio.fixture
async def postgres_session_factory():
    """A minimal, self-contained schema (just the 5 tables this sink's FK
    chain needs) created fresh against the real `DATABASE_URL` Postgres and
    dropped again on teardown -- deliberately independent of the Alembic
    migration chain (that belongs to `test_workflow_run_events_schema.py`;
    this is a unit test of sink *behavior*, not of the migration)."""
    eng = create_async_engine(async_database_url(_database_url()))

    def _create(sync_conn):
        Base.metadata.create_all(sync_conn, tables=_PG_TABLES)

    def _drop(sync_conn):
        Base.metadata.drop_all(sync_conn, tables=_PG_TABLES)

    async with eng.begin() as conn:
        await conn.run_sync(_create)
    try:
        yield async_sessionmaker(eng, expire_on_commit=False)
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(_drop)
        await eng.dispose()


@requires_postgres
async def test_commit_lands_before_publish_is_ever_invoked_real_postgres(
    postgres_session_factory,
):
    await _assert_ordering_commit_before_publish(postgres_session_factory)


@requires_postgres
async def test_replayed_emit_same_sequence_number_is_a_noop_real_postgres(
    postgres_session_factory,
):
    await _assert_replayed_emit_is_a_noop(postgres_session_factory)


@requires_postgres
async def test_publish_failure_is_logged_and_swallowed_row_stays_committed_real_postgres(
    postgres_session_factory, caplog: pytest.LogCaptureFixture
):
    await _assert_publish_failure_is_swallowed_and_row_stays_committed(
        postgres_session_factory, caplog
    )


@requires_postgres
async def test_real_unique_index_violation_is_the_mechanism_behind_the_noop(
    postgres_session_factory,
):
    """Belt-and-suspenders on top of `_assert_replayed_emit_is_a_noop`: the
    real Postgres unique `(workflow_run_id, sequence_number)` index --
    P8-1's `uq_workflow_run_events_run_sequence` -- is the actual mechanism
    PersistingEventSink relies on. Confirms it exists and fires at the
    database level, independent of this sink's own catch/no-op logic."""
    from sqlalchemy.exc import IntegrityError

    async with postgres_session_factory() as seed_session:
        run = await _seed_shop_product_run(seed_session)
        run_id = run.id

    async with postgres_session_factory() as session:
        session.add(
            WorkflowRunEventRow(
                workflow_run_id=run_id,
                sequence_number=0,
                event_type="workflow.status",
                timestamp=datetime.now(UTC),
                payload={"phase_narration": "first"},
                v=1,
            )
        )
        await session.commit()

        session.add(
            WorkflowRunEventRow(
                workflow_run_id=run_id,
                sequence_number=0,
                event_type="workflow.status",
                timestamp=datetime.now(UTC),
                payload={"phase_narration": "duplicate"},
                v=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
