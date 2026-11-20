"""The persisting event sink and the SSE replay of one answer (``agent_messages``).

Wire format (``format_sse`` of the agent-run stream; the Juli page, T4, reads the type from
``event:`` and dedupes on ``id:``)::

    id: <seq>
    event: <type>
    data: <the event's payload JSON>

``seq`` starts at 1 and is the position in ``agent_messages.events``; ``Last-Event-ID`` (else
``?after=``) resumes after it. Postgres is the replay authority and the live leg polls it: a run
executes in one API process, the stream may be served by another.

What never leaves the server: ``done.routing`` (stored in ``agent_routing_decisions``) and
``needs_choice.pending`` (stored on the message, handed back to the engine on the answer).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.agent_chat import TERMINAL_MESSAGE_STATUSES, AgentMessage
from juli_backend.services.agent_runs.events import format_sse

#: Events that end an answer's stream.
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"done", "error"})
#: Streamed text is persisted at most this often; every other event is persisted at once.
FLUSH_INTERVAL_S = 0.25
DEFAULT_POLL_INTERVAL_S = 0.5
DEFAULT_HEARTBEAT_INTERVAL_S = 15.0

_PRIVATE_FIELDS: dict[str, tuple[str, ...]] = {"done": ("routing",), "needs_choice": ("pending",)}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_wire(event: Any) -> dict[str, Any]:
    """One engine event as ``{"type", "payload"}``.

    Accepts a mapping (``{"type", "payload"}`` or ``{"type", **payload}``), a pydantic model or a
    dataclass: the engine's ``AgentEvent`` is JSON (contract), its Python class is T1's.
    """
    if hasattr(event, "model_dump"):
        raw = event.model_dump(mode="json")
    elif dataclasses.is_dataclass(event) and not isinstance(event, type):
        raw = dataclasses.asdict(event)
    elif isinstance(event, dict):
        raw = dict(event)
    else:
        raise TypeError(f"not an agent event: {type(event).__name__}")
    kind = str(raw.pop("type"))
    payload = raw.pop("payload", None)
    if payload is None:
        payload = raw
    return {"type": kind, "payload": json.loads(json.dumps(payload, default=str))}


def split_private(wire: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The event as the seller sees it, and the private fields taken out of it."""
    fields = _PRIVATE_FIELDS.get(wire["type"], ())
    payload = dict(wire["payload"])
    private = {k: payload.pop(k) for k in fields if k in payload}
    return {"type": wire["type"], "payload": payload}, private


class CancelRequested(asyncio.CancelledError):
    """Raised out of ``emit`` when the seller pressed "Dừng" (read back from the row)."""


class PersistingSink:
    """``EventSink`` for one assistant message: numbers, persists, and holds the end back.

    The engine's own ``done`` and ``error`` are NOT written by ``emit``: the runner writes the
    end last, after the drafts and routing rows, in the same transaction that finishes the
    message, so a client that sees ``done`` can send a card at once (and a router failure can
    still end as the template buttons, J11). ``unsupported.switch_platform`` is dropped unless
    the platform is one of ``switch_platforms`` (the business's other shops).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        shop_id: uuid.UUID,
        message_id: uuid.UUID,
        *,
        switch_platforms: frozenset[str] = frozenset(),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = session_factory
        self._switch_platforms = switch_platforms
        self._shop_id = shop_id
        self._message_id = message_id
        self._clock = clock
        self.events: list[dict[str, Any]] = []
        self.done: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None
        self.private: dict[str, Any] = {}
        self._flushed = 0
        self._last_flush = clock()

    async def emit(self, event: Any) -> None:
        wire = to_wire(event)
        public, private = split_private(wire)
        if public["type"] == "done":
            self.done = public
            self.private["routing"] = private.get("routing")
            return
        if public["type"] == "error":  # the runner decides the end (J11 Jev fallback, cancel)
            self.error = public
            return
        if public["type"] == "unsupported":
            # a hint only: kept when the seller's business has a shop on that platform
            hint = public["payload"].get("switch_platform")
            if hint is not None and hint not in self._switch_platforms:
                public["payload"].pop("switch_platform")
        if "pending" in private:
            self.private["pending"] = private["pending"]
        self.events.append({"seq": len(self.events) + 1, **public})
        due = self._clock() - self._last_flush >= FLUSH_INTERVAL_S
        if public["type"] != "text_delta" or due:
            await self.flush()

    async def flush(self) -> None:
        if self._flushed == len(self.events):
            return
        async with self._factory() as session, with_shop_scope(session, self._shop_id):
            cancel = await session.scalar(
                select(AgentMessage.cancel_requested).where(AgentMessage.id == self._message_id)
            )
            await session.execute(
                update(AgentMessage)
                .where(AgentMessage.id == self._message_id)
                .values(events=list(self.events), updated_at=_utcnow())
            )
            await session.commit()
        self._flushed = len(self.events)
        self._last_flush = self._clock()
        if cancel:
            raise CancelRequested()

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Add an event the runner writes itself (``done`` / ``error``); not flushed here."""
        event = {"seq": len(self.events) + 1, "type": kind, "payload": payload}
        self.events.append(event)
        return event


# -- replay ----------------------------------------------------------------------------------


def resolve_after(last_event_id: str | None, after: int | None) -> int:
    """``Last-Event-ID``, else ``?after=``, else 0; an unreadable cursor falls to the next."""
    for raw in (last_event_id, after):
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return 0


def _frame(event: dict[str, Any]) -> str:
    data = json.dumps(event["payload"], ensure_ascii=False, separators=(",", ":"))
    return format_sse(event["seq"], event["type"], data)


async def _read(
    factory: async_sessionmaker[AsyncSession], shop_id: uuid.UUID, message_id: uuid.UUID
) -> tuple[list[dict[str, Any]], str]:
    # A fresh session inherits no scope and must take one (agent_runs/events.py, #1700).
    async with factory() as session, with_shop_scope(session, shop_id):
        row = (
            await session.execute(
                select(AgentMessage.events, AgentMessage.status).where(
                    AgentMessage.id == message_id
                )
            )
        ).one_or_none()
        await session.commit()
    if row is None:
        return [], "failed"
    return list(row.events or []), row.status


async def event_stream(
    *,
    message_id: uuid.UUID,
    shop_id: uuid.UUID,
    after_seq: int,
    session_factory: async_sessionmaker[AsyncSession],
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Replay every event after ``after_seq``, then follow the row until the answer ends."""
    yield ": connected\n\n"  # first byte at once (#1292)
    last = after_seq
    quiet = 0.0
    while True:
        events, status = await _read(session_factory, shop_id, message_id)
        for event in events:
            if event["seq"] <= last:
                continue
            yield _frame(event)
            last = event["seq"]
            quiet = 0.0
            if event["type"] in TERMINAL_EVENT_TYPES:
                return
        if status in TERMINAL_MESSAGE_STATUSES:
            return
        await asyncio.sleep(poll_interval_s)
        quiet += poll_interval_s
        if quiet >= heartbeat_interval_s:
            yield ": heartbeat\n\n"
            quiet = 0.0


__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_S",
    "DEFAULT_POLL_INTERVAL_S",
    "TERMINAL_EVENT_TYPES",
    "CancelRequested",
    "PersistingSink",
    "event_stream",
    "resolve_after",
    "split_private",
    "to_wire",
]
