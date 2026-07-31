"""Shop-scoped compute mutex shared by CDP batch and speed paths (#618 / CDP-A2-4).

Redis key ``compute:{shop_id}`` with documented TTL. Batch reconcile **defers** when
speed compute holds the lock — structured reason ``speed_mutex_active``. Distinct from
ETL ingest / ``material_analytics:mutex:*`` enqueue gates and asyncio backpressure.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

DEFER_REASON = "speed_mutex_active"

# TTL for orphaned compute locks (speed or batch). Refreshed on acquire.
COMPUTE_MUTEX_TTL_SECONDS = 600

ComputeOwner = Literal["speed", "batch"]

# Atomic compare-and-delete: stale releaser cannot remove a new owner's lock.
_RELEASE_IF_OWNER_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

# Atomic compare-and-expire: same-owner refresh cannot clobber a new owner after TTL rollover.
_REFRESH_IF_OWNER_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('set', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
else
    return 0
end
"""


def _normalize_owner(raw: object) -> ComputeOwner | None:
    """Decode redis-py bytes responses and validate owner tokens."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if raw == "speed":
        return "speed"
    if raw == "batch":
        return "batch"
    return None


def compute_mutex_key(shop_id: str) -> str:
    """Redis key for shop-scoped Shared Compute exclusion."""
    return f"compute:{shop_id}"


@dataclass(frozen=True, slots=True)
class BatchComputeEntryResult:
    """Outcome of batch reconcile entry through the compute mutex."""

    acquired: bool
    defer_reason: str | None = None

    def structured_log_fields(self) -> dict[str, str | None]:
        """Observability fields when batch defers or proceeds."""
        return {
            "defer_reason": self.defer_reason,
            "stopped_reason": self.defer_reason,
        }


class ShopComputeMutex(Protocol):
    """Acquire/release API for batch and speed Shared Compute callers."""

    def try_acquire(self, shop_id: str, owner: ComputeOwner) -> bool: ...

    def release(self, shop_id: str, owner: ComputeOwner) -> None: ...

    def current_owner(self, shop_id: str) -> ComputeOwner | None: ...


@dataclass
class _LockState:
    owner: ComputeOwner
    expires_at: float


class InMemoryShopComputeMutex:
    """Test-friendly mutex with injectable clock."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = COMPUTE_MUTEX_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._locks: dict[str, _LockState] = {}

    def _purge_expired(self, shop_id: str) -> None:
        state = self._locks.get(shop_id)
        if state is not None and self._clock() >= state.expires_at:
            del self._locks[shop_id]

    def current_owner(self, shop_id: str) -> ComputeOwner | None:
        self._purge_expired(shop_id)
        state = self._locks.get(shop_id)
        return state.owner if state is not None else None

    def try_acquire(self, shop_id: str, owner: ComputeOwner) -> bool:
        self._purge_expired(shop_id)
        state = self._locks.get(shop_id)
        now = self._clock()
        if state is not None:
            if state.owner != owner:
                return False
            state.expires_at = now + self._ttl
            return True
        self._locks[shop_id] = _LockState(owner=owner, expires_at=now + self._ttl)
        return True

    def release(self, shop_id: str, owner: ComputeOwner) -> None:
        self._purge_expired(shop_id)
        state = self._locks.get(shop_id)
        if state is not None and state.owner == owner:
            del self._locks[shop_id]


class RedisShopComputeMutex:
    """Production mutex backed by Redis ``SET NX`` on ``compute:{shop_id}``."""

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = COMPUTE_MUTEX_TTL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds

    def current_owner(self, shop_id: str) -> ComputeOwner | None:
        raw = self._redis.get(compute_mutex_key(shop_id))
        return _normalize_owner(raw)

    def try_acquire(self, shop_id: str, owner: ComputeOwner) -> bool:
        key = compute_mutex_key(shop_id)
        acquired = self._redis.set(key, owner, nx=True, ex=self._ttl)
        if acquired:
            return True
        refreshed = self._redis.eval(
            _REFRESH_IF_OWNER_SCRIPT,
            1,
            key,
            owner,
            str(self._ttl),
        )
        return bool(refreshed)

    def release(self, shop_id: str, owner: ComputeOwner) -> None:
        key = compute_mutex_key(shop_id)
        self._redis.eval(_RELEASE_IF_OWNER_SCRIPT, 1, key, owner)


def try_begin_batch_compute(
    mutex: ShopComputeMutex,
    shop_id: str,
) -> BatchComputeEntryResult:
    """Batch reconcile entry gate.

    Defers with ``speed_mutex_active`` when speed compute holds the lock; acquires
    batch ownership when the lock is free.
    """
    if mutex.current_owner(shop_id) == "speed":
        return BatchComputeEntryResult(acquired=False, defer_reason=DEFER_REASON)
    if mutex.try_acquire(shop_id, "batch"):
        return BatchComputeEntryResult(acquired=True)
    return BatchComputeEntryResult(acquired=False)
