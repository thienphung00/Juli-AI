"""Redis token-bucket rate limiter for TikTok Shop API.

Maintains per-(app_id, shop_id, endpoint) counters in Redis with TTL-based
window expiry.  Uses atomic INCR to avoid TOCTOU races under concurrent access.
"""

from __future__ import annotations

from typing import Any


class RateLimiter:
    """Token-bucket rate limiter backed by Redis."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        """Atomically consume one token.  Returns True if allowed, False if exhausted."""
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
        raw = self._redis.get(self._key(app_id, shop_id, endpoint))
        if raw is None:
            return False
        return int(raw) >= max_requests

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        """Seconds until the rate-limit window resets.  Returns 0 if no active window."""
        ttl_raw = self._redis.ttl(self._key(app_id, shop_id, endpoint))
        ttl = int(ttl_raw) if ttl_raw is not None else 0
        return max(ttl, 0)

    @staticmethod
    def _key(app_id: str, shop_id: str, endpoint: str) -> str:
        return f"ratelimit:{app_id}:{shop_id}:{endpoint}"
