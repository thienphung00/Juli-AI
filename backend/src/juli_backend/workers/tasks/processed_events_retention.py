"""Celery beat task: ``processed_events`` retention (fast track P62-B, D72.2).

``juli_backend.processed_events_retention`` (default queue, nightly)
    Deletes ETL idempotency-ledger rows older than
    ``PROCESSED_EVENTS_RETENTION_DAYS`` through the owner-role
    ``purge_processed_events`` function (migration 098), in committed batches
    (``services/etl/persistence/ingest/retention.py``). A failure is logged;
    tomorrow's run catches up.
"""

from __future__ import annotations

import asyncio
import logging

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

PROCESSED_EVENTS_RETENTION_TASK = "juli_backend.processed_events_retention"


@celery_app.task(name=PROCESSED_EVENTS_RETENTION_TASK)
def processed_events_retention() -> int:
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.services.etl.persistence.ingest.retention import purge_processed_events

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        return asyncio.run(purge_processed_events(factory)).deleted
    except Exception as exc:
        logger.error(
            "processed_events_retention_failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:200]},
            exc_info=True,
        )
        return 0


__all__ = ["PROCESSED_EVENTS_RETENTION_TASK", "processed_events_retention"]
