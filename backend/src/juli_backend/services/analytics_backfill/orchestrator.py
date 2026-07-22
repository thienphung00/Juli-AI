"""Multi-bucket analytics historical backfill orchestrator (#470).

Walks the Fujiwa window bucket-by-bucket (revenue → live → product → catalog)
and date-by-date, skipping completed partitions and pausing cleanly when the
per-run Partner call budget is exhausted.

Multi-day A-36/A-29 batching is deferred to existing one-day partition
primitives; each calendar day is marked complete individually after its
partition runner succeeds.
"""

from __future__ import annotations

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
) -> OrchestratorResult:
    """Walk buckets and dates, skipping completed partitions and honoring budget."""
    resolved_buckets = _ordered_buckets(buckets)
    governor = budget or begin_run()
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)

    skipped = 0
    completed = 0
    stopped_reason: StoppedReason = "complete"

    for bucket in resolved_buckets:
        for partition_date in _iter_dates(start_date, end_date):
            if await partitions_repo.is_complete(shop_id, bucket, partition_date):
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
                continue

            if governor.should_stop():
                stopped_reason = "budget"
                governor.finish("budget")
                logger.info(
                    "analytics_backfill_orchestrator_stopped",
                    extra=_structured_log_fields(
                        shop_id=shop_id,
                        bucket=bucket,
                        partition_date=partition_date,
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

            await run_partition(bucket, partition_date)
            completed += 1
            logger.info(
                "analytics_backfill_partition_completed",
                extra=_structured_log_fields(
                    shop_id=shop_id,
                    bucket=bucket,
                    partition_date=partition_date,
                    budget=governor,
                    skipped=skipped,
                    completed=completed,
                ),
            )

            if governor.should_stop():
                stopped_reason = "budget"
                governor.finish("budget")
                logger.info(
                    "analytics_backfill_orchestrator_stopped",
                    extra=_structured_log_fields(
                        shop_id=shop_id,
                        bucket=bucket,
                        partition_date=partition_date,
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
