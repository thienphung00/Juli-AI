"""Celery task entrypoint for the daily impact-reader beat task — ADR-077
decision 5 (#1044), rewritten per ADR-089 for per-tenant context (#1488).

Runs daily at 03:23 UTC (``workers/celery_app.py``). Every connected shop's
``analytics_performance_intervals`` is kept current by that shop's own
``poll_shop`` cycle (at most one analytics pass per shop per UTC day,
``workers/services/polling/ingestion.py::_daily_analytics``); fast track P61-D
retired the reference-shop-only top-up this task used to follow. A day the
shop's poll has not landed yet is the missing-daily-rows case
``workers/impact_reader/pipeline.py`` degrades to a ``suppressed`` reading for,
never a crash.

The task enumerates measurable executions via a SECURITY DEFINER function
that returns identifiers and scheduling metadata only, then loops over them
setting per-execution context (the execution's shop). Every data access is
then under the execution's shop scope, not fleet-wide system_scope, so RLS
policies are satisfied and the two-tenant proof covers the whole work.
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
        # Per ADR-089 decision 2: impact_reader enumerates via SECURITY DEFINER
        # function, then loops with per-execution context. No system_scope
        # exemption needed — every data access is under the execution's shop context.
        result = await run_daily_impact_reader(session, reference_date)
        await session.commit()
        logger.info(
            "daily_impact_reader_complete",
            extra={
                "reference_date": reference_date.isoformat(),
                "executions_scanned": result.executions_scanned,
                "readings_written": result.readings_written,
                "executions_skipped_unclassified": result.executions_skipped_unclassified,
                "executions_skipped_simulated": result.executions_skipped_simulated,
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
