"""Celery task: the stored-facts backfill right after a deploy (owner decision #74, plan a).

``juli_backend.shopee_facts_backfill`` (default queue): once when a worker starts
(``worker_ready``: the deploy restarts the worker right after migrating) and on the beat, so a
release that changes the facts' ``derivation_version`` is rebuilt within minutes, not at the
nightly job. ``services.shopee_analytics.facts_backfill.run`` does the work (real Shopee shops
only, one at a time, newest days first, advisory-locked, idempotent; counts-only logs). A failure
is logged; the next beat catches up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery.signals import worker_ready

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

SHOPEE_FACTS_BACKFILL_TASK = "juli_backend.shopee_facts_backfill"


@celery_app.task(name=SHOPEE_FACTS_BACKFILL_TASK)
def shopee_facts_backfill() -> dict[str, Any]:
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.services.shopee_analytics import facts_backfill

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        return asyncio.run(facts_backfill.run(factory)).as_log()
    except Exception as exc:
        logger.error(
            "shopee_facts_backfill_failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:200]},
            exc_info=True,
        )
        return {"failed": True}


@worker_ready.connect
def _backfill_at_worker_start(**_: Any) -> None:
    """Queue one run as the worker comes up (right after the deploy migrated)."""
    try:
        shopee_facts_backfill.apply_async()
    except Exception as exc:  # the beat run catches up
        logger.warning(
            "shopee_facts_backfill_enqueue_failed", extra={"error_type": type(exc).__name__}
        )


__all__ = ["SHOPEE_FACTS_BACKFILL_TASK", "shopee_facts_backfill"]
