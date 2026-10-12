"""Fixed-window rate limits for the ingest routes (per shop; per client for pairing).

The same INCR + EXPIRE shape as ``services.agent.abuse_limits``: Redis when
``REDIS_URL`` is set (the API's shared client), failing CLOSED on a Redis error;
an in-process window otherwise (single-process dev / tests).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

_KEY_PREFIX = "juli:ingest:rate:"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def shop_limit() -> tuple[int, int]:
    """(requests, window seconds) per shop across the ingest routes."""
    return _int_env("INGEST_RATE_LIMIT_PER_SHOP", 120), _int_env("INGEST_RATE_WINDOW_SECONDS", 600)


def pair_limit() -> tuple[int, int]:
    """(attempts, window seconds) per client address on ``/v1/ingest/pair``."""
    return _int_env("INGEST_PAIR_LIMIT_PER_CLIENT", 10), _int_env("INGEST_PAIR_WINDOW_SECONDS", 600)


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int = 0


class IngestRateGate(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision: ...


class InMemoryRateGate:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        now = time.monotonic()
        started, count = self._windows.get(key, (now, 0))
        if now - started >= window_seconds:
            started, count = now, 0
        count += 1
        self._windows[key] = (started, count)
        if count > limit:
            return RateDecision(False, max(1, int(window_seconds - (now - started))))
        return RateDecision(True)


class RedisRateGate:
    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        from redis.exceptions import RedisError

        full = f"{_KEY_PREFIX}{key}"
        try:
            count = int(await self._redis.incr(full))
            if count == 1:
                await self._redis.expire(full, window_seconds)
            if count <= limit:
                return RateDecision(True)
            ttl = await self._redis.ttl(full)
        except RedisError:
            return RateDecision(False, window_seconds)
        return RateDecision(False, int(ttl) if isinstance(ttl, int) and ttl > 0 else window_seconds)


class _DefaultGate:
    """Redis through the shared client (re-fetched per call: it is bound to the
    running event loop), or the in-process window when ``REDIS_URL`` is unset."""

    def __init__(self) -> None:
        self._memory = InMemoryRateGate()

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        from juli_backend.services.analytics_kpi_cache import get_shared_redis_client

        client = get_shared_redis_client()
        if client is None:
            return await self._memory.hit(key, limit, window_seconds)
        return await RedisRateGate(client).hit(key, limit, window_seconds)


_gate: IngestRateGate | None = None


def set_ingest_rate_gate(gate: IngestRateGate | None) -> None:
    global _gate
    _gate = gate


def get_ingest_rate_gate() -> IngestRateGate:
    global _gate
    if _gate is None:
        _gate = _DefaultGate()
    return _gate
