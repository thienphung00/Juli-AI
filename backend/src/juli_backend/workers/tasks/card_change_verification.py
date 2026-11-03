"""Celery beat task: read-back verification of executed card changes (P90 assisted execution).

``juli_backend.card_change_verification`` (default queue, 01:17 / 07:17 / 13:17 / 19:17 UTC)
    ``services/card_change_verification.run_verification``: for each Shopee shop, compare the
    Connector's readings after each ``executed`` change with its expected value and write
    ``verified`` / ``mismatch`` / ``not_seen`` to ``card_events``. DB only, idempotent.
"""

from __future__ import annotations

import asyncio
import logging

from juli_backend.services import card_change_verification as job
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

CARD_CHANGE_VERIFICATION_TASK = "juli_backend.card_change_verification"


@celery_app.task(name=CARD_CHANGE_VERIFICATION_TASK)
def card_change_verification() -> dict[str, int]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        run = asyncio.run(job.run_verification(factory))
    except Exception as exc:
        logger.error("card_change_verification_failed", extra={"error_type": type(exc).__name__})
        return {"failed": 1}
    return {
        "shops": run.shops,
        "checked": run.checked,
        "verified": run.verified,
        "mismatch": run.mismatch,
        "not_seen": run.not_seen,
        "failed_shops": run.failed_shops,
    }


__all__ = ["CARD_CHANGE_VERIFICATION_TASK", "card_change_verification"]
