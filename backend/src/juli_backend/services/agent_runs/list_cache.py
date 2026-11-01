"""A few-second Redis cache of the polled runs list (P82, Supabase egress).

``GET /v1/demo/runs`` is polled by every open Quyết định tab; two tabs, a reload and the
in-page refreshes all read the same list within seconds. A hit is served from Redis, so
the runs statements never reach Postgres.

Scope: one Redis hash per ``X-Shop-Id`` header value (``juli:agent_runs:list:<header>``) so a
write can drop every cached list of that shop at once; inside it one field per
(resolved shop, requesting user, reviewer viewer, limit) -- a list is never served to
another user, another shop or another viewer window. The value carries the moment it was
cached and is ignored once older than :func:`ttl_seconds`, whatever the hash TTL says.

Invalidation: any successful non-GET request carrying the header (approve, cancel, a
confirmation, a revert ...) drops the shop's hash (``api/middleware``). A status change
made by a worker (runner, reaper) is seen when the entry expires -- a few seconds.

Fail-open like ``services/kpi_cache``: no Redis, an outage or a corrupt value is a miss,
never an error. Postgres stays the source of truth. ``RUNS_LIST_CACHE_SECONDS=0``
disables it (the test suites do, so a real CI Redis never serves one test's list to
another).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol, TypeVar

from redis.exceptions import RedisError

from juli_backend.services.agent_runs.listing import RunViewer

logger = logging.getLogger(__name__)

TTL_ENV = "RUNS_LIST_CACHE_SECONDS"
DEFAULT_TTL_SECONDS = 4.0
KEY_PREFIX = "juli:agent_runs:list:"


def ttl_seconds() -> float:
    raw = os.getenv(TTL_ENV, "").strip()
    if not raw:
        return DEFAULT_TTL_SECONDS
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _client() -> Any | None:
    from juli_backend.services.kpi_cache import get_shared_redis_client

    return get_shared_redis_client()


def shop_key(shop_header: str) -> str:
    return f"{KEY_PREFIX}{shop_header.strip()}"


def entry_field(
    shop_id: uuid.UUID, user_id: uuid.UUID, viewer: RunViewer | None, limit: int
) -> str:
    """The hash field of one list: the resolved shop, the requesting user, the reviewer's
    window (or ``-`` for everyone else) and the limit."""
    window = "-"
    if viewer is not None:
        since = viewer.since.isoformat() if viewer.since is not None else "-"
        window = f"{viewer.user_id}@{since}"
    return f"{shop_id}|{user_id}|{window}|{limit}"


async def read(shop_header: str, field: str, *, redis_client: Any | None = None) -> Any | None:
    """The cached response body, or ``None`` (miss, stale, disabled, no Redis, outage)."""
    ttl = ttl_seconds()
    client = redis_client if redis_client is not None else (_client() if ttl > 0 else None)
    if ttl <= 0 or client is None or not shop_header:
        return None
    try:
        raw = await client.hget(shop_key(shop_header), field)
        if raw is None:
            return None
        entry = json.loads(raw)
    except (RedisError, ValueError, TypeError) as exc:
        logger.warning("runs_list_cache_read_failed: %s", exc)
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("at"), int | float):
        return None
    if time.time() - entry["at"] >= ttl:
        return None
    return entry.get("body")


async def write(
    shop_header: str, field: str, body: Any, *, redis_client: Any | None = None
) -> None:
    ttl = ttl_seconds()
    client = redis_client if redis_client is not None else (_client() if ttl > 0 else None)
    if ttl <= 0 or client is None or not shop_header:
        return
    key = shop_key(shop_header)
    try:
        await client.hset(key, field, json.dumps({"at": time.time(), "body": body}))
        await client.expire(key, max(int(ttl) + 1, 1))
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning("runs_list_cache_write_failed: %s", exc)


class ListResponse(Protocol):
    """The route's response model: a ``data`` list, dumped to JSON for the cache."""

    @property
    def data(self) -> Sequence[object]: ...

    def model_dump(self, *, mode: str) -> dict[str, Any]: ...


ResponseT = TypeVar("ResponseT", bound=ListResponse)


def cache_key(
    headers: Mapping[str, str],
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    viewer: RunViewer | None,
    limit: int,
) -> tuple[str, str]:
    """(shop header, hash field) of one request's list."""
    return headers.get("x-shop-id", ""), entry_field(shop_id, user_id, viewer, limit)


async def read_through(
    key: tuple[str, str],
    load: Callable[[], Awaitable[ResponseT]],
    *,
    redis_client: Any | None = None,
) -> ResponseT | dict[str, Any]:
    """The cached body (a JSON dict the route's ``response_model`` validates), else
    ``load()``. An empty list is never cached: it may be a degraded read (#1310), and an
    empty list costs Postgres nothing worth saving."""
    shop_header, field = key
    cached = await read(shop_header, field, redis_client=redis_client)
    if isinstance(cached, dict):
        return cached
    response = await load()
    if response.data:
        body = response.model_dump(mode="json")
        await write(shop_header, field, body, redis_client=redis_client)
    return response


async def forget(shop_header: str, *, redis_client: Any | None = None) -> None:
    """Drop every cached runs list of the shop named by this header (best-effort)."""
    client = (
        redis_client if redis_client is not None else (_client() if ttl_seconds() > 0 else None)
    )
    if client is None or not shop_header:
        return
    try:
        await client.delete(shop_key(shop_header))
    except RedisError as exc:
        logger.warning("runs_list_cache_forget_failed: %s", exc)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "TTL_ENV",
    "ListResponse",
    "cache_key",
    "entry_field",
    "forget",
    "read",
    "read_through",
    "shop_key",
    "ttl_seconds",
    "write",
]
