"""Celery task: the automatic business backfill (P101 W1, owner rule T2).

``juli_backend.businesses_backfill`` (default queue): beat every 10 minutes, and once when a worker
starts (``worker_ready``), so a release carrying migration 130 backfills within seconds of the
worker restart that deploys it. ``services.businesses.run_backfill`` (``backfill.py``) does the work
(idempotent, batched, advisory-locked, counts-only logs); once every shop has a business a run is
two cheap reads. A failure is logged; the next run catches up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery.signals import worker_ready

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

BUSINESSES_BACKFILL_TASK = "juli_backend.businesses_backfill"


@celery_app.task(name=BUSINESSES_BACKFILL_TASK)
def businesses_backfill() -> dict[str, Any]:
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.services.businesses import run_backfill

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        return asyncio.run(run_backfill(factory)).as_log()
    except Exception as exc:
        logger.error(
            "businesses_backfill_failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:200]},
            exc_info=True,
        )
        return {"failed": True}


@worker_ready.connect
def _backfill_at_worker_start(**_: Any) -> None:
    """Queue one run as the worker comes up (the deploy restarts it right after migrating)."""
    try:
        businesses_backfill.apply_async()
    except Exception as exc:  # the beat run 10 minutes later catches up
        logger.warning(
            "businesses_backfill_enqueue_failed", extra={"error_type": type(exc).__name__}
        )


__all__ = ["BUSINESSES_BACKFILL_TASK", "businesses_backfill"]
