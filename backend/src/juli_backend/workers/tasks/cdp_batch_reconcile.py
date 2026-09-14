"""Celery Beat periodic task for CDP batch staggered reconcile (#622 / CDP-A2-9).

Enqueues BatchReconcileOrchestrator jobs based on StaggerScheduler windows:
- One reconcile window per shop per UTC day (no global hourly full poll)
- Guarded by config flag CDP_BATCH_STAGGERED_RECONCILE_ENABLED (default OFF)
- Rollout allowlist restricts to Fujiwa reference shop + N stub shops
- Rejects fake_refresh / visitor-triggered enqueue (PRD US #25)
- Does not duplicate A1 hourly exception (US #27)

Mixed-version hazard: a newly-named Celery task is unregistered on workers
still running a previous image — the flag must stay off until all consumers
of the target queue have the new task registered.

Issue #1857 (W8-F / P10-6): before this change, the flag-off tick returned in
~2ms having written no log line at all -- an instant "succeeded" indistinguishable
from real work. `cdp_batch_staggered_reconcile_tick_complete` now fires on every
branch (flag off, empty allowlist, no shop in window, and the normal enqueue
path), always carrying `enqueued_count` (0 for every no-op branch) and a
measured `duration_ms`. The pre-existing `cdp_batch_staggered_reconcile_skipped`
line for the empty-allowlist branch is RETAINED, not folded -- both lines fire
for that branch, so a log consumer keyed on either one keeps working. An
exception raised outside the per-shop loop (e.g. `StaggerScheduler.assign_window`)
still emits the completion fact via an outer `try/finally` and then re-raises --
the exception is never swallowed.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime

from juli_backend.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    """Check if staggered batch reconcile is enabled via config flag."""
    flag = os.getenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "false").strip().lower()
    return flag in ("true", "1", "yes")


def _get_rollout_allowlist() -> list[str]:
    """Load rollout allowlist from config: comma-separated shop IDs."""
    allowlist_str = os.getenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", "").strip()
    if not allowlist_str:
        return []
    return [shop_id.strip() for shop_id in allowlist_str.split(",") if shop_id.strip()]


def _get_enabled_shops() -> list[str]:
    """Get list of shops to enqueue in this beat tick."""
    if not _is_enabled():
        return []
    return _get_rollout_allowlist()


@celery_app.task(name="juli_backend.cdp_batch_staggered_reconcile")
def cdp_batch_staggered_reconcile_beat_tick(*, clock: Callable[[], float] | None = None) -> None:
    """Celery Beat periodic task for staggered batch reconcile enqueue.

    Executes once per configured interval (e.g., minutely); enqueues jobs for
    shops whose assigned window minute matches current UTC minute.

    Guard: config flag CDP_BATCH_STAGGERED_RECONCILE_ENABLED must be ON.
    Allowlist: only shop IDs in CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST are enqueued.

    `cdp_batch_staggered_reconcile_tick_complete` fires on EVERY exit path
    (#1857) -- flag off, empty allowlist, no shop in window, or a normal
    enqueue pass -- always carrying `enqueued_count` (0 on every no-op branch)
    and a `duration_ms` measured from `clock` (defaults to `time.monotonic`;
    tests inject a fake to assert the delta rather than mere non-nullness).
    The outer `try/finally` means an exception raised outside the per-shop
    loop (e.g. `StaggerScheduler.assign_window`) still emits the completion
    fact and then re-raises -- it is never swallowed.
    """
    clock = clock or time.monotonic
    started_at = clock()
    enqueued_count = 0
    try:
        if not _is_enabled():
            return

        enabled_shops = _get_enabled_shops()
        if not enabled_shops:
            # Retained, not folded into the completion line below (#1857):
            # an existing log consumer keyed on this reason keeps working.
            logger.info(
                "cdp_batch_staggered_reconcile_skipped",
                extra={"reason": "empty_allowlist"},
            )
            return

        # Get current UTC time
        now_utc = datetime.utcnow()
        current_minute = now_utc.hour * 60 + now_utc.minute
        current_day = now_utc.date()

        # Import here to avoid circular imports
        from juli_backend.services.cdp_batch import (
            StaggerScheduler,
            is_batch_fetch_trigger_allowed,
        )

        scheduler = StaggerScheduler()

        for shop_id in enabled_shops:
            # Get assigned window for this shop on this day
            window = scheduler.assign_window(shop_id, current_day)

            # Enqueue only if current minute matches this shop's window minute
            if window.minute_of_day != current_minute:
                continue

            # Guard: reject public/visitor trigger sources (PRD US #25)
            # Beat-scheduled jobs use trigger_source="batch_reconcile" internally
            if not is_batch_fetch_trigger_allowed("batch_reconcile"):
                logger.warning(
                    "cdp_batch_staggered_reconcile_rejected_trigger_source",
                    extra={
                        "shop_id": shop_id,
                        "reason": "forbidden_trigger_source",
                    },
                )
                continue

            # Enqueue the job
            try:
                celery_app.send_task(
                    "juli_backend.cdp_batch_reconcile_orchestrator_task",
                    kwargs={
                        "shop_id": shop_id,
                        "partition_date": current_day.isoformat(),
                        "reconcile_window": window,
                    },
                    queue="cdp_batch",
                )
                logger.info(
                    "cdp_batch_staggered_reconcile_enqueued",
                    extra={
                        "shop_id": shop_id,
                        "window_minute": window.minute_of_day,
                        "partition_date": current_day.isoformat(),
                    },
                )
                enqueued_count += 1
            except Exception as e:
                logger.error(
                    "cdp_batch_staggered_reconcile_enqueue_failed",
                    extra={
                        "shop_id": shop_id,
                        "error": str(e),
                    },
                )
    finally:
        duration_ms = int((clock() - started_at) * 1000)
        logger.info(
            "cdp_batch_staggered_reconcile_tick_complete",
            extra={"enqueued_count": enqueued_count, "duration_ms": duration_ms},
        )
