"""Bronze append handoff for targeted Partner fetch rows (#627)."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import BronzeOrderRawPayload, BronzeReturnRawPayload
from juli_backend.repositories.repos import (
    BronzeOrderRawPayloadsRepo,
    BronzeReturnRawPayloadsRepo,
)
from juli_backend.services.ingestion.handoff import HandoffFn

logger = logging.getLogger(__name__)

INGEST_SOURCE = "targeted_fetch"


@dataclass
class BronzeAppendTracker:
    """Bronze rows appended during one Shared Compute bronze stage."""

    order_row_ids: list[uuid.UUID] = field(default_factory=list)
    return_row_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def appended_count(self) -> int:
        return len(self.order_row_ids) + len(self.return_row_ids)


def _order_source_event_id(job_token: str, payload: dict[str, Any]) -> str:
    order_id = str(payload.get("order_id") or payload.get("tiktok_order_id") or "")
    update_time = str(payload.get("update_time") or "")
    return f"{job_token}:orders:{order_id}:{update_time}"


def _return_source_event_id(job_token: str, payload: dict[str, Any]) -> str:
    return_id = str(payload.get("return_id") or payload.get("tiktok_return_id") or "")
    update_time = str(payload.get("update_time") or "")
    return f"{job_token}:returns:{return_id}:{update_time}"


def make_targeted_fetch_bronze_handoff(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    job_token: str,
    tracker: BronzeAppendTracker,
    clock: Callable[[], datetime] | None = None,
) -> HandoffFn:
    """Return a handoff that append-only writes Partner rows to bronze."""

    orders_repo = BronzeOrderRawPayloadsRepo(session)
    returns_repo = BronzeReturnRawPayloadsRepo(session)

    async def handoff(channel: str, shop_key: str, payload: bytes) -> None:
        del shop_key  # shop scope enforced by caller + shop_id
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            logger.warning(
                "targeted_fetch_bronze_skip_unparseable",
                extra={"channel": channel, "correlation_id": job_token},
            )
            return
        if not isinstance(data, dict):
            return

        received_at = clock() if clock else datetime.now(tz=UTC)

        if channel == "tiktok.orders.raw":
            source_event_id = _order_source_event_id(job_token, data)
            existing = await session.execute(
                select(BronzeOrderRawPayload.id).where(
                    BronzeOrderRawPayload.shop_id == shop_id,
                    BronzeOrderRawPayload.source_event_id == source_event_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                return

            order_id = str(data.get("order_id") or data.get("tiktok_order_id") or "") or None
            rows = await orders_repo.append_batch(
                [
                    {
                        "shop_id": shop_id,
                        "ingest_source": INGEST_SOURCE,
                        "payload": data,
                        "received_at": received_at,
                        "tiktok_order_id": order_id,
                        "source_event_id": source_event_id,
                    },
                ]
            )
            tracker.order_row_ids.extend(row.id for row in rows)
            return

        if channel == "tiktok.returns.raw":
            source_event_id = _return_source_event_id(job_token, data)
            existing = await session.execute(
                select(BronzeReturnRawPayload.id).where(
                    BronzeReturnRawPayload.shop_id == shop_id,
                    BronzeReturnRawPayload.source_event_id == source_event_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                return

            return_id = str(data.get("return_id") or data.get("tiktok_return_id") or "") or None
            order_id = str(data.get("order_id") or data.get("tiktok_order_id") or "") or None
            return_rows = await returns_repo.append_batch(
                [
                    {
                        "shop_id": shop_id,
                        "ingest_source": INGEST_SOURCE,
                        "payload": data,
                        "received_at": received_at,
                        "tiktok_return_id": return_id,
                        "tiktok_order_id": order_id,
                        "source_event_id": source_event_id,
                    },
                ]
            )
            tracker.return_row_ids.extend(row.id for row in return_rows)

    return handoff
