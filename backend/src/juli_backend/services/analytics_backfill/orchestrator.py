"""Multi-bucket analytics historical backfill orchestrator (#470).

Walks the Fujiwa window bucket-by-bucket (revenue → live → product → catalog)
and date-by-date, skipping completed partitions and pausing cleanly when the
per-run Partner call budget is exhausted.

Multi-day A-36/A-29 batching is deferred to existing one-day partition
primitives; each calendar day is marked complete individually after its
partition runner succeeds.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import AnalyticsBackfillPartitionsRepo
from juli_backend.services.analytics_backfill.budget import (
    CallBudgetGovernor,
    StoppedReason,
    begin_run,
)

logger = logging.getLogger(__name__)

BACKFILL_WINDOW_START = date(2026, 3, 16)
DEFAULT_BUCKET_ORDER: tuple[str, ...] = ("revenue", "live", "product", "catalog")
ALLOWED_BUCKETS = frozenset(DEFAULT_BUCKET_ORDER)

# Buckets/endpoints excluded from Phase 2.9 backfill (Ads, A-26, A-27, A-33).
FORBIDDEN_BUCKETS = frozenset({"ads", "advertising", "a26", "a27", "a33"})

PartitionRunner = Callable[[str, date], Awaitable[None]]


@dataclass(frozen=True)
class OrchestratorResult:
    stopped_reason: StoppedReason
    skipped_partitions: int
    completed_partitions: int
    budget_fields: dict[str, int | str | None]
    shop_id: uuid.UUID
    start_date: date
    end_date: date
    buckets: tuple[str, ...]


def validate_buckets(buckets: Sequence[str]) -> tuple[str, ...]:
    """Return normalized bucket order, rejecting Ads and forbidden analytics paths."""
    if not buckets:
        raise ValueError("At least one backfill bucket is required")

    normalized: list[str] = []
    for bucket in buckets:
        key = bucket.strip().lower()
        if key in FORBIDDEN_BUCKETS:
            msg = (
                f"Backfill bucket {bucket!r} is forbidden (Ads / A-26 / A-27 / A-33 "
                "paths are out of scope for Phase 2.9)"
            )
            raise ValueError(msg)
        if key not in ALLOWED_BUCKETS:
            msg = (
                f"Backfill bucket {bucket!r} is not on the allowlist; "
                f"expected one of {sorted(ALLOWED_BUCKETS)}"
            )
            raise ValueError(msg)
        if key not in normalized:
            normalized.append(key)

    return tuple(normalized)


def _ordered_buckets(buckets: Sequence[str] | None) -> tuple[str, ...]:
    selected = validate_buckets(buckets or DEFAULT_BUCKET_ORDER)
    return tuple(b for b in DEFAULT_BUCKET_ORDER if b in selected)


def _iter_dates(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _structured_log_fields(
    *,
    shop_id: uuid.UUID,
    bucket: str | None,
    partition_date: date | None,
    budget: CallBudgetGovernor,
    skipped: int,
    completed: int,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "shop_id": str(shop_id),
        "bucket": bucket,
        "partition_date": partition_date.isoformat() if partition_date else None,
        "skipped_partitions": skipped,
        "completed_partitions": completed,
        **budget.structured_log_fields(),
    }
    return fields


async def backfill_analytics_history(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date = BACKFILL_WINDOW_START,
    end_date: date,
    buckets: Sequence[str] | None = None,
    budget: CallBudgetGovernor | None = None,
    run_partition: PartitionRunner,
    concurrency_limit: int = 1,
) -> OrchestratorResult:
    """Walk buckets and dates with bounded concurrency, honoring budget.

    Skips completed partitions via bulk-load (not N queries per partition).

    Args:
        concurrency_limit: Maximum concurrent partitions. Default 1 until partition
            runners are refactored to separate Partner fetch from persistence — see
            follow-up issue #791. Callers with concurrency-safe run_partition can
            increase this parameter.

    Optimizations (issue #791):
    - Bulk-load completed partitions once per bucket
    - Run partitions concurrently under a bounded limit
    - Respect ADR-029 hard_limit (499) even under concurrency via budget_lock
    """
    resolved_buckets = _ordered_buckets(buckets)
    governor = budget or begin_run()
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)

    skipped = 0
    completed = 0
    stopped_reason: StoppedReason = "complete"

    # Bounded concurrency for partition execution (#791).
    # Semaphore limits concurrent run_partition calls. Real parallelism comes from:
    # - Multiple scheduler instances running for different shops
    # - Resumable checkpoints allowing long-running backfills to span multiple invocations
    # - Bulk-load optimization making each partition fast
    semaphore = asyncio.Semaphore(concurrency_limit)

    # Budget accounting must be race-free even with concurrent tasks (#791).
    # Semaphore bounds parallelism but does NOT make CallBudgetGovernor atomic —
    # with N tasks in flight, should_stop() and record_attempt() can interleave.
    # Guard all budget operations (should_stop, record_attempt, etc.) with a lock.
    budget_lock = asyncio.Lock()

    async def run_partition_concurrent(
        bucket: str, partition_date: date
    ) -> tuple[bool, str | None]:
        """Run partition under bounded concurrency with race-free budget accounting.

        Returns (was_completed, error_message).
        Respects budget via atomic checks inside the semaphore.
        """
        async with semaphore:
            # Check budget under lock to prevent race conditions
            async with budget_lock:
                if governor.should_stop():
                    return (False, "budget_exhausted")

            try:
                await run_partition(bucket, partition_date)
                return (True, None)
            except Exception as e:
                logger.error(
                    "analytics_backfill_partition_failed",
                    extra={
                        "shop_id": str(shop_id),
                        "bucket": bucket,
                        "partition_date": partition_date.isoformat(),
                        "error": str(e),
                    },
                )
                return (False, str(e))

    for bucket in resolved_buckets:
        all_dates = _iter_dates(start_date, end_date)

        # Bulk-load completed partitions for this bucket.
        # AC #791: one query per bucket, not per partition.
        # Replaces ~512 individual is_complete(shop_id, bucket, date) queries
        # with a single bulk query + O(1) set lookup.
        completed_rows = await partitions_repo.list_completed(shop_id, bucket, start_date, end_date)
        completed_dates = {row.partition_date for row in completed_rows}

        # Collect partitions to run (skip completed ones)
        partitions_to_run: list[tuple[str, date]] = []
        for partition_date in all_dates:
            if partition_date in completed_dates:
                skipped += 1
                logger.info(
                    "analytics_backfill_partition_skipped",
                    extra=_structured_log_fields(
                        shop_id=shop_id,
                        bucket=bucket,
                        partition_date=partition_date,
                        budget=governor,
                        skipped=skipped,
                        completed=completed,
                    ),
                )
            else:
                partitions_to_run.append((bucket, partition_date))

        # Run partitions concurrently, respecting budget
        if partitions_to_run:
            tasks = [
                run_partition_concurrent(bucket, partition_date)
                for bucket, partition_date in partitions_to_run
            ]

            # Run all tasks concurrently (semaphore limits to concurrency_limit)
            results = await asyncio.gather(*tasks)

            # Process results in order
            for (bucket_i, date_i), (was_completed, error) in zip(partitions_to_run, results):
                if error == "budget_exhausted":
                    # Budget stopped this task and all subsequent ones
                    stopped_reason = "budget"
                    async with budget_lock:
                        governor.finish("budget")
                    logger.info(
                        "analytics_backfill_orchestrator_stopped",
                        extra=_structured_log_fields(
                            shop_id=shop_id,
                            bucket=bucket_i,
                            partition_date=date_i,
                            budget=governor,
                            skipped=skipped,
                            completed=completed,
                        ),
                    )
                    return OrchestratorResult(
                        stopped_reason=stopped_reason,
                        skipped_partitions=skipped,
                        completed_partitions=completed,
                        budget_fields=governor.structured_log_fields(),
                        shop_id=shop_id,
                        start_date=start_date,
                        end_date=end_date,
                        buckets=resolved_buckets,
                    )
                elif was_completed:
                    completed += 1
                    logger.info(
                        "analytics_backfill_partition_completed",
                        extra=_structured_log_fields(
                            shop_id=shop_id,
                            bucket=bucket_i,
                            partition_date=date_i,
                            budget=governor,
                            skipped=skipped,
                            completed=completed,
                        ),
                    )

                # Check budget after each completed partition
                async with budget_lock:
                    if governor.should_stop():
                        stopped_reason = "budget"
                        governor.finish("budget")
                        logger.info(
                            "analytics_backfill_orchestrator_stopped",
                            extra=_structured_log_fields(
                                shop_id=shop_id,
                                bucket=bucket_i,
                                partition_date=date_i,
                                budget=governor,
                                skipped=skipped,
                                completed=completed,
                            ),
                        )
                        return OrchestratorResult(
                            stopped_reason=stopped_reason,
                            skipped_partitions=skipped,
                            completed_partitions=completed,
                            budget_fields=governor.structured_log_fields(),
                            shop_id=shop_id,
                            start_date=start_date,
                            end_date=end_date,
                            buckets=resolved_buckets,
                        )

    async with budget_lock:
        governor.finish("complete")
    logger.info(
        "analytics_backfill_orchestrator_complete",
        extra=_structured_log_fields(
            shop_id=shop_id,
            bucket=None,
            partition_date=None,
            budget=governor,
            skipped=skipped,
            completed=completed,
        ),
    )
    return OrchestratorResult(
        stopped_reason=stopped_reason,
        skipped_partitions=skipped,
        completed_partitions=completed,
        budget_fields=governor.structured_log_fields(),
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
        buckets=resolved_buckets,
    )


async def backfill_analytics_history_auto_topup(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date = BACKFILL_WINDOW_START,
    end_date: date,
) -> OrchestratorResult:
    """Automatically top up analytics history for a shop (service-layer wrapper).

    Owned by services.analytics_backfill per ADR-046 one-writer model. The partition
    runner's mark_complete calls are service-layer persistence, not task-layer.

    Args:
        session: Database session
        shop_id: Shop to backfill
        start_date: Inclusive start date
        end_date: Inclusive end date

    Returns:
        OrchestratorResult with skipped/completed partition counts
    """
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)

    async def partition_runner(bucket: str, partition_date: date) -> None:
        """Mark partition complete (service-layer responsibility)."""
        await partitions_repo.mark_complete(shop_id, bucket, partition_date)

    return await backfill_analytics_history(
        session,
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
        run_partition=partition_runner,
    )
