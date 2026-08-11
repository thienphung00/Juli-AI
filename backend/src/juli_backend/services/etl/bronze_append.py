"""ETL-owned append-only writers for targeted-fetch bronze payloads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    BronzeCtorPerformanceRawPayload,
    BronzeLiveHoursRawPayload,
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
)
from juli_backend.repositories.repos import (
    BronzeCtorPerformanceRawPayloadsRepo,
    BronzeLiveHoursRawPayloadsRepo,
    BronzeOrderRawPayloadsRepo,
    BronzeReturnRawPayloadsRepo,
)

TARGETED_FETCH_INGEST_SOURCE = "targeted_fetch"


async def append_targeted_order_payload(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    payload: dict[str, Any],
    received_at: datetime,
    source_event_id: str,
) -> uuid.UUID | None:
    """Append one order payload unless this shop/source event already exists."""
    existing = await session.execute(
        select(BronzeOrderRawPayload.id).where(
            BronzeOrderRawPayload.shop_id == shop_id,
            BronzeOrderRawPayload.source_event_id == source_event_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    order_id = str(payload.get("order_id") or payload.get("tiktok_order_id") or "") or None
    rows = await BronzeOrderRawPayloadsRepo(session).append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": TARGETED_FETCH_INGEST_SOURCE,
                "payload": payload,
                "received_at": received_at,
                "tiktok_order_id": order_id,
                "source_event_id": source_event_id,
            }
        ]
    )
    return rows[0].id if rows else None


async def append_targeted_return_payload(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    payload: dict[str, Any],
    received_at: datetime,
    source_event_id: str,
) -> uuid.UUID | None:
    """Append one return payload unless this shop/source event already exists."""
    existing = await session.execute(
        select(BronzeReturnRawPayload.id).where(
            BronzeReturnRawPayload.shop_id == shop_id,
            BronzeReturnRawPayload.source_event_id == source_event_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    return_id = str(payload.get("return_id") or payload.get("tiktok_return_id") or "") or None
    order_id = str(payload.get("order_id") or payload.get("tiktok_order_id") or "") or None
    rows = await BronzeReturnRawPayloadsRepo(session).append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": TARGETED_FETCH_INGEST_SOURCE,
                "payload": payload,
                "received_at": received_at,
                "tiktok_return_id": return_id,
                "tiktok_order_id": order_id,
                "source_event_id": source_event_id,
            }
        ]
    )
    return rows[0].id if rows else None


async def append_targeted_ctor_payload(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    payload: dict[str, Any],
    received_at: datetime,
    source_event_id: str,
) -> uuid.UUID | None:
    """Append one A-34 product performance row unless already recorded (#880).

    ``payload`` is the already-normalized ``expand_analytics_product_list_item``
    row (grain/start_date/snapshot_key/metric fields), matching the shape the
    analytics backfill product partition hands the transform layer — bronze
    here mirrors that "pre-normalized entity" convention, not raw wire JSON.
    """
    existing = await session.execute(
        select(BronzeCtorPerformanceRawPayload.id).where(
            BronzeCtorPerformanceRawPayload.shop_id == shop_id,
            BronzeCtorPerformanceRawPayload.source_event_id == source_event_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    product_id = str(payload.get("product_id") or "") or None
    rows = await BronzeCtorPerformanceRawPayloadsRepo(session).append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": TARGETED_FETCH_INGEST_SOURCE,
                "payload": payload,
                "received_at": received_at,
                "tiktok_product_id": product_id,
                "source_event_id": source_event_id,
            }
        ]
    )
    return rows[0].id if rows else None


async def append_targeted_live_hours_payload(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    payload: dict[str, Any],
    received_at: datetime,
    source_event_id: str,
) -> uuid.UUID | None:
    """Append one A-28 LIVE performance row unless already recorded (#880).

    ``payload`` is either an ``expand_analytics_live_session`` per-session row
    (``live_id`` set, grain ``"live"``) or the derived shop-grain daily rollup
    (``live_id`` unset, grain ``"shop"``) — both flow through the same table
    and the same ``tiktok.analytics.live.raw`` silver-promotion channel.
    """
    existing = await session.execute(
        select(BronzeLiveHoursRawPayload.id).where(
            BronzeLiveHoursRawPayload.shop_id == shop_id,
            BronzeLiveHoursRawPayload.source_event_id == source_event_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    live_id = str(payload.get("live_id") or "") or None
    rows = await BronzeLiveHoursRawPayloadsRepo(session).append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": TARGETED_FETCH_INGEST_SOURCE,
                "payload": payload,
                "received_at": received_at,
                "tiktok_live_id": live_id,
                "source_event_id": source_event_id,
            }
        ]
    )
    return rows[0].id if rows else None
