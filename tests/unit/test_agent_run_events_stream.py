"""`event_stream` mechanics -- ADR-074 decision 3, #1128 / AGT-W3B.

Exercises `api/routes/agent_runs.event_stream` directly (no FastAPI/HTTP in
this file -- that layer, plus tenant scoping and the wire format, is
`test_agent_run_events_api.py`). Each proof matches one acceptance
criterion of issue #1128:

- `test_after_seq_replay_is_strictly_ordered_no_gaps_no_duplicates` -- AC2.
- `test_subscribe_before_replay_closes_the_gap` / the paired
  `test_naive_replay_then_subscribe_drops_the_race_event` -- AC1, the
  load-bearing pair. The second test proves `FakePubSub` has the one
  property that makes the first meaningful: publishing to a channel with
  zero registered subscribers drops the message (real Redis pub/sub
  semantics, not a buffering mock) -- so if `event_stream` ever regressed
  to replay-then-subscribe, the first test would fail exactly the way the
  second demonstrates a naive implementation does.
- `test_server_side_dedupe_of_live_redelivery` -- AC3.
- `test_heartbeat_emitted_on_idle_stream_within_injected_interval` -- AC4.
- `test_terminal_event_closes_stream_no_further_reads_succeed` -- AC5.
- `test_already_terminal_run_at_connect_replays_and_never_subscribes` --
  AC6.
- `test_subscribe_failure_degrades_to_postgres_polling` -- AC7.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.api.routes import agent_runs
from juli_backend.api.routes.agent_runs import event_stream
from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.persisting_sink import run_events_channel

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _seed_run(session: AsyncSession) -> uuid.UUID:
    user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(user_id=user.id, shop_name="AGT-W3B P8-4 Test Shop")
    session.add(shop)
    await session.flush()
    product = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-w3b-p8-4-{uuid.uuid4()}",
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
    return run.id


async def _insert_event(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    seq: int,
    event_type: str = "workflow.status",
    payload: dict | None = None,
) -> None:
    async with session_factory() as session:
        row = WorkflowRunEventRow(
            workflow_run_id=run_id,
            sequence_number=seq,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            payload=payload if payload is not None else {"phase_narration": f"seq-{seq}"},
            v=1,
        )
        session.add(row)
        await session.commit()


def _envelope_json(
    run_id: uuid.UUID, seq: int, event_type: str, payload: dict | None = None
) -> str:
    return json.dumps(
        {
            "workflow_run_id": str(run_id),
            "sequence_number": seq,
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload or {},
            "v": 1,
        }
    )


def _chunk_ids(chunks: list[str]) -> list[int]:
    return [int(c.splitlines()[0].removeprefix("id: ")) for c in chunks if not c.startswith(":")]


async def _drain(gen) -> list[str]:
    return [chunk async for chunk in gen]


# ---------------------------------------------------------------------------
# Fakes -- a realistic in-memory pub/sub: publishing to a channel nobody has
# subscribed to yet drops the message, exactly like real Redis pub/sub. This
# realism is the point (see module docstring).
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


class FakePubSub:
    def __init__(self) -> None:
        self._channels: dict[str, list[QueueSubscription]] = {}

    def subscribe(self, channel: str) -> QueueSubscription:
        sub = QueueSubscription()
        self._channels.setdefault(channel, []).append(sub)
        return sub

    def publish(self, channel: str, message: str) -> int:
        subs = self._channels.get(channel, [])
        for sub in subs:
            sub.queue.put_nowait(message)
        return len(subs)


class RecordingSubscriber:
    def __init__(self, pubsub: FakePubSub, call_log: list[str]) -> None:
        self._pubsub = pubsub
        self._call_log = call_log

    async def subscribe(self, channel: str) -> QueueSubscription:
        self._call_log.append("subscribe")
        return self._pubsub.subscribe(channel)


class PreloadedSubscriber:
    """Returns a subscription whose queue already holds `messages`."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = messages

    async def subscribe(self, channel: str) -> QueueSubscription:
        sub = QueueSubscription()
        for message in self._messages:
            sub.queue.put_nowait(message)
        return sub


class FailingSubscriber:
    async def subscribe(self, channel: str) -> QueueSubscription:
        raise RuntimeError("redis subscribe failed")


