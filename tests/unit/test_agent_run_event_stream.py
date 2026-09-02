"""``event_stream`` mechanics (``services/agent_runs/events.py``, ADR-074 decision 3).

No HTTP here; the route layer is ``test_agent_run_events_api.py``. The doubles
live in ``tests/support/event_stream.py``; ``FakePubSub`` drops a publish with
no subscriber, which is what makes the subscribe-before-replay proof real.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.services.agent_runs import event_stream, run_events_channel
from juli_backend.services.agent_runs import events as stream_events
from tests.support.builders import make_run_event, make_tenant, make_workflow_run
from tests.support.event_stream import (
    FailingSubscriber,
    FakePubSub,
    HangingSubscriber,
    PreloadedSubscriber,
    RecordingSubscriber,
    drain,
    envelope_json,
    sse_ids,
)

COMPLETED = {"event_type": "workflow.completed", "payload": {"stop_reason": "final_response"}}


class CountingSubscriber:
    """Counts ``subscribe`` calls instead of raising: a raise would be swallowed by the
    stream's degrade-to-polling handler and the test could never go red."""

    def __init__(self) -> None:
        self.calls = 0

    async def subscribe(self, channel: str):
        self.calls += 1
        return PreloadedSubscriber([]).subscribe(channel)


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def run_id(session_factory):
    """A committed ``running`` run; the stream reads it from its own sessions."""
    async with session_factory() as session:
        _, shop = await make_tenant(session)
        run = await make_workflow_run(session, shop)
        await session.commit()
        return run.id


async def insert_event(session_factory, run_id, seq: int, **event) -> None:
    async with session_factory() as session:
        await make_run_event(session, run_id, seq, **event)
        await session.commit()


def stream(run_id, session_factory, **overrides):
    options = dict(after_seq=0, run_is_terminal=False, subscriber=None)
    options.update(overrides)
    return event_stream(run_id=run_id, session_factory=session_factory, **options)


class TestReplay:
    async def test_replays_strictly_after_the_cursor_in_order(self, run_id, session_factory):
        for seq in range(1, 6):
            await insert_event(session_factory, run_id, seq)
        subscriber = CountingSubscriber()

        chunks = await drain(
            stream(
                run_id, session_factory, after_seq=2, run_is_terminal=True, subscriber=subscriber
            )
        )

        assert sse_ids(chunks) == [3, 4, 5]
        assert subscriber.calls == 0

    async def test_terminal_run_at_connect_replays_and_never_subscribes(
        self, run_id, session_factory
    ):
        await insert_event(session_factory, run_id, 1)
        await insert_event(session_factory, run_id, 2, **COMPLETED)
        subscriber = CountingSubscriber()

        chunks = await drain(
            stream(run_id, session_factory, run_is_terminal=True, subscriber=subscriber)
        )

        assert sse_ids(chunks) == [1, 2]
        assert subscriber.calls == 0

    async def test_terminal_event_closes_the_stream(self, run_id, session_factory):
        await insert_event(session_factory, run_id, 1)
        await insert_event(session_factory, run_id, 2, **COMPLETED)
        generator = stream(run_id, session_factory, subscriber=RecordingSubscriber(FakePubSub()))

        chunks = await drain(generator)

        assert sse_ids(chunks) == [1, 2]
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()


class TestLiveLeg:
    async def test_subscribe_happens_before_replay_so_the_gap_event_is_kept(
        self, run_id, session_factory, monkeypatch
    ):
        await insert_event(session_factory, run_id, 1)
        await insert_event(session_factory, run_id, 2)
        pubsub = FakePubSub()
        subscriber = RecordingSubscriber(pubsub)
        channel = run_events_channel(run_id)
        original_replay = stream_events.replay_events

        async def replay_then_publish_into_the_gap(factory, run, after_seq):
            assert subscriber.calls == [channel], "replay ran before subscribe: the gap is open"
            async for row in original_replay(factory, run, after_seq):
                yield row
            await insert_event(factory, run, 3)
            pubsub.publish(channel, envelope_json(run, 3, "workflow.status"))
            await insert_event(factory, run, 4, **COMPLETED)
            pubsub.publish(
                channel, envelope_json(run, 4, "workflow.completed", COMPLETED["payload"])
            )

        monkeypatch.setattr(stream_events, "replay_events", replay_then_publish_into_the_gap)

        chunks = await drain(stream(run_id, session_factory, subscriber=subscriber))

        assert sse_ids(chunks) == [1, 2, 3, 4]

    async def test_fake_pubsub_really_drops_a_publish_with_no_subscriber(self):
        """The property the test above depends on; a buffering fake would hide a regression."""
        pubsub = FakePubSub()

        assert pubsub.publish("run_events:x", "too early") == 0
        subscription = pubsub.subscribe("run_events:x")
        assert await subscription.get_message(timeout=0.01) is None

    async def test_live_redelivery_of_a_replayed_event_is_dropped_server_side(
        self, run_id, session_factory
    ):
        await insert_event(session_factory, run_id, 1)
        await insert_event(session_factory, run_id, 2)
        subscriber = PreloadedSubscriber(
            [
                envelope_json(run_id, 2, "workflow.status"),
                envelope_json(run_id, 3, "workflow.completed", COMPLETED["payload"]),
            ]
        )

        chunks = await drain(stream(run_id, session_factory, subscriber=subscriber))

        assert sse_ids(chunks) == [1, 2, 3]

    async def test_idle_stream_emits_heartbeats_at_the_injected_interval(
        self, run_id, session_factory
    ):
        generator = stream(
            run_id, session_factory, subscriber=PreloadedSubscriber([]), heartbeat_interval_s=0.02
        )

        frames = [await asyncio.wait_for(generator.__anext__(), timeout=1.0) for _ in range(3)]
        await generator.aclose()

        assert frames == [": connected\n\n", ": heartbeat\n\n", ": heartbeat\n\n"]

    async def test_first_byte_is_sent_before_subscribe_can_block(self, run_id, session_factory):
        """#1292: a hung Redis must not delay the first byte, or the edge buffers until timeout."""
        generator = stream(run_id, session_factory, subscriber=HangingSubscriber())

        first = await asyncio.wait_for(generator.__anext__(), timeout=0.5)
        await generator.aclose()

        assert first == ": connected\n\n"


class TestPollingFallback:
    async def test_subscribe_failure_degrades_to_postgres_polling(self, run_id, session_factory):
        async def insert_terminal_after_a_beat():
            await asyncio.sleep(0.02)
            await insert_event(session_factory, run_id, 1, **COMPLETED)

        inserter = asyncio.create_task(insert_terminal_after_a_beat())
        try:
            chunks = await asyncio.wait_for(
                drain(
                    stream(
                        run_id,
                        session_factory,
                        subscriber=FailingSubscriber(),
                        poll_interval_s=0.01,
                    )
                ),
                timeout=2.0,
            )
        finally:
            await inserter

        assert chunks[0] == ": connected\n\n"
        assert sse_ids(chunks) == [1]
        assert "workflow.completed" in chunks[1]

    async def test_no_subscriber_at_all_polls_too(self, run_id, session_factory):
        await insert_event(session_factory, run_id, 1, **COMPLETED)

        chunks = await drain(stream(run_id, session_factory, subscriber=None, poll_interval_s=0.01))

        assert sse_ids(chunks) == [1]
