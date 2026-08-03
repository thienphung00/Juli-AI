"""ETL handoff wrapper that enqueues material Analytics precompute after success."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from juli_backend.services.cdp_speed import webhook_catalog_enqueue_reason
from juli_backend.services.etl.consumer import ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.ingestion.handoff import HandoffFn
from juli_backend.services.tiktok.webhook_catalog import catalog_id_for_event
from juli_backend.services.webhook.material_dispatch import maybe_enqueue_material_analytics_compute

if TYPE_CHECKING:
    from juli_backend.services.etl.consumer import EtlConsumer

logger = logging.getLogger(__name__)


def make_material_etl_handoff(
    consumer: EtlConsumer,
    *,
    clock: Callable[[], float] = time.time,
) -> HandoffFn:
    """Return handoff that ingests through ETL then enqueues material Analytics compute."""

    async def handoff(channel: str, shop_key: str, payload: bytes) -> None:
        outcome = await consumer.ingest(
            IngestRecord(
                channel=channel,
                shop_key=shop_key,
                value=payload,
                received_at=clock(),
            )
        )
        if outcome is not ProcessOutcome.PROCESSED:
            return

        try:
            raw = json.loads(payload)
            event_type = str(raw.get("type", ""))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, AttributeError):
            logger.warning(
                "material_enqueue_skip_unparseable_payload",
                extra={"shop_key": shop_key, "channel": channel},
            )
            return

        task_id = maybe_enqueue_material_analytics_compute(shop_key, event_type)
        if task_id is not None:
            catalog_id = catalog_id_for_event(event_type)
            reason = (
                webhook_catalog_enqueue_reason(catalog_id)
                if catalog_id is not None
                else "webhook_catalog:unknown"
            )
            logger.info(
                "material_analytics_compute_enqueued",
                extra={
                    "shop_key": shop_key,
                    "event_type": event_type,
                    "task_id": task_id,
                    "enqueue_reason": reason,
                },
            )

    return handoff
