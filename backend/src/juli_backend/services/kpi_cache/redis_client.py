"""The one shared ``redis.asyncio`` client (ADR-041).

Every caller that wants Redis -- both KPI caches, the action-card refresh
cooldown gate, the agent abuse-limit gate -- goes through
:func:`get_shared_redis_client`, so a process holds one connection pool, not
one per feature.

Two constraints shape the lifecycle, and both are easy to lose in a rewrite:

* **One client per event loop (#871).** An async client's connections bind to
  the loop that first used them. The API runs one loop for the whole process,
  so one client is right there. Celery worker tasks each enter through
  ``asyncio.run()``; reusing the previous task's client makes every Redis call
  after the child's first run fail cross-loop, and because the gold cache key
  has no TTL the Demo would then serve a stale envelope indefinitely. The
  cache key is therefore ``(url, running loop)``, not ``url`` alone.
* **Explicit socket timeouts (#927).** ``redis.asyncio.from_url`` sets none by
  default, so an unreachable or hung Redis would block a call for the OS-level
  TCP timeout instead of raising ``RedisError`` promptly into the fail-open
  (caches) or fail-closed (gates) path.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis_asyncio

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

SOCKET_CONNECT_TIMEOUT_SECONDS = 2.0
SOCKET_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class _SharedClient:
    client: Redis
    url: str
    loop: asyncio.AbstractEventLoop | None


_shared: _SharedClient | None = None


def resolve_redis_url(redis_url: str | None = None) -> str:
    """``redis_url`` if given, else ``REDIS_URL``; empty string means "no Redis"."""
    raw = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
    return (raw or "").strip()


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_shared_redis_client(redis_url: str | None = None) -> Redis | None:
    """Return the shared client for ``(url, current loop)``, or ``None`` without a URL."""
    global _shared

    url = resolve_redis_url(redis_url)
    if not url:
        return None
    loop = _running_loop()
    if _shared is not None and _shared.url == url and _shared.loop is loop:
        return _shared.client

    # A superseded client is dropped without aclose(): its loop is closed or
    # closing (asyncio.run tears it down), so its connections are already
    # unusable and cannot be awaited shut from here.
    client = redis_asyncio.from_url(
        url,
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=SOCKET_CONNECT_TIMEOUT_SECONDS,
    )
    _shared = _SharedClient(client=client, url=url, loop=loop)
    return client


async def close_shared_redis_client() -> None:
    """Close and forget the shared client (API lifespan shutdown).

    Best-effort: if the connection's loop is already gone the connection is
    already effectively closed, so a ``RuntimeError`` here is logged, not
    raised -- the same fail-open stance every Redis read takes.
    """
    global _shared

    shared = _shared
    _shared = None
    if shared is None:
        return
    try:
        await _aclose(shared.client)
    except RuntimeError as exc:
        logger.warning("shared redis client close failed (best-effort): %s", exc)


async def _aclose(client: Any) -> None:
    aclose = getattr(client, "aclose", None)
    if aclose is not None:
        await aclose()
        return
    close = getattr(client, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result


def reset_shared_redis_client_for_tests() -> None:
    """Forget the shared client without closing it. Unit tests only."""
    global _shared
    _shared = None


__all__ = [
    "SOCKET_CONNECT_TIMEOUT_SECONDS",
    "SOCKET_TIMEOUT_SECONDS",
    "close_shared_redis_client",
    "get_shared_redis_client",
    "reset_shared_redis_client_for_tests",
    "resolve_redis_url",
]
