"""Redis token-bucket rate limiter for TikTok Shop API.

Maintains per-(app_id, shop_id, endpoint) counters in Redis with TTL-based
window expiry.  Uses atomic INCR to avoid TOCTOU races under concurrent access.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any

#: Per-shop 429 backoff (contract p101 §7: "Per-shop backoff with jitter").
#: The first throttle pauses the shop ~30 s, each further one inside the strike
#: window doubles it, capped at 15 min. Jitter adds up to 25 % so shops that were
#: throttled together do not wake together.
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 900
BACKOFF_JITTER_FRACTION = 0.25
#: A throttle older than this no longer counts towards the next delay.
BACKOFF_STRIKE_WINDOW_SECONDS = 3600


class RateLimiter:
    """Token-bucket rate limiter backed by Redis, with a per-shop 429 backoff.

    Every TikTok call a worker makes for a shop acquires through this class, so
    one backoff key per (app, shop) pauses poll, history and analytics together
    without any of them knowing about it: ``acquire`` answers False while the
    shop is backing off and ``time_until_reset`` reports the wait.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._redis = redis_client
        self._jitter = jitter

    def note_throttled(self, app_id: str, shop_id: str) -> int:
        """Record a TikTok 429 (100005) for this shop; return the pause in seconds.

        Exponential per consecutive throttle, jittered, capped. Callers that catch
        ``RateLimitError`` call this once per throttle; it never raises on a Redis
        error (a missed backoff must not turn a throttle into a failed cycle).
        """
        try:
            strikes_key = self._strikes_key(app_id, shop_id)
            strikes = int(self._redis.incr(strikes_key))
            self._redis.expire(strikes_key, BACKOFF_STRIKE_WINDOW_SECONDS)
            base = min(BACKOFF_BASE_SECONDS * 2 ** (strikes - 1), BACKOFF_MAX_SECONDS)
            delay = math.ceil(base * (1 + BACKOFF_JITTER_FRACTION * self._jitter()))
            self._redis.set(self._backoff_key(app_id, shop_id), 1, ex=delay)
            return delay
        except Exception:
            return 0

    def note_success(self, app_id: str, shop_id: str) -> None:
        """A call went through: the next throttle starts again at the base delay."""
        try:
            self._redis.delete(self._strikes_key(app_id, shop_id))
        except Exception:
            return

    def backoff_remaining(self, app_id: str, shop_id: str) -> int:
        """Seconds this shop must still wait after a 429; 0 when it is free."""
        ttl_raw = self._redis.ttl(self._backoff_key(app_id, shop_id))
        ttl = int(ttl_raw) if ttl_raw is not None else 0
        return max(ttl, 0)

    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Atomically consume one token.  Returns True if allowed, False if exhausted."""
        if self.backoff_remaining(app_id, shop_id) > 0:
            return False
        key = self._key(app_id, shop_id, endpoint)

        count = self._redis.incr(key)
        if count == 1:
            self._redis.expire(key, window_seconds)

        if count > max_requests:
            return False
        return True

    def is_exhausted(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
    ) -> bool:
        """Return True when the bucket is at or above max_requests (read-only)."""
        if self.backoff_remaining(app_id, shop_id) > 0:
            return True
        raw = self._redis.get(self._key(app_id, shop_id, endpoint))
        if raw is None:
            return False
        return int(raw) >= max_requests

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        """Seconds until the rate-limit window resets.  Returns 0 if no active window."""
        ttl_raw = self._redis.ttl(self._key(app_id, shop_id, endpoint))
        ttl = int(ttl_raw) if ttl_raw is not None else 0
        return max(ttl, 0, self.backoff_remaining(app_id, shop_id))

    @staticmethod
    def _backoff_key(app_id: str, shop_id: str) -> str:
        return f"ratelimit-backoff:{app_id}:{shop_id}"

    @staticmethod
    def _strikes_key(app_id: str, shop_id: str) -> str:
        return f"ratelimit-strikes:{app_id}:{shop_id}"

    @staticmethod
    def _key(app_id: str, shop_id: str, endpoint: str) -> str:
        return f"ratelimit:{app_id}:{shop_id}:{endpoint}"
