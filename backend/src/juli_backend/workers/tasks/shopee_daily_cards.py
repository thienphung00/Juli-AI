"""Celery task: new Shopee recommendation cards for the seller, every day.

``juli_backend.shopee_daily_cards`` (default queue):

- with a shop id: that one shop, enqueued by ``POST /v1/ingest/connector-ticks`` when the
  Connector's daily run reports in (the primary trigger);
- without: the 02:03 UTC beat (09:03 GMT+7), the fallback for every real Shopee shop that has no
  daily generation yet today (``services/shopee_recommendations/daily_generation``).

Idempotent per (shop, local day). A failure is counted and logged and never raises out.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from juli_backend.services.shopee_recommendations import daily_generation as daily
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

SHOPEE_DAILY_CARDS_TASK = "juli_backend.shopee_daily_cards"


@celery_app.task(name=SHOPEE_DAILY_CARDS_TASK)
def shopee_daily_cards(shop_id: str | None = None) -> dict[str, int | str]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    if shop_id is None:
        summary = asyncio.run(daily.run_all(factory, "daily_beat"))
        return {
            "shops": summary.shops,
            "done": summary.done,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "cards": summary.cards,
        }
    try:
        result = asyncio.run(daily.run_one(factory, uuid.UUID(shop_id), "connector_daily_run"))
    except Exception as exc:  # type only: a message can carry client values
        logger.error(
            "shopee_daily_cards_shop_failed",
            extra={"shop_id": shop_id, "error_type": type(exc).__name__},
        )
        return {"status": "failed", "failed": 1}
    return {"status": result.status, "cards": result.sent}


__all__ = ["SHOPEE_DAILY_CARDS_TASK", "shopee_daily_cards"]
