"""Celery beat task: the daily Shopee KPI run (ADR-117 step 3).

``juli_backend.shopee_kpi_daily`` (default queue, daily 18:29 UTC = 01:29 UTC+7)
    ``services/shopee_kpi_daily.run_daily_kpi``: for each Shopee shop with a current
    KPI contract, store a new ``kpi_forecasts`` run unless the inputs are unchanged
    since the shop's newest one. One session per shop; a failure is counted and logged
    and tomorrow's run tries again.
"""

from __future__ import annotations

import asyncio
import logging

from juli_backend.services import shopee_kpi_daily as daily
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

SHOPEE_KPI_DAILY_TASK = "juli_backend.shopee_kpi_daily"


@celery_app.task(name=SHOPEE_KPI_DAILY_TASK)
def shopee_kpi_daily() -> dict[str, int]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        summary = asyncio.run(daily.run_daily_kpi(factory))
    except Exception as exc:
        logger.error("shopee_kpi_daily_failed", extra={"error_type": type(exc).__name__})
        return {}
    return {
        "scanned": summary.scanned,
        "ran": summary.ran,
        "skipped_nothing_landed": summary.skipped_nothing_landed,
        "skipped_unchanged": summary.skipped_unchanged,
        "refused": summary.refused,
        "failed": summary.failed,
    }


__all__ = ["SHOPEE_KPI_DAILY_TASK", "shopee_kpi_daily"]
