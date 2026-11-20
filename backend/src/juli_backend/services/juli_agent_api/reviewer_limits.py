"""A partner reviewer's ask limits, across every pin (owner, 2026-11-20).

The shop's limits (30 / hour, 200 / day) are counted on ``agent_messages`` under the shop's RLS
scope, which cannot see a reviewer's asks on another pin. A reviewer's limits are therefore two
Redis fixed-window counters keyed by the reviewer's user id --
``juli:agent:reviewer:<user_id>:hour`` and ``…:day`` -- the INCR-then-EXPIRE pattern of
``services/agent/abuse_limits.py``. FAIL-CLOSED like that module: no Redis configured, or any
Redis error, refuses the ask (429) rather than letting it through unlimited.

Every attempt counts (a refused one too), as in ``abuse_limits``. A key found without a TTL
(``TTL`` -1: the EXPIRE after the first INCR was lost) gets its window set again on the next
ask, so a lost EXPIRE can never lock a reviewer out. ``abuse_limits`` has the same INCR/EXPIRE
gap; it is not changed here.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from juli_backend.services.agent.abuse_limits import AbuseLimitDecision
from juli_backend.services.juli_agent_api import config

logger = logging.getLogger(__name__)

KEY_PREFIX = "juli:agent:reviewer:"
HOUR_S = 3600
DAY_S = 86_400

_client: Any = None


def set_client(client: Any) -> None:
    """Tests bind a fake; ``None`` falls back to the process's shared client."""
    global _client
    _client = client


def _redis() -> Any:
    if _client is not None:
        return _client
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    from juli_backend.services.kpi_cache.redis_client import get_shared_redis_client

    return get_shared_redis_client(url)


def key(user_id: uuid.UUID, window: str) -> str:
    return f"{KEY_PREFIX}{user_id}:{window}"


async def try_acquire(user_id: uuid.UUID) -> AbuseLimitDecision:
    """One ask by this reviewer: allowed, or refused with the seconds until a window frees."""
    redis = _redis()
    windows = ((key(user_id, "hour"), HOUR_S, config.limit_per_hour()),
               (key(user_id, "day"), DAY_S, config.limit_per_day()))  # fmt: skip
    if redis is None:
        logger.warning("juli_reviewer_limit_store_unconfigured")
        return AbuseLimitDecision(allowed=False, retry_after_seconds=HOUR_S)
    try:
        for name, seconds, limit in windows:
            count = int(await redis.incr(name))
            ttl = seconds if count == 1 else await redis.ttl(name)
            if count == 1 or ttl == -1:
                # the first hit sets the window; a key left WITHOUT a TTL (EXPIRE lost, or the
                # process died between INCR and EXPIRE) is healed here, never a lockout
                await redis.expire(name, seconds)
                ttl = seconds
            if count > limit:
                wait = int(ttl) if isinstance(ttl, int) and ttl > 0 else seconds
                return AbuseLimitDecision(allowed=False, retry_after_seconds=wait)
    except Exception as exc:  # any store failure: closed, never unlimited
        logger.warning("juli_reviewer_limit_store_unavailable", extra={"error": type(exc).__name__})
        return AbuseLimitDecision(allowed=False, retry_after_seconds=HOUR_S)
    return AbuseLimitDecision(allowed=True, retry_after_seconds=0)


__all__ = ["DAY_S", "HOUR_S", "KEY_PREFIX", "key", "set_client", "try_acquire"]