class CountingSubscriber:
    """Records how many times `subscribe()` was called, without raising.

    An earlier version of this fake (`NeverCalledSubscriber`) proved
    "never subscribed" by raising `AssertionError` from `subscribe()`.
    That signal is untrustworthy: `event_stream`'s own subscribe-failure
    handling wraps the call in a blanket `except Exception` (the same
    mechanism that implements the graceful degrade-to-polling in AC7), so
    a raise from inside `subscribe()` is caught, logged, and silently
    treated as "Redis unavailable, fall back" -- indistinguishable from
    every other subscribe failure. If the already-terminal short-circuit
    ever regressed and started subscribing anyway, the raise would still
    be swallowed and the replayed output would look identical, so that
    test could never go red. Recording a plain counter and asserting on
    it *after* the stream completes is a signal the route cannot eat.
    """

    def __init__(self) -> None:
        self.call_count = 0

    async def subscribe(self, channel: str) -> QueueSubscription:
        self.call_count += 1
        return QueueSubscription()


# ---------------------------------------------------------------------------
# AC2 -- exact after=k replay
# ---------------------------------------------------------------------------


async def test_after_seq_replay_is_strictly_ordered_no_gaps_no_duplicates(session_factory):
    run_id = await _seed_run_via_factory(session_factory)
    for seq in range(1, 6):
        await _insert_event(session_factory, run_id, seq)

    subscriber = CountingSubscriber()
    chunks = await _drain(
        event_stream(
            run_id=run_id,
            after_seq=2,
            run_is_terminal=True,  # skip subscribe entirely -- pure replay ordering proof
            session_factory=session_factory,
            subscriber=subscriber,
        )
    )

    assert _chunk_ids(chunks) == [3, 4, 5]
    assert subscriber.call_count == 0


# ---------------------------------------------------------------------------
# AC1 -- subscribe before replay closes the gap
# ---------------------------------------------------------------------------


async def test_subscribe_before_replay_closes_the_gap(session_factory, monkeypatch):
    run_id = await _seed_run_via_factory(session_factory)
    await _insert_event(session_factory, run_id, 1)
    await _insert_event(session_factory, run_id, 2)

    pubsub = FakePubSub()
    call_log: list[str] = []
    subscriber = RecordingSubscriber(pubsub, call_log)
    channel = run_events_channel(run_id)

    original_replay = agent_runs._replay_events

    async def hooked_replay(session_factory_arg, run_id_arg, after_seq_arg):
        # By the time replay runs, subscribe must already have happened --
        # this IS the ordering the whole test exists to enforce.
        assert call_log == ["subscribe"], "replay ran before subscribe -- the gap is open"
        async for row in original_replay(session_factory_arg, run_id_arg, after_seq_arg):
            yield row
        # Simulate a concurrent emitter landing exactly in the window a
        # naive replay-then-subscribe implementation would still be racing:
        # "replay just ended," about to (too late, in the naive version)
        # call subscribe(). Event 3 is committed to Postgres and published
        # here, followed immediately by the terminal event 4 so the live
        # leg closes deterministically instead of idling on a heartbeat.
        await _insert_event(session_factory_arg, run_id_arg, 3)
        pubsub.publish(channel, _envelope_json(run_id_arg, 3, "workflow.status"))
        await _insert_event(
            session_factory_arg,
            run_id_arg,
            4,
            event_type="workflow.completed",
            payload={"stop_reason": "final_response"},
        )
        pubsub.publish(
            channel,
            _envelope_json(run_id_arg, 4, "workflow.completed", {"stop_reason": "final_response"}),
        )

    monkeypatch.setattr(agent_runs, "_replay_events", hooked_replay)

    chunks = await _drain(
        event_stream(
            run_id=run_id,
            after_seq=0,
            run_is_terminal=False,
            session_factory=session_factory,
            subscriber=subscriber,
        )
    )

    assert _chunk_ids(chunks) == [1, 2, 3, 4], (
        "event 3, published in the replay-end/subscribe-start gap, must not be lost"
    )


async def test_naive_replay_then_subscribe_drops_the_race_event():
    """Proves `FakePubSub`'s realism: with nobody subscribed yet, a publish
    into the exact race window is simply gone -- the property that makes
    the test above a genuine regression guard rather than an accident."""
    pubsub = FakePubSub()
    channel = "run_events:naive-demo"

    # Naive order: replay first, publish races in before subscribe() runs.
    delivered_to = pubsub.publish(channel, "event-that-arrives-too-early")
    assert delivered_to == 0

    # Only now does the naive implementation subscribe -- nothing is queued.
    sub = pubsub.subscribe(channel)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(sub.queue.get(), timeout=0.05)


# ---------------------------------------------------------------------------
# AC3 -- server-side dedupe
# ---------------------------------------------------------------------------


