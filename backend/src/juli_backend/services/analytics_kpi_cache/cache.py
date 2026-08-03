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

_shared_client: Any | None = None
_shared_client_url: str | None = None


def envelope_cache_key(shop_id: uuid.UUID) -> str:
    return f"{CACHE_KEY_PREFIX}{shop_id}"


def _resolve_redis_url(redis_url: str | None = None) -> str:
    raw = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
    return (raw or "").strip()


def get_shared_redis_client(redis_url: str | None = None) -> Any | None:
    """Return process-lifetime async Redis client from REDIS_URL (or None)."""
    global _shared_client, _shared_client_url

    url = _resolve_redis_url(redis_url)
    if not url:
        return None
    if _shared_client is not None and _shared_client_url == url:
        return _shared_client

    import redis.asyncio as redis

    # URL changed without close — drop the old handle; caller should prefer
    # close_shared_redis_client() on shutdown. We cannot await aclose here.
    _shared_client = redis.from_url(url, decode_responses=True)
    _shared_client_url = url
    return _shared_client


def create_redis_client(redis_url: str | None = None) -> Any | None:
    """Return the shared async Redis client (compat alias for get_shared_redis_client)."""
    return get_shared_redis_client(redis_url)


async def close_shared_redis_client() -> None:
    """Close and clear the process-lifetime async Redis client.

    Best-effort: if the underlying connection's event loop is already
    closed (e.g. a test-teardown ordering edge case), the connection is
    already effectively gone — log and move on rather than raise, matching
    this module's fail-open philosophy for every other Redis operation.
    """
    global _shared_client, _shared_client_url

    client = _shared_client
    _shared_client = None
    _shared_client_url = None
    if client is None:
        return
    try:
        aclose = getattr(client, "aclose", None)
        if aclose is not None:
            await aclose()
            return
        close = getattr(client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
    except RuntimeError as exc:
        logger.warning("analytics KPI cache client close failed (best-effort): %s", exc)


def reset_shared_redis_client_for_tests() -> None:
    """Drop the singleton without closing (unit tests only)."""
    global _shared_client, _shared_client_url
    _shared_client = None
    _shared_client_url = None


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
