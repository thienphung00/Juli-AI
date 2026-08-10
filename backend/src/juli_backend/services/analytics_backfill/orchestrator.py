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
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    ClientFactoryConfig,
    ProductionReadClientFactory,
    TikTokCapability,
)
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
    TikTokCredentialRepo,
)
from juli_backend.services.analytics_backfill.budget import (
    CallBudgetGovernor,
    StoppedReason,
    begin_run,
)
from juli_backend.services.analytics_backfill.catalog_partition import (
    run_catalog_partition,
)
from juli_backend.services.analytics_backfill.live_partition import (
    run_live_partition,
)
from juli_backend.services.analytics_backfill.product_partition import (
    backfill_product_partition,
)
from juli_backend.services.analytics_backfill.revenue_partition import (
    backfill_revenue_partition,
)

logger = logging.getLogger(__name__)

BACKFILL_WINDOW_START = date(2026, 3, 16)
DEFAULT_BUCKET_ORDER: tuple[str, ...] = ("revenue", "live", "product", "catalog")
ALLOWED_BUCKETS = frozenset(DEFAULT_BUCKET_ORDER)

# Buckets/endpoints excluded from Phase 2.9 backfill (Ads, A-26, A-27, A-33).
FORBIDDEN_BUCKETS = frozenset({"ads", "advertising", "a26", "a27", "a33"})

# Conservative default for the production scheduled top-up caller (issue #795).
# The actual Partner call RATE is governed by the Redis-backed token-bucket
# RateLimiter (integrations/tiktok/rate_limiter.py) per shop+endpoint, not by
# this value — this only bounds how many partitions may be *in flight*
# fetching at once. ADR-029's hard_limit=499 total attempts per run is also
# unaffected: more in-flight tasks make the same capped set of calls finish
# sooner, not more calls happen. Kept small because each in-flight partition
# holds a thread-pool worker (asyncio.to_thread) for the duration of its
# blocking Partner HTTP call.
DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT = 4
_CONCURRENCY_LIMIT_ENV_VAR = "ANALYTICS_BACKFILL_CONCURRENCY_LIMIT"

PartitionRunner = Callable[[str, date], Awaitable[None]]


