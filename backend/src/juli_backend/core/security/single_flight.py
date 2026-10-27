"""Per-key single flight for cold identity loads (fast track P69b).

Measured live after P69 (2026-10-26): the demo page fires 4-7 requests at once, and
after >30 s idle every one of them missed the reviewer identity cache and did the whole
cold path itself -- 6-7 s each, contending for the 5 + 5 connection pool. With a single
flight, when N concurrent requests miss the cache for the SAME key, exactly one (the
leader) runs the loader; the others await its result and do no database work for it.

Semantics:

- **per key, never across keys.** The caller's key names whose facts are loaded (the
  verified JWT ``sub``, plus the pinned shop id where relevant). Two different keys
  always run two loaders; a waiter only ever receives the value loaded for its own key.
- **errors reach every waiter and are not kept.** A loader that raises fails the leader
  and every request waiting on it with that error; the entry is dropped, so the next
  request runs the loader again.
- **a cancelled leader does not fail its waiters.** When the leader's request is
  cancelled (client gone), each waiter retries: one of them becomes the new leader.
- **in-process, per event loop.** The API runs one uvicorn worker (one loop). Nothing is
  remembered after the flight lands: caching is the caller's business (``IdentityCache``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class _LeaderCancelled(Exception):
    """Set on a flight whose leader was cancelled: its waiters retry."""


class SingleFlight(Generic[K, V]):
    """Coalesce concurrent loads of the same key into one call of the loader."""

    def __init__(self) -> None:
        self._inflight: dict[K, asyncio.Future[V]] = {}

    def in_flight(self, key: K) -> bool:
        return key in self._inflight

    async def run(self, key: K, loader: Callable[[], Awaitable[V]]) -> V:
        while True:
            flight = self._inflight.get(key)
            if flight is None:
                break
            try:
                # shield: a waiter being cancelled must not cancel the leader's future.
                return await asyncio.shield(flight)
            except _LeaderCancelled:
                continue
        flight = asyncio.get_running_loop().create_future()
        self._inflight[key] = flight
        try:
            value = await loader()
        except asyncio.CancelledError:
            flight.set_exception(_LeaderCancelled())
            flight.exception()  # retrieved: no "never retrieved" warning when nobody waits
            raise
        except BaseException as exc:
            flight.set_exception(exc)
            flight.exception()
            raise
        else:
            flight.set_result(value)
            return value
        finally:
            if self._inflight.get(key) is flight:
                del self._inflight[key]


__all__ = ["SingleFlight"]
