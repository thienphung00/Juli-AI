"""Per-shop ingestion mutex (fast track SPEC §3.2, AC-1.5).

Two poll cycles for the same shop must never overlap: both would read the same
watermark, refetch the same delta and race the same upserts. The beat fans out
every fifteen minutes while a cold start can run far longer, so overlap is the
normal case without a lock, not an edge case.

Redis ``SET NX EX`` with an owner token, released by compare-and-delete --
the shape ``services/cdp_batch/shop_compute_mutex.py`` already runs in
production, so a releaser whose lock expired cannot delete the next owner's.
The TTL is a crash backstop (a worker killed mid-cycle must not wedge the shop
forever); callers size it to the cycle budget plus grace.

Two lock NAMES, deliberately: ``cycle`` (bootstrap fast phase and the regular
cycle -- these must exclude each other) and ``history`` (the low-priority
backward walk). History writes only days strictly older than the fast window,
so it may run beside a regular cycle; it must not run beside itself.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any, Literal, Protocol

#: ``cycle`` / ``history`` are mutexes. ``bootstrap_queued`` / ``history_queued``
#: are enqueue de-duplication markers: set when a task is enqueued, released
#: by that task when it starts, so a backed-up queue never accumulates one
#: copy per fan-out tick. Their TTL bounds a lost message.
LockName = Literal["cycle", "history", "bootstrap_queued", "history_queued"]

_RELEASE_IF_OWNER_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def shop_lock_key(shop_id: str, name: LockName) -> str:
    return f"ingest:{name}:{shop_id}"


class ShopIngestLock(Protocol):
    def try_acquire(self, shop_id: str, name: LockName, *, ttl_seconds: int) -> str | None:
        """Return an owner token, or ``None`` if another holder has it."""

    def release(self, shop_id: str, name: LockName, token: str) -> None: ...

    def is_held(self, shop_id: str, name: LockName) -> bool: ...


class RedisShopIngestLock:
    """Production lock on ``ingest:{name}:{shop_id}``."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def try_acquire(self, shop_id: str, name: LockName, *, ttl_seconds: int) -> str | None:
        token = uuid.uuid4().hex
        acquired = self._redis.set(
            shop_lock_key(shop_id, name), token, nx=True, ex=max(1, int(ttl_seconds))
        )
        return token if acquired else None

    def release(self, shop_id: str, name: LockName, token: str) -> None:
        self._redis.eval(_RELEASE_IF_OWNER_SCRIPT, 1, shop_lock_key(shop_id, name), token)

    def is_held(self, shop_id: str, name: LockName) -> bool:
        return bool(self._redis.exists(shop_lock_key(shop_id, name)))


class InMemoryShopIngestLock:
    """Test double with the same contract and an injectable clock."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._held: dict[str, tuple[str, float]] = {}

    def try_acquire(self, shop_id: str, name: LockName, *, ttl_seconds: int) -> str | None:
        key = shop_lock_key(shop_id, name)
        now = self._clock()
        held = self._held.get(key)
        if held is not None and held[1] > now:
            return None
        token = uuid.uuid4().hex
        self._held[key] = (token, now + ttl_seconds)
        return token

    def release(self, shop_id: str, name: LockName, token: str) -> None:
        key = shop_lock_key(shop_id, name)
        held = self._held.get(key)
        if held is not None and held[0] == token:
            del self._held[key]

    def is_held(self, shop_id: str, name: LockName) -> bool:
        held = self._held.get(shop_lock_key(shop_id, name))
        return held is not None and held[1] > self._clock()


__all__ = [
    "InMemoryShopIngestLock",
    "LockName",
    "RedisShopIngestLock",
    "ShopIngestLock",
    "shop_lock_key",
]