def _resolve_concurrency_limit() -> int:
    """Read the production concurrency limit from config, with a safe fallback."""
    raw = os.getenv(_CONCURRENCY_LIMIT_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "analytics_backfill_invalid_concurrency_limit",
            extra={"raw_value": raw, "fallback": DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT},
        )
        return DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT
    if value < 1:
        logger.warning(
            "analytics_backfill_invalid_concurrency_limit",
            extra={"raw_value": raw, "fallback": DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT},
        )
        return DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT
    return value


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
        concurrency_limit: Maximum concurrent partitions. Default 1 (safe for
            any injected ``run_partition`` — this function cannot know
            whether an arbitrary caller's closure is safe to run
            concurrently, e.g. whether it shares one AsyncSession). Real
            partition runners now offload their blocking Partner fetch
            calls via ``asyncio.to_thread`` and accept a ``session_lock`` to
            serialize their DB touches (issue #795), which is what makes
            raising this above 1 actually produce overlap instead of the
            inert #791 scaffolding. See ``backfill_analytics_history_auto_topup``
            for the production wiring that raises this via config.

    Optimizations (issue #791):
    - Bulk-load completed partitions once per bucket
    - Run partitions concurrently under a bounded limit

    Optimizations (issue #795):
    - Real concurrency: partition fetch calls genuinely overlap in wall time
    - Respect ADR-029 hard_limit (499) even under concurrency via budget_lock
    - No AsyncSession is ever touched by two concurrent partition tasks
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


def _partner_env_ready() -> dict[str, str] | None:
    """Partner app credentials from environment, or None when unconfigured."""
    values = {
        "app_key": os.getenv("TIKTOK_APP_KEY", "").strip(),
        "app_secret": os.getenv("TIKTOK_APP_SECRET", "").strip(),
    }
    if not all(values.values()):
        return None
    return values


def _empty_result(shop_id: uuid.UUID, start_date: date, end_date: date) -> OrchestratorResult:
    """Result for a run that did no work because prerequisites were absent."""
    return OrchestratorResult(
        stopped_reason="complete",
        skipped_partitions=0,
        completed_partitions=0,
        budget_fields={},
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
        buckets=(),
    )


async def backfill_analytics_history_auto_topup(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    start_date: date = BACKFILL_WINDOW_START,
    end_date: date,
    concurrency_limit: int | None = None,
) -> OrchestratorResult:
    """Automatically top up analytics history for a shop (service-layer wrapper).

    Owned by services.analytics_backfill per ADR-046 one-writer model. Dispatches
    each bucket to its real partition runner which owns its own persistence
    (mark_complete only after successful data fetch + upsert).

    Args:
        session: Database session
        shop_id: Shop to backfill
        start_date: Inclusive start date
        end_date: Inclusive end date
        concurrency_limit: Maximum partitions fetching concurrently. Defaults
            to config (``ANALYTICS_BACKFILL_CONCURRENCY_LIMIT`` env var, else
            ``DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT``). All four real partition
            runners accept a shared ``session_lock`` (created below) so their
            DB touches stay serialized on this single AsyncSession even
            though their Partner fetch calls genuinely overlap (issue #795).

    Returns:
        OrchestratorResult with skipped/completed partition counts
    """
    # app_key/app_secret are environment config, not credential columns. Skip rather
    # than raise when unconfigured: this runs unattended on Beat, and a missing env var
    # is an operator state, not a task failure.
    env = _partner_env_ready()
    if env is None:
        logger.info(
            "analytics_backfill_auto_topup_skipped",
            extra={"shop_id": str(shop_id), "reason": "missing_tiktok_env"},
        )
        return _empty_result(shop_id, start_date, end_date)

    # Shop-scoped production-read credential. Use the repo, not session.get: the
    # primary key is `id`, so session.get(TikTokCredential, shop_id) never resolves.
    try:
        credential = await TikTokCredentialRepo(session).get_by_shop_and_capability(
            shop_id,
            TikTokCapability.PRODUCTION_READ,
        )
    except NotFound:
        logger.info(
            "analytics_backfill_auto_topup_skipped",
            extra={"shop_id": str(shop_id), "reason": "missing_production_read_credential"},
        )
        return _empty_result(shop_id, start_date, end_date)

    # Build through the factory so the read-only transport guard applies. An unattended
    # scheduled job is the last place that guard should be bypassed.
    resources = ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key=env["app_key"],
            app_secret=env["app_secret"],
            access_token=credential.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=credential.shop_cipher,
        )
    )
    analytics_resource = resources.analytics
    products_resource = resources.products

    # Create repos for partition state and analytics data persistence
    partitions_repo = AnalyticsBackfillPartitionsRepo(session)
    performance_repo = AnalyticsPerformanceRepo(session)

    # Begin budget tracking for this run
    budget = begin_run()

    synced_at = int(time.time())

    # Guards every DB touch made by concurrently-running partition tasks below
    # (issue #795). All four real partition runners share this ONE lock because
    # they all share this ONE AsyncSession — the session itself is never safe
    # for concurrent use, so serializing access to it (not to the network
    # fetches, which run via asyncio.to_thread) is what makes concurrency_limit
    # > 1 safe here.
    session_lock = asyncio.Lock()

    # Dispatch by bucket to real partition runners
    async def partition_runner(bucket: str, partition_date: date) -> None:
        """Dispatch to bucket-specific runner that owns its own persistence."""
        if bucket == "revenue":
            await backfill_revenue_partition(
                shop_id=shop_id,
                partition_date=partition_date,
                analytics_resource=analytics_resource,
                partitions_repo=partitions_repo,
                performance_repo=performance_repo,
                budget=budget,
                synced_at=synced_at,
                session_lock=session_lock,
            )
        elif bucket == "live":
            await run_live_partition(
                shop_id=shop_id,
                partition_date=partition_date,
                analytics=analytics_resource,
                budget=budget,
                partitions_repo=partitions_repo,
                performance_repo=performance_repo,
                synced_at=synced_at,
                session_lock=session_lock,
            )
        elif bucket == "product":
            await backfill_product_partition(
                session,
                shop_id=shop_id,
                partition_date=partition_date,
                resource=analytics_resource,
                budget=budget,
                synced_at=synced_at,
                session_lock=session_lock,
            )
        elif bucket == "catalog":
            await run_catalog_partition(
                session=session,
                shop_id=shop_id,
                partition_date=partition_date,
                products=products_resource,
                budget=budget,
                session_lock=session_lock,
            )
        else:
            msg = f"Unknown bucket: {bucket}"
            raise ValueError(msg)

    resolved_concurrency_limit = (
        concurrency_limit if concurrency_limit is not None else _resolve_concurrency_limit()
    )

    return await backfill_analytics_history(
        session,
        shop_id=shop_id,
        start_date=start_date,
        end_date=end_date,
        budget=budget,
        concurrency_limit=resolved_concurrency_limit,
        run_partition=partition_runner,
    )
