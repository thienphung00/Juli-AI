"""Analytics KPI envelope cache (Phase 2.10, #529).

The read-through lives in ``services.kpi_cache``; this module names the key
prefix, the repository and the envelope type. After the #606 gold cutover the
repository it reads is itself an adapter over ``gold.kpi_envelopes``, so this
cache and ``gold_kpi_cache`` serve the same row under two key prefixes.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsKpiEnvelope
from juli_backend.repositories import AnalyticsKpiEnvelopesRepo
from juli_backend.services.kpi_cache import (
    EnvelopeCache,
    EnvelopeCodec,
    close_shared_redis_client,
    get_shared_redis_client,
    reset_shared_redis_client_for_tests,
)
from juli_backend.services.kpi_cache.envelope_cache import computed_at_from_payload

ANALYTICS_KIND = "analytics"
CACHE_KEY_PREFIX = "analytics:kpi_envelope:"


def _envelope_from_payload(shop_id: uuid.UUID, payload: dict[str, Any]) -> AnalyticsKpiEnvelope:
    return AnalyticsKpiEnvelope(
        id=uuid.uuid4(),
        shop_id=shop_id,
        kind=ANALYTICS_KIND,
        envelope_version=int(payload.get("envelope_version", 1)),
        payload=payload,
        computed_at=computed_at_from_payload(payload),
    )


async def _load_from_postgres(
    session: AsyncSession, shop_id: uuid.UUID
) -> AnalyticsKpiEnvelope | None:
    return await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop_id, ANALYTICS_KIND)


_cache: EnvelopeCache[AnalyticsKpiEnvelope] = EnvelopeCache(
    name="analytics_kpi",
    codec=EnvelopeCodec(
        key_prefix=CACHE_KEY_PREFIX,
        payload_of=lambda envelope: envelope.payload,
        from_payload=_envelope_from_payload,
    ),
    load=_load_from_postgres,
)


def envelope_cache_key(shop_id: uuid.UUID) -> str:
    return _cache.key(shop_id)


def create_redis_client(redis_url: str | None = None) -> Any | None:
    """Compat alias for :func:`get_shared_redis_client`."""
    return get_shared_redis_client(redis_url)


async def refresh_analytics_kpi_envelope_cache(
    shop_id: uuid.UUID,
    envelope: AnalyticsKpiEnvelope,
    *,
    redis_client: Any | None = None,
) -> None:
    """Overwrite Redis after a successful Postgres upsert. Fail-open on Redis errors."""
    await _cache.refresh(shop_id, envelope, redis_client=redis_client)


async def get_analytics_kpi_envelope(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> AnalyticsKpiEnvelope | None:
    """Read-through: Redis first, Postgres on miss or outage."""
    return await _cache.get(session, shop_id, redis_client=redis_client)


__all__ = [
    "ANALYTICS_KIND",
    "CACHE_KEY_PREFIX",
    "close_shared_redis_client",
    "create_redis_client",
    "envelope_cache_key",
    "get_analytics_kpi_envelope",
    "get_shared_redis_client",
    "refresh_analytics_kpi_envelope_cache",
    "reset_shared_redis_client_for_tests",
]
