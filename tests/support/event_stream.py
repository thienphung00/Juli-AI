"""Doubles for the agent-run event stream's live-subscription seam.

``FakePubSub`` has the one property that makes the subscribe-before-replay
proofs meaningful: a publish to a channel with no subscriber is dropped, as
in real Redis pub/sub. A buffering fake would make a replay-then-subscribe
regression invisible.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any


class QueueSubscription:
    """``EventSubscription`` backed by an asyncio queue."""

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
    """Channels of live subscriptions. ``publish`` returns how many received the message."""

    def __init__(self) -> None:
        self._channels: dict[str, list[QueueSubscription]] = {}

    def subscribe(self, channel: str) -> QueueSubscription:
        subscription = QueueSubscription()
        self._channels.setdefault(channel, []).append(subscription)
        return subscription

    def publish(self, channel: str, message: str) -> int:
        subscriptions = self._channels.get(channel, [])
        for subscription in subscriptions:
            subscription.queue.put_nowait(message)
        return len(subscriptions)


class RecordingSubscriber:
    """``EventSubscriber`` over a ``FakePubSub`` that logs each ``subscribe`` call."""

    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub
        self.calls: list[str] = []

    async def subscribe(self, channel: str) -> QueueSubscription:
        self.calls.append(channel)
        return self._pubsub.subscribe(channel)


class PreloadedSubscriber:
    """Every subscription starts with ``messages`` already queued."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = messages

    async def subscribe(self, channel: str) -> QueueSubscription:
        subscription = QueueSubscription()
        for message in self._messages:
            subscription.queue.put_nowait(message)
        return subscription


class FailingSubscriber:
    async def subscribe(self, channel: str) -> QueueSubscription:
        raise RuntimeError("redis subscribe failed")


class HangingSubscriber:
    """``subscribe`` never returns -- Redis slow or hung."""

    async def subscribe(self, channel: str) -> QueueSubscription:
        await asyncio.sleep(1000)
        raise AssertionError("unreachable")


def envelope_json(
    run_id: uuid.UUID, seq: int, event_type: str, payload: dict[str, Any] | None = None
) -> str:
    """A live-leg message as ``PersistingEventSink`` publishes it."""
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


def sse_ids(chunks: list[str]) -> list[int]:
    """The ``id:`` of every event frame, skipping comment frames (``: connected`` etc.)."""
    return [int(c.splitlines()[0].removeprefix("id: ")) for c in chunks if not c.startswith(":")]


async def drain(generator: Any) -> list[str]:
    return [chunk async for chunk in generator]


__all__ = [
    "FailingSubscriber",
    "FakePubSub",
    "HangingSubscriber",
    "PreloadedSubscriber",
    "QueueSubscription",
    "RecordingSubscriber",
    "drain",
    "envelope_json",
    "sse_ids",
]
