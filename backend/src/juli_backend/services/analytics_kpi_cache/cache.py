"""Redis read-through cache for Analytics KPI envelopes."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsKpiEnvelope
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo

logger = logging.getLogger(__name__)

ANALYTICS_KIND = "analytics"
CACHE_KEY_PREFIX = "analytics:kpi_envelope:"


def envelope_cache_key(shop_id: uuid.UUID) -> str:
    return f"{CACHE_KEY_PREFIX}{shop_id}"


def create_redis_client(redis_url: str | None = None) -> Any | None:
    """Build async Redis client from REDIS_URL when configured."""
    raw = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
    url = (raw or "").strip()
    if not url:
        return None
    import redis.asyncio as redis

    return redis.from_url(url, decode_responses=True)


def _envelope_from_cached_payload(
    shop_id: uuid.UUID,
    payload: dict[str, Any],
) -> AnalyticsKpiEnvelope:
    raw_computed_at = payload.get("computed_at")
    computed_at = (
        datetime.fromisoformat(raw_computed_at)
        if isinstance(raw_computed_at, str)
        else datetime.now(tz=UTC)
    )
    return AnalyticsKpiEnvelope(
        id=uuid.uuid4(),
        shop_id=shop_id,
        kind=ANALYTICS_KIND,
        envelope_version=int(payload.get("envelope_version", 1)),
        payload=payload,
        computed_at=computed_at,
    )


def _serialize_envelope_payload(envelope: AnalyticsKpiEnvelope) -> str:
    return json.dumps(envelope.payload, separators=(",", ":"), sort_keys=True)


async def refresh_analytics_kpi_envelope_cache(
    shop_id: uuid.UUID,
    envelope: AnalyticsKpiEnvelope,
    *,
    redis_client: Any | None = None,
) -> None:
    """Overwrite Redis after successful Postgres upsert. Fail-open on Redis errors."""
    if redis_client is None:
        return
    key = envelope_cache_key(shop_id)
    try:
        await redis_client.set(key, _serialize_envelope_payload(envelope))
    except RedisError as exc:
        logger.warning("analytics KPI cache refresh failed for %s: %s", shop_id, exc)


async def get_analytics_kpi_envelope(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> AnalyticsKpiEnvelope | None:
    """Read-through: Redis first, Postgres SoT on miss or Redis outage."""
    if redis_client is not None:
        key = envelope_cache_key(shop_id)
        try:
            cached = await redis_client.get(key)
            if cached is not None:
                payload = json.loads(cached)
                return _envelope_from_cached_payload(shop_id, payload)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("analytics KPI cache read failed for %s: %s", shop_id, exc)

    repo = AnalyticsKpiEnvelopesRepo(session)
    envelope = await repo.get_by_kind(shop_id, ANALYTICS_KIND)
    if envelope is None:
        return None

    await refresh_analytics_kpi_envelope_cache(
        shop_id,
        envelope,
        redis_client=redis_client,
    )
    return envelope
