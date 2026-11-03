"""Celery beat task: the daily Shopee KPI run (ADR-117 step 3).

``juli_backend.shopee_kpi_daily`` (default queue, daily 18:29 UTC = 01:29 UTC+7)
    ``services/shopee_kpi_daily.run_daily_kpi``: for each Shopee shop with a current
    KPI contract, store a new ``kpi_forecasts`` run unless the inputs are unchanged
    since the shop's newest one. Then ``services/shop_proposals.measure_all`` (ADR-118
    §3, D81.3): a result row for each executed proposal whose data moved forward. One
    session per shop; a failure is counted and logged and tomorrow's run tries again. The
    measurement runs even when the KPI run failed -- the two read different rows.
"""

from __future__ import annotations

import asyncio
import logging

from juli_backend.services import shopee_kpi_daily as daily
from juli_backend.services.shop_proposals import measure_all
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

SHOPEE_KPI_DAILY_TASK = "juli_backend.shopee_kpi_daily"


@celery_app.task(name=SHOPEE_KPI_DAILY_TASK)
def shopee_kpi_daily() -> dict[str, int]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    # One event loop for both steps: the worker's engine must not cross loops.
    return asyncio.run(_run(factory))


async def _run(factory: daily.SessionFactory) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        summary = await daily.run_daily_kpi(factory)
        out.update(
            scanned=summary.scanned,
            ran=summary.ran,
            skipped_nothing_landed=summary.skipped_nothing_landed,
            skipped_unchanged=summary.skipped_unchanged,
            refused=summary.refused,
            failed=summary.failed,
        )
    except Exception as exc:
        logger.error("shopee_kpi_daily_failed", extra={"error_type": type(exc).__name__})
    try:
        measured = await measure_all(factory)
        out.update(
            proposals_written=measured.counts.written,
            proposals_measured=measured.counts.measured,
            proposal_shops_failed=measured.failed,
        )
    except Exception as exc:
        logger.error("shopee_proposal_measure_failed", extra={"error_type": type(exc).__name__})
    return out


__all__ = ["SHOPEE_KPI_DAILY_TASK", "shopee_kpi_daily"]
