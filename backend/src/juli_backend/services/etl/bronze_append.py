"""ETL-owned append-only writers for targeted-fetch bronze payloads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import BronzeOrderRawPayload, BronzeReturnRawPayload
from juli_backend.repositories.repos import (
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
