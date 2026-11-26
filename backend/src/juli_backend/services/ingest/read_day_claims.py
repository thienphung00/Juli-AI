"""C5e (batch-1123-a): one computer per hole day.

``GET /v1/connector/shopee/read-days`` hands every computer of a shop the same holes, so two
Connectors running at the same time both read them. Each (shop, dataset, day) handed out is now
claimed for the asking token in Redis (``SET NX EX``) for ``READ_DAY_LEASE``; a day another token
holds is left out of the answer. A day the holder does not read becomes free when the lease ends,
and a day that was read is no longer a hole at all.

The hole list is fetched once at the start of a daily run and read during that run, one page at
a time; the lease covers that run (up to about two hours with waits) plus an hour of margin.

Never blocks reading: without Redis (``REDIS_URL`` unset) or on a Redis error the answer is
returned unfiltered, as before, and the miss is logged (``read_day_claims_unavailable``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any, Protocol

logger = logging.getLogger(__name__)

READ_DAY_LEASE = timedelta(hours=3)
_KEY_PREFIX = "juli:ingest:readday:"


class ReadDayClaimStore(Protocol):
    async def claim(self, keys: list[str], holder: str, ttl_seconds: int) -> set[str] | None:
        """The keys ``holder`` now holds (newly claimed, or already its own); ``None`` when the
        store cannot answer."""


class InMemoryReadDayClaims:
    """For tests and single-process runs: no expiry clock beyond what the test sets."""

    def __init__(self) -> None:
        self.held: dict[str, str] = {}

    async def claim(self, keys: list[str], holder: str, ttl_seconds: int) -> set[str] | None:
        mine: set[str] = set()
        for key in keys:
            if self.held.setdefault(key, holder) == holder:
                mine.add(key)
        return mine


class RedisReadDayClaims:
    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def claim(self, keys: list[str], holder: str, ttl_seconds: int) -> set[str] | None:
        from redis.exceptions import RedisError

        if not keys:
            return set()
        try:
            pipe = self._redis.pipeline(transaction=False)
            for key in keys:
                pipe.set(key, holder, nx=True, ex=ttl_seconds)
            taken = await pipe.execute()
            rest = [k for k, ok in zip(keys, taken, strict=True) if not ok]
            owners: list[Any] = []
            if rest:
                pipe = self._redis.pipeline(transaction=False)
                for key in rest:
                    pipe.get(key)
                owners = await pipe.execute()
        except (RedisError, OSError) as exc:
            logger.warning("read_day_claims_unavailable", extra={"error_type": type(exc).__name__})
            return None
        mine = {k for k, ok in zip(keys, taken, strict=True) if ok}
        mine.update(k for k, owner in zip(rest, owners, strict=True) if owner == holder)
        return mine


class _DefaultStore:
    """Redis through the shared client (bound to the running loop, so fetched per call)."""

    async def claim(self, keys: list[str], holder: str, ttl_seconds: int) -> set[str] | None:
        from juli_backend.services.kpi_cache.redis_client import get_shared_redis_client

        client = get_shared_redis_client()
        if client is None:
            logger.info("read_day_claims_unavailable", extra={"error_type": "no_redis_url"})
            return None
        return await RedisReadDayClaims(client).claim(keys, holder, ttl_seconds)


_store: ReadDayClaimStore | None = None


def set_read_day_claim_store(store: ReadDayClaimStore | None) -> None:
    global _store
    _store = store


def get_read_day_claim_store() -> ReadDayClaimStore:
    global _store
    if _store is None:
        _store = _DefaultStore()
    return _store


def _key(shop_id: uuid.UUID, dataset: str, day: str) -> str:
    return f"{_KEY_PREFIX}{shop_id}:{dataset}:{day}"


async def claim_holes(
    answer: dict[str, Any], *, shop_id: uuid.UUID, token_id: uuid.UUID
) -> dict[str, Any]:
    """``answer`` (``read_days.read_days``) with only the hole days this token holds; unchanged
    when the claim store cannot answer."""
    datasets: dict[str, dict[str, list[str]]] = answer.get("datasets") or {}
    keys = [_key(shop_id, ds, day) for ds, entry in datasets.items() for day in entry["missing"]]
    mine = await get_read_day_claim_store().claim(
        keys, str(token_id), int(READ_DAY_LEASE.total_seconds())
    )
    if mine is None:
        return answer
    kept: dict[str, dict[str, list[str]]] = {}
    for ds, entry in datasets.items():
        days = [d for d in entry["missing"] if _key(shop_id, ds, d) in mine]
        if days:
            kept[ds] = {"missing": days}
    out = {**answer, "datasets": kept}
    refs = answer.get("unsettled_orders")
    if isinstance(refs, dict):
        # 7b: the refs of the days this token did not claim stay with the computer that did
        held = set(kept.get("order_income_unsettled", {}).get("missing", []))
        out["unsettled_orders"] = {day: r for day, r in refs.items() if day in held}
        if not out["unsettled_orders"]:
            del out["unsettled_orders"]
    return out
