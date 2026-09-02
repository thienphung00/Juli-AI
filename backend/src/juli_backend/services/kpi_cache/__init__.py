"""Shared machinery for the Redis read-through KPI envelope caches.

Two envelope caches exist -- ``gold_kpi_cache`` (serving, ADR-038/#631) and
``analytics_kpi_cache`` (Phase 2.10) -- and for a long time each carried its
own copy of the Redis client lifecycle and the read-through loop. The copies
drifted: gold gained the per-event-loop client (#871) that analytics lacked,
analytics gained the socket timeouts (#927) that gold lacked. Each fixed a bug
the other still had.

This package is the single copy. ``redis_client`` owns the one shared
``redis.asyncio`` client (both fixes, once); ``envelope_cache`` owns the
fail-open read-through. The two public packages are thin adapters that name
their key prefix, their repository and their envelope type -- nothing else.
"""

from __future__ import annotations

from juli_backend.services.kpi_cache.envelope_cache import EnvelopeCache, EnvelopeCodec
from juli_backend.services.kpi_cache.redis_client import (
    close_shared_redis_client,
    get_shared_redis_client,
    reset_shared_redis_client_for_tests,
    resolve_redis_url,
)

__all__ = [
    "EnvelopeCache",
    "EnvelopeCodec",
    "close_shared_redis_client",
    "get_shared_redis_client",
    "reset_shared_redis_client_for_tests",
    "resolve_redis_url",
]
