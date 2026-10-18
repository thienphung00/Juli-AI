"""Celery beat task: the Juli Ops audit log's retention (fast track P18, D27.4).

``juli_backend.ops_audit_retention`` (default queue, nightly)
    Deletes ``ops_audit_log`` rows past their kind's retention: configuration
    changes after 365 days, "Xem như shop" sessions / data refreshes and system
    jobs after 90 days (``services/ops/audit.purge_expired``). Runs as
    ``juli_ops`` (the only role with DELETE on the table, migration 085). A
    failure is logged; tomorrow's run catches up.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

OPS_AUDIT_RETENTION_TASK = "juli_backend.ops_audit_retention"


async def run_ops_audit_retention(session_factory: Any, *, now: datetime | None = None) -> int:
    """Delete the expired rows and commit; returns how many were deleted."""
    from juli_backend.services.ops import purge_expired

    async with session_factory() as session:
        deleted = await purge_expired(session, now=now)
        await session.commit()
    logger.info("ops_audit_retention", extra={"deleted": deleted})
    return deleted


@celery_app.task(name=OPS_AUDIT_RETENTION_TASK)
def ops_audit_retention() -> int:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        return asyncio.run(run_ops_audit_retention(factory))
    except Exception as exc:
        logger.error(
            "ops_audit_retention_failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:200]},
            exc_info=True,
        )
        return 0


__all__ = ["OPS_AUDIT_RETENTION_TASK", "ops_audit_retention", "run_ops_audit_retention"]
