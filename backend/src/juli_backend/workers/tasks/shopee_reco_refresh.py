"""Celery beat task: recompute the stale Shopee recommendation cards (daily safety net).

``juli_backend.shopee_reco_refresh`` (default queue, daily 19:11 UTC): for every Shopee shop, flag
the open cards whose engine version or inputs fingerprint no longer matches and recompute them
(``services/shopee_reco_refresh``). Idempotent; the same refresh also runs after each input write
and once when the API starts. One session per shop; a failure is counted and never stops the rest.
"""

from __future__ import annotations

import asyncio

from juli_backend.services import shopee_reco_refresh as refresh
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

SHOPEE_RECO_REFRESH_TASK = "juli_backend.shopee_reco_refresh"


@celery_app.task(name=SHOPEE_RECO_REFRESH_TASK)
def shopee_reco_refresh() -> dict[str, int]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    summary = asyncio.run(refresh.run_refresh_all(factory, "daily_beat"))
    return {
        "shops": summary.shops,
        "failed": summary.failed,
        "stale": summary.stale,
        "refreshed": summary.refreshed,
    }


__all__ = ["SHOPEE_RECO_REFRESH_TASK", "shopee_reco_refresh"]
