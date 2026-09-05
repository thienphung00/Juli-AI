"""Gold KPI envelope cache: the shared read-through plus a last-good fallback (#631).

The read-through itself lives in ``services.kpi_cache``; this module names the
key prefix, the repository and the envelope type, and adds the one behaviour
unique to the serving path: when Postgres has nothing (a compute failure left
no row) the Demo may serve the last envelope this process successfully cached,
rather than an empty dashboard. That fallback is read-only -- it never writes
to Postgres and never fabricates a value it did not previously serve.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import GoldKpiEnvelope
from juli_backend.repositories import GoldKpiEnvelopesRepo
from juli_backend.services.kpi_cache import (
    EnvelopeCache,
    EnvelopeCodec,
    close_shared_redis_client,
    get_shared_redis_client,
    reset_shared_redis_client_for_tests,
)
from juli_backend.services.kpi_cache.envelope_cache import computed_at_from_payload

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "gold:kpi_envelope:"

# Payloads this process has served successfully, by shop. Consulted only when
# both Redis and Postgres come back empty (see module docstring).
_last_good_payloads: dict[uuid.UUID, dict[str, Any]] = {}


def _envelope_from_payload(shop_id: uuid.UUID, payload: dict[str, Any]) -> GoldKpiEnvelope:
    return GoldKpiEnvelope(
        shop_id=shop_id,
        envelope_version=int(payload.get("envelope_version", 1)),
        payload=payload,
        computed_at=computed_at_from_payload(payload),
    )


async def _load_from_postgres(session: AsyncSession, shop_id: uuid.UUID) -> GoldKpiEnvelope | None:
    return await GoldKpiEnvelopesRepo(session).get(shop_id)


_cache: EnvelopeCache[GoldKpiEnvelope] = EnvelopeCache(
    name="gold_kpi",
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


async def refresh_gold_kpi_envelope_cache(
    shop_id: uuid.UUID,
    envelope: GoldKpiEnvelope,
    *,
    redis_client: Any | None = None,
) -> None:
    """Overwrite Redis after a successful Postgres upsert; remember the payload as last-good."""
    if await _cache.refresh(shop_id, envelope, redis_client=redis_client):
        _last_good_payloads[shop_id] = envelope.payload


async def get_gold_kpi_envelope(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> GoldKpiEnvelope | None:
    """Read-through: Redis first, Postgres on miss or outage."""
    return await _cache.get(session, shop_id, redis_client=redis_client)


async def get_gold_kpi_envelope_with_last_good_fallback(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> GoldKpiEnvelope | None:
    """Read-through, then the last payload this process served if both stores are empty."""
    payload = await _cache.read_payload(shop_id, redis_client)
    if payload is not None:
        _last_good_payloads[shop_id] = payload
        return _envelope_from_payload(shop_id, payload)

    envelope = await _load_from_postgres(session, shop_id)
    if envelope is not None:
        _last_good_payloads[shop_id] = envelope.payload
        await _cache.refresh(shop_id, envelope, redis_client=redis_client)
        return envelope

    last_good = _last_good_payloads.get(shop_id)
    if last_good is None:
        return None
    logger.info("gold KPI cache using last-good fallback for %s", shop_id)
    return _envelope_from_payload(shop_id, last_good)


__all__ = [
    "CACHE_KEY_PREFIX",
    "close_shared_redis_client",
    "create_redis_client",
    "envelope_cache_key",
    "get_gold_kpi_envelope",
    "get_gold_kpi_envelope_with_last_good_fallback",
    "get_shared_redis_client",
    "refresh_gold_kpi_envelope_cache",
    "reset_shared_redis_client_for_tests",
]