async def test_server_side_dedupe_of_live_redelivery(session_factory):
    run_id = await _seed_run_via_factory(session_factory)
    await _insert_event(session_factory, run_id, 1)
    await _insert_event(session_factory, run_id, 2)

    # The live leg redelivers event 2 (already covered by replay) before a
    # genuinely new terminal event 3.
    messages = [
        _envelope_json(run_id, 2, "workflow.status"),
        _envelope_json(run_id, 3, "workflow.completed", {"stop_reason": "final_response"}),
    ]
    subscriber = PreloadedSubscriber(messages)

    chunks = await _drain(
        event_stream(
            run_id=run_id,
            after_seq=0,
            run_is_terminal=False,
            session_factory=session_factory,
            subscriber=subscriber,
        )
    )

    ids = _chunk_ids(chunks)
    assert ids == [1, 2, 3], "event 2's live redelivery must be dropped server-side, not duplicated"


# ---------------------------------------------------------------------------
# AC4 -- heartbeat on an idle stream
# ---------------------------------------------------------------------------


async def test_heartbeat_emitted_on_idle_stream_within_injected_interval(session_factory):
    run_id = await _seed_run_via_factory(session_factory)
    subscriber = PreloadedSubscriber([])  # never delivers anything -- pure idle

    gen = event_stream(
        run_id=run_id,
        after_seq=0,
        run_is_terminal=False,
        session_factory=session_factory,
        subscriber=subscriber,
        heartbeat_interval_s=0.05,
    )

    first = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    second = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert first == ": heartbeat\n\n"
    assert second == ": heartbeat\n\n"
    await gen.aclose()


# ---------------------------------------------------------------------------
# AC5 -- terminal event closes the stream
# ---------------------------------------------------------------------------


async def test_terminal_event_closes_stream_no_further_reads_succeed(session_factory):
    run_id = await _seed_run_via_factory(session_factory)
    await _insert_event(session_factory, run_id, 1)
    await _insert_event(
        session_factory,
        run_id,
        2,
        event_type="workflow.completed",
        payload={"stop_reason": "final_response"},
    )
    call_log: list[str] = []
    subscriber = RecordingSubscriber(FakePubSub(), call_log)

    gen = event_stream(
        run_id=run_id,
        after_seq=0,
        run_is_terminal=False,
        session_factory=session_factory,
        subscriber=subscriber,
    )

    chunks = await _drain(gen)
    assert _chunk_ids(chunks) == [1, 2]

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


# ---------------------------------------------------------------------------
# AC6 -- already-terminal run at connect: full replay, never subscribes
# ---------------------------------------------------------------------------


async def test_already_terminal_run_at_connect_replays_and_never_subscribes(session_factory):
    run_id = await _seed_run_via_factory(session_factory)
    await _insert_event(session_factory, run_id, 1)
    await _insert_event(
        session_factory,
        run_id,
        2,
        event_type="workflow.completed",
        payload={"stop_reason": "final_response"},
    )

    subscriber = CountingSubscriber()
    chunks = await _drain(
        event_stream(
            run_id=run_id,
            after_seq=0,
            run_is_terminal=True,
            session_factory=session_factory,
            subscriber=subscriber,
        )
    )

    assert _chunk_ids(chunks) == [1, 2]
    assert subscriber.call_count == 0, (
        "an already-terminal run at connect must never attempt to subscribe"
    )


# ---------------------------------------------------------------------------
# AC7 -- subscribe failure degrades to Postgres polling
# ---------------------------------------------------------------------------


async def test_subscribe_failure_degrades_to_postgres_polling(session_factory):
    run_id = await _seed_run_via_factory(session_factory)

    async def _insert_terminal_shortly():
        await asyncio.sleep(0.05)
        await _insert_event(
            session_factory,
            run_id,
            1,
            event_type="workflow.completed",
            payload={"stop_reason": "final_response"},
        )

    insert_task = asyncio.create_task(_insert_terminal_shortly())
    try:
        chunks = await asyncio.wait_for(
            _drain(
                event_stream(
                    run_id=run_id,
                    after_seq=0,
                    run_is_terminal=False,
                    session_factory=session_factory,
                    subscriber=FailingSubscriber(),
                    poll_interval_s=0.02,
                )
            ),
            timeout=2.0,
        )
    finally:
        await insert_task

    assert _chunk_ids(chunks) == [1]
    assert "workflow.completed" in chunks[0]


# ---------------------------------------------------------------------------
# Shared fixture: a session_factory bound to the in-memory SQLite engine,
# plus a helper that seeds through it (rather than the plain `session`
# fixture) so every read in these tests -- including `event_stream`'s own
# fresh-session-per-read pattern -- shares the same underlying database.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_run_via_factory(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        return await _seed_run(session)
