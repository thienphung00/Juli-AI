"""Celery task entrypoint for the daily impact-reader beat task — ADR-077
decision 5 (#1044).

Scheduled after ``analytics-backfill-topup`` (``workers/celery_app.py``) so
the reference shop's daily analytics partitions are as fresh as that day's
top-up can make them before this task reads them — though per the
reference-shop gap (the daily topup is hardcoded to
``DEMO_REFERENCE_SHOP_ID``, see ``workers/tasks/analytics_backfill_topup.py``),
every other shop's ``analytics_performance_intervals`` stays whatever it was
left at by the last manual refresh. That is exactly the missing-daily-rows
case ``workers/impact_reader/pipeline.py`` degrades to a ``suppressed``
reading for, never a crash — this task itself is not shop-scoped; it scans
terminal executions across every shop and lets the per-metric confidence
pipeline decide.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _run_daily_impact_reader_async() -> None:
    factory = _ensure_session_factory()
    reference_date = datetime.now(UTC).date()
    async with factory() as session:
        result = await run_daily_impact_reader(session, reference_date)
        await session.commit()
        logger.info(
            "daily_impact_reader_complete",
            extra={
                "reference_date": reference_date.isoformat(),
                "executions_scanned": result.executions_scanned,
                "readings_written": result.readings_written,
                "executions_skipped_unclassified": result.executions_skipped_unclassified,
            },
        )


@celery_app.task(name="juli_backend.daily_impact_reader")
def daily_impact_reader() -> None:
    """Celery Beat periodic task — computes elapsed T+7/T+14 impact readings.

    Idempotent by construction (ADR-077 decision 5 / #1040's unique
    constraint on ``(tool_execution_id, metric, kind)`` is the backstop; the
    reader's own pre-write existence checks in ``workers/impact_reader/
    pipeline.py`` are what actually prevent a re-run from ever reaching it):
    a re-run over identical state writes nothing new and raises nothing.

    Exception handling mirrors ``analytics_backfill_topup``: any unhandled
    exception is logged with structured context and re-raised so Celery
    retry logic can kick in; runtime is bounded to prevent an indefinite hang.
    """
    timeout_seconds = 300  # 5 minutes max, matching analytics_backfill_topup
    try:
        asyncio.run(asyncio.wait_for(_run_daily_impact_reader_async(), timeout=timeout_seconds))
    except TimeoutError:
        logger.error(
            "daily_impact_reader_timeout",
            extra={"timeout_seconds": timeout_seconds},
        )
        raise
    except Exception as exc:
        logger.error(
            "daily_impact_reader_failed",
            extra={
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            exc_info=True,
        )
        raise
