"""Redis read-through cache for Gold KPI envelopes."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import GoldKpiEnvelope
from juli_backend.repositories.repos import GoldKpiEnvelopesRepo

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "gold:kpi_envelope:"

_shared_client: Any | None = None
_shared_client_url: str | None = None
_last_good_cache: dict[uuid.UUID, dict[str, Any]] = {}


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
        logger.warning("gold KPI cache client close failed (best-effort): %s", exc)


def reset_shared_redis_client_for_tests() -> None:
    """Drop the singleton without closing (unit tests only)."""
    global _shared_client, _shared_client_url
    _shared_client = None
    _shared_client_url = None


def _envelope_from_cached_payload(
    shop_id: uuid.UUID,
    payload: dict[str, Any],
) -> GoldKpiEnvelope:
    raw_computed_at = payload.get("computed_at")
    computed_at = (
        datetime.fromisoformat(raw_computed_at)
        if isinstance(raw_computed_at, str)
        else datetime.now(tz=UTC)
    )
    return GoldKpiEnvelope(
        shop_id=shop_id,
        envelope_version=int(payload.get("envelope_version", 1)),
        payload=payload,
        computed_at=computed_at,
    )


def _serialize_envelope_payload(envelope: GoldKpiEnvelope) -> str:
    return json.dumps(envelope.payload, separators=(",", ":"), sort_keys=True)


async def refresh_gold_kpi_envelope_cache(
    shop_id: uuid.UUID,
    envelope: GoldKpiEnvelope,
    *,
    redis_client: Any | None = None,
) -> None:
    """Overwrite Redis after successful Postgres upsert. Fail-open on Redis errors."""
    global _last_good_cache

    if redis_client is None:
        return

    key = envelope_cache_key(shop_id)
    try:
        await redis_client.set(key, _serialize_envelope_payload(envelope))
        # Update last-good cache on successful Redis write
        _last_good_cache[shop_id] = envelope.payload
    except RedisError as exc:
        logger.warning("gold KPI cache refresh failed for %s: %s", shop_id, exc)


async def get_gold_kpi_envelope(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> GoldKpiEnvelope | None:
    """Read-through: Redis first, Postgres SoT on miss or Redis outage."""
    if redis_client is not None:
        key = envelope_cache_key(shop_id)
        try:
            cached = await redis_client.get(key)
            if cached is not None:
                logger.info(
                    "gold_kpi_cache_hit",
                    extra={"shop_id": str(shop_id)},
                )
                payload = json.loads(cached)
                return _envelope_from_cached_payload(shop_id, payload)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("gold KPI cache read failed for %s: %s", shop_id, exc)

    logger.info(
        "gold_kpi_cache_miss",
        extra={"shop_id": str(shop_id)},
    )
    repo = GoldKpiEnvelopesRepo(session)
    envelope = await repo.get(shop_id)
    if envelope is None:
        return None

    await refresh_gold_kpi_envelope_cache(
        shop_id,
        envelope,
        redis_client=redis_client,
    )
    return envelope


async def get_gold_kpi_envelope_with_last_good_fallback(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> GoldKpiEnvelope | None:
    """Read-through with last-good fallback for compute failures.

    Never returns stale/fabricated values. On compute failure in Demo, returns the
    last-good cached envelope if available, allowing graceful degradation. Postgres
    (gold.kpi_envelopes) always remains SoT.
    """
    global _last_good_cache

    if redis_client is not None:
        key = envelope_cache_key(shop_id)
        try:
            cached = await redis_client.get(key)
            if cached is not None:
                payload = json.loads(cached)
                _last_good_cache[shop_id] = payload
                return _envelope_from_cached_payload(shop_id, payload)
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("gold KPI cache read failed for %s (last-good): %s", shop_id, exc)

    # Try to load from Postgres
    repo = GoldKpiEnvelopesRepo(session)
    envelope = await repo.get(shop_id)
    if envelope is not None:
        _last_good_cache[shop_id] = envelope.payload
        await refresh_gold_kpi_envelope_cache(
            shop_id,
            envelope,
            redis_client=redis_client,
        )
        return envelope

    # Fall back to last-good cached value if Postgres miss
    if shop_id in _last_good_cache:
        payload = _last_good_cache[shop_id]
        logger.info("gold KPI cache using last-good fallback for %s", shop_id)
        return _envelope_from_cached_payload(shop_id, payload)

    return None
