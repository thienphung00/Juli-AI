"""Scheduled task to keep shop analytics history current via automatic backfill.

Issue #791: Replaces manual operator CLI invocation with a scheduled Celery Beat task
that tops up missing or stale analytics partitions for the reference shop.

SCOPE DECISION (Issue #601 US #30, A1 vs A2): Single-shop (reference shop) only.
- Single-shop top-up defensible in A1 (matches mock_analytics_hourly_reconcile)
- Fleet-wide reconciliation belongs in A2 (CDP-A2-9, services/cdp_batch/)
- Runs daily for DEMO_REFERENCE_SHOP_ID only; does not fan out to all shops

Checkpoints in AnalyticsBackfillPartitionsRepo make this safely idempotent and resumable:
- Already-complete partitions are skipped
- Failed/stale partitions are retried (if within history window)
- No duplicate Partner calls on repeated runs
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)


def get_demo_reference_shop_id() -> uuid.UUID | None:
    """Return configured Demo reference shop id, if set."""
    raw = os.getenv("DEMO_REFERENCE_SHOP_ID", "").strip()
    if not raw:
        return None
    return uuid.UUID(raw)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory():
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.database.database import create_session_factory, init_session_factory

    engine = create_async_engine(_database_url())
    factory = create_session_factory(engine)
    init_session_factory(factory)
    return factory


def _get_backfill_date_range() -> tuple[date, date]:
    """Get the date range for automatic backfill top-up.

    Default: last 30 days from today (to keep partition lag bounded).
    Configurable via ANALYTICS_BACKFILL_HISTORY_DAYS env var.

    AC #791: Ensures scheduled run stays within reasonable bounds and completes quickly.
    Resumable checkpoints (AnalyticsBackfillPartitionsRepo) ensure across-run continuity
    if a run is paused due to budget.
    """
    history_days = int(os.getenv("ANALYTICS_BACKFILL_HISTORY_DAYS", "30"))
    end_date = date.today()
    start_date = end_date - timedelta(days=history_days)
    return start_date, end_date


async def run_analytics_backfill_topup_for_shop(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> None:
    """Top up missing or stale analytics partitions for a single shop.

    Thin wrapper that delegates to services.analytics_backfill per ADR-046 one-writer model.
    Partition persistence (mark_complete) is owned by the service layer, not the task layer.
    """
    from juli_backend.services.analytics_backfill import backfill_analytics_history_auto_topup

    start_date, end_date = _get_backfill_date_range()

    logger.info(
        "analytics_backfill_topup_started",
        extra={
            "shop_id": str(shop_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )

    result = await backfill_analytics_history_auto_topup(
        session,
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
    )

    logger.info(
        "analytics_backfill_topup_complete",
        extra={
            "shop_id": str(shop_id),
            "stopped_reason": result.stopped_reason,
            "skipped_partitions": result.skipped_partitions,
            "completed_partitions": result.completed_partitions,
            **result.budget_fields,
        },
    )

    await session.commit()


async def _run_analytics_backfill_topup_async() -> None:
    """Run analytics backfill top-up for the reference shop (async entrypoint)."""
    shop_id = get_demo_reference_shop_id()
    if shop_id is None:
        logger.info(
            "analytics_backfill_topup_skipped",
            extra={"reason": "missing_demo_reference_shop_id"},
        )
        return

    factory = _ensure_session_factory()
    async with factory() as session:
        await run_analytics_backfill_topup_for_shop(session=session, shop_id=shop_id)


@celery_app.task(name="juli_backend.analytics_backfill_topup")
def analytics_backfill_topup() -> None:
    """Celery Beat periodic task for automatic analytics history top-up.

    Runs once per configured interval (e.g., daily) to keep analytics partitions current.
    Uses the resumable checkpoint system (AnalyticsBackfillPartitionsRepo) to safely
    skip already-complete partitions and avoid duplicate Partner calls.

    SCOPE: Single-shop (DEMO_REFERENCE_SHOP_ID) only, A1 phase.
    Fleet-wide reconciliation belongs in A2 (issue #601 US #30).
    """
    asyncio.run(_run_analytics_backfill_topup_async())
