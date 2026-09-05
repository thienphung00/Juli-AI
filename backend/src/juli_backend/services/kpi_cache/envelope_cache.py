"""Fail-open Redis read-through for a per-shop KPI envelope.

Postgres is always the system of record. Redis only makes the read cheaper:
a hit is served from the cached payload, a miss (or any Redis failure) falls
through to the repository and best-effort fills the cache on the way back.
No path returns empty while Postgres has a row, and no path raises because
Redis is down.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

EnvelopeT = TypeVar("EnvelopeT")


def computed_at_from_payload(payload: Mapping[str, Any]) -> datetime:
    """The ``computed_at`` a cached payload carries, or now if it carries none."""
    raw = payload.get("computed_at")
    return datetime.fromisoformat(raw) if isinstance(raw, str) else datetime.now(tz=UTC)


@dataclass(frozen=True)
class EnvelopeCodec(Generic[EnvelopeT]):
    """How one envelope type crosses the Redis boundary.

    ``key_prefix`` namespaces the key (``"gold:kpi_envelope:"``); ``payload_of``
    picks the JSON-serialisable dict to store; ``from_payload`` rebuilds an
    envelope object from a cached dict for a given shop.
    """

    key_prefix: str
    payload_of: Callable[[EnvelopeT], Mapping[str, Any]]
    from_payload: Callable[[uuid.UUID, dict[str, Any]], EnvelopeT]

    def key(self, shop_id: uuid.UUID) -> str:
        return f"{self.key_prefix}{shop_id}"

    def encode(self, envelope: EnvelopeT) -> str:
        return json.dumps(self.payload_of(envelope), separators=(",", ":"), sort_keys=True)


class EnvelopeCache(Generic[EnvelopeT]):
    """Read-through cache over ``load`` (the repository read) using ``codec``.

    ``name`` prefixes the structured log events (``<name>_cache_hit`` /
    ``<name>_cache_miss``) so dashboards can tell the two caches apart.
    """

    def __init__(
        self,
        *,
        name: str,
        codec: EnvelopeCodec[EnvelopeT],
        load: Callable[[AsyncSession, uuid.UUID], Awaitable[EnvelopeT | None]],
    ) -> None:
        self._name = name
        self._codec = codec
        self._load = load

    def key(self, shop_id: uuid.UUID) -> str:
        return self._codec.key(shop_id)

    async def read_payload(
        self, shop_id: uuid.UUID, redis_client: Any | None
    ) -> dict[str, Any] | None:
        """The cached payload, or ``None`` on miss, no client, outage, or corrupt JSON."""
        if redis_client is None:
            return None
        try:
            cached = await redis_client.get(self.key(shop_id))
            if cached is None:
                return None
            payload = json.loads(cached)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("%s cache read failed for %s: %s", self._name, shop_id, exc)
            return None
        logger.info("%s_cache_hit", self._name, extra={"shop_id": str(shop_id)})
        return payload

    async def refresh(
        self, shop_id: uuid.UUID, envelope: EnvelopeT, *, redis_client: Any | None
    ) -> bool:
        """Overwrite the cached payload after a Postgres write. Returns whether it stuck."""
        if redis_client is None:
            return False
        try:
            await redis_client.set(self.key(shop_id), self._codec.encode(envelope))
        except RedisError as exc:
            logger.warning("%s cache refresh failed for %s: %s", self._name, shop_id, exc)
            return False
        return True

    async def get(
        self, session: AsyncSession, shop_id: uuid.UUID, *, redis_client: Any | None
    ) -> EnvelopeT | None:
        """Redis first; on miss or outage load from Postgres and fill the cache."""
        payload = await self.read_payload(shop_id, redis_client)
        if payload is not None:
            return self._codec.from_payload(shop_id, payload)

        logger.info("%s_cache_miss", self._name, extra={"shop_id": str(shop_id)})
        envelope = await self._load(session, shop_id)
        if envelope is None:
            return None
        await self.refresh(shop_id, envelope, redis_client=redis_client)
        return envelope


__all__ = ["EnvelopeCache", "EnvelopeCodec", "computed_at_from_payload"]
