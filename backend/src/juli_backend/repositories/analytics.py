"""Creators, livestreams, performance intervals and the serving KPI envelope.

``gold.kpi_envelopes`` is the serving source of truth after the #606 cutover:
one row per shop, flexible ``payload.kpis`` JSON. ``AnalyticsKpiEnvelopesRepo``
is a compatibility adapter that presents that row in the legacy
``analytics_kpi_envelopes`` shape for the Demo and its Redis cache; it neither
reads nor writes the legacy table.

One-writer rule: both envelope repos' ``upsert`` may only be called from
``services.gold_kpi_envelope_serving`` and ``services.analytics_kpi_precompute``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsKpiEnvelope,
    AnalyticsPerformanceInterval,
    Creator,
    GoldKpiEnvelope,
    Livestream,
)
from juli_backend.repositories._base import SessionRepo, ShopScopedRepo

ANALYTICS_KIND = "analytics"


class CreatorsRepo(ShopScopedRepo[Creator]):
    _model = Creator
    _lookup_attrs = ("tiktok_creator_id",)


class LivestreamsRepo(ShopScopedRepo[Livestream]):
    _model = Livestream
    _lookup_attrs = ("tiktok_livestream_id",)


class AnalyticsPerformanceRepo(ShopScopedRepo[AnalyticsPerformanceInterval]):
    _model = AnalyticsPerformanceInterval
    _lookup_attrs = ("snapshot_key",)


class GoldKpiEnvelopesRepo(SessionRepo):
    """``gold.kpi_envelopes`` -- keyed by ``shop_id``, so there is no ``id`` to page on."""

    async def get(self, shop_id: uuid.UUID) -> GoldKpiEnvelope | None:
        envelope = await self._session.get(GoldKpiEnvelope, shop_id)
        if envelope is not None:
            # Another session (the precompute worker) may have written since this
            # identity-map entry was loaded; refresh so the caller sees the row.
            await self._session.refresh(envelope)
        return envelope

    async def upsert(
        self,
        *,
        shop_id: uuid.UUID,
        envelope_version: int,
        payload: dict[str, Any],
        computed_at: datetime,
    ) -> GoldKpiEnvelope:
        envelope = await self.get(shop_id)
        if envelope is None:
            envelope = GoldKpiEnvelope(
                shop_id=shop_id,
                envelope_version=envelope_version,
                payload=payload,
                computed_at=computed_at,
            )
            self._session.add(envelope)
        else:
            envelope.envelope_version = envelope_version
            envelope.payload = payload
            envelope.computed_at = computed_at
        await self._session.flush()
        await self._session.refresh(envelope)
        return envelope


def _gold_to_legacy_envelope(gold: GoldKpiEnvelope) -> AnalyticsKpiEnvelope:
    """Present a gold row in the legacy shape. Deterministic id so callers can compare."""
    return AnalyticsKpiEnvelope(
        id=uuid.uuid5(uuid.NAMESPACE_OID, f"{gold.shop_id}:{ANALYTICS_KIND}"),
        shop_id=gold.shop_id,
        kind=ANALYTICS_KIND,
        envelope_version=gold.envelope_version,
        payload=gold.payload,
        computed_at=gold.computed_at,
        created_at=gold.created_at,
        updated_at=gold.updated_at,
    )


class AnalyticsKpiEnvelopesRepo(SessionRepo):
    """Legacy-shaped view over :class:`GoldKpiEnvelopesRepo` (#606 cutover).

    Only ``kind == "analytics"`` exists after the cutover; other kinds read as
    absent and refuse to write.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._gold = GoldKpiEnvelopesRepo(session)

    async def get_by_kind(self, shop_id: uuid.UUID, kind: str) -> AnalyticsKpiEnvelope | None:
        if kind != ANALYTICS_KIND:
            return None
        gold = await self._gold.get(shop_id)
        return None if gold is None else _gold_to_legacy_envelope(gold)

    async def upsert(
        self,
        *,
        shop_id: uuid.UUID,
        kind: str,
        envelope_version: int,
        payload: dict[str, Any],
        computed_at: datetime,
    ) -> AnalyticsKpiEnvelope:
        if kind != ANALYTICS_KIND:
            raise ValueError(f"unsupported envelope kind after gold cutover: {kind}")
        gold = await self._gold.upsert(
            shop_id=shop_id,
            envelope_version=envelope_version,
            payload=payload,
            computed_at=computed_at,
        )
        envelope = _gold_to_legacy_envelope(gold)
        envelope.computed_at = computed_at
        return envelope

    async def list(self, shop_id: uuid.UUID, *, limit: int = 50) -> list[AnalyticsKpiEnvelope]:
        gold = await self._gold.get(shop_id)
        if gold is None:
            return []
        return [_gold_to_legacy_envelope(gold)][:limit]


__all__ = [
    "ANALYTICS_KIND",
    "AnalyticsKpiEnvelopesRepo",
    "AnalyticsPerformanceRepo",
    "CreatorsRepo",
    "GoldKpiEnvelopesRepo",
    "LivestreamsRepo",
]
