"""BatchReconcileOrchestrator — shop-scoped batch reconcile entry (#621 / CDP-A2-8).

Coordinates batch reconcile through:
- Gap detection & fetch planning (BatchFetchPlanner)
- Partner API budget governance
- Postgres I/O budget governance
- Shop compute mutex (defers when speed holds lock)
- Partition-resumable bronze append (reconcile_partition_with_checkpoints)
- Shared Compute bronze→silver→gold stages

Writes same gold.kpi_envelopes serving contract as Speed path (no separate batch table).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.cdp_batch.batch_fetch_planner import (
    DEFER_REASON as GAP_NOT_DETECTED_DEFER_REASON,
)
from juli_backend.services.cdp_batch.batch_fetch_planner import (
    BatchFetchPlan,
    BatchFetchPlanner,
)
from juli_backend.services.cdp_batch.partition_checkpoints import (
    ReconcilePageFetcher,
    reconcile_partition_with_checkpoints,
)
from juli_backend.services.cdp_batch.partner_budget import (
    DEFER_REASON as PARTNER_BUDGET_DEFER_REASON,
)
from juli_backend.services.cdp_batch.partner_budget import (
    PartnerApiBudgetGovernor,
)
from juli_backend.services.cdp_batch.postgres_io_budget import (
    DEFER_REASON as POSTGRES_IO_DEFER_REASON,
)
from juli_backend.services.cdp_batch.postgres_io_budget import (
    PostgresIoBudgetGovernor,
)
from juli_backend.services.cdp_batch.shop_compute_mutex import (
    DEFER_REASON as SPEED_MUTEX_DEFER_REASON,
)
from juli_backend.services.cdp_batch.shop_compute_mutex import (
    ShopComputeMutex,
    try_begin_batch_compute,
)
from juli_backend.services.cdp_batch.stagger_scheduler import ReconcileWindow
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FetchResource,
    TargetedFetchPlan,
)

logger = logging.getLogger(__name__)


def _batch_fetch_plan_to_targeted(
    fetch_plan: BatchFetchPlan,
) -> TargetedFetchPlan:
    """Convert batch fetch plan resources to targeted fetch plan resources."""
    resources = tuple(
        FetchResource(
            name=resource.name,
            endpoint_path=resource.endpoint_path,
            resource_attr=resource.resource_attr,
        )
        for resource in fetch_plan.resources
    )
    return TargetedFetchPlan(
        catalog_id=None,  # Batch reconcile has no specific catalog_id
        shop_id=fetch_plan.shop_id,
        resources=resources,
    )


@dataclass(frozen=True, slots=True)
class BatchReconcileResult:
    """Outcome of one shop-scoped batch reconcile run."""

    acquired: bool
    deferred: bool = False
    defer_reason: str | None = None
    pages_fetched: int = 0
    bronze_rows_appended: int = 0
    silver_promoted: int = 0
    gold_written: bool = False


class BatchReconcileOrchestrator:
    """Shop-scoped batch reconcile orchestrator."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        mutex: ShopComputeMutex,
        planner: BatchFetchPlanner,
        partner_budget: PartnerApiBudgetGovernor,
        postgres_budget: PostgresIoBudgetGovernor,
    ) -> None:
        self._session = session
        self._mutex = mutex
        self._planner = planner
        self._partner_budget = partner_budget
        self._postgres_budget = postgres_budget

    async def run(
        self,
        *,
        shop_id: uuid.UUID,
        detected_gaps: frozenset[str] | set[str] | tuple[str, ...],
        fetcher: ReconcilePageFetcher,
        partition_date: date,
        reconcile_window: ReconcileWindow | None = None,
    ) -> BatchReconcileResult:
        """Run batch reconcile for one shop window: plan → fetch → bronze → silver → gold."""
        shop_id_str = str(shop_id)

        # Gate 1: Check if speed is holding the compute mutex
        compute_entry = try_begin_batch_compute(self._mutex, shop_id_str)
        if not compute_entry.acquired:
            logger.info(
                "batch_reconcile_deferred_speed_mutex_active",
                extra={
                    "shop_id": shop_id_str,
                    "defer_reason": SPEED_MUTEX_DEFER_REASON,
                },
            )
            return BatchReconcileResult(
                acquired=False,
                deferred=True,
                defer_reason=SPEED_MUTEX_DEFER_REASON,
            )

        try:
            # Gate 2: Plan fetch based on gaps
            fetch_plan = self._planner.plan(
                shop_id=shop_id_str,
                detected_gaps=detected_gaps,
                reconcile_window=reconcile_window,
                trigger_source="batch_reconcile",
            )

            if not fetch_plan.should_fetch:
                logger.info(
                    "batch_reconcile_deferred_gap_not_detected",
                    extra={
                        "shop_id": shop_id_str,
                        "defer_reason": GAP_NOT_DETECTED_DEFER_REASON,
                    },
                )
                return BatchReconcileResult(
                    acquired=True,
                    deferred=True,
                    defer_reason=GAP_NOT_DETECTED_DEFER_REASON,
                )

            # Gate 3: Run partition reconcile with checkpoints (bronze stage)
            partition_result = await reconcile_partition_with_checkpoints(
                self._session,
                shop_id=shop_id,
                bucket="catalog",
                partition_date=partition_date,
                fetcher=fetcher,
                budget=self._partner_budget,
            )

            if partition_result.deferred or partition_result.error:
                defer_reason = PARTNER_BUDGET_DEFER_REASON if partition_result.deferred else None
                return BatchReconcileResult(
                    acquired=True,
                    deferred=partition_result.deferred,
                    defer_reason=defer_reason,
                    pages_fetched=partition_result.pages_fetched,
                    bronze_rows_appended=partition_result.bronze_rows_appended,
                )

            # Gate 4: Run silver promotion via Shared Compute Orchestrator
            # Build a fetch plan that matches Shared Compute's expected format
            shared_compute_plan = _batch_fetch_plan_to_targeted(fetch_plan)

            shared_job = SharedComputeJob(
                shop_id=shop_id,
                shop_key=shop_id_str,
                enqueue_reason="batch_reconcile",
                fetch_plan=shared_compute_plan,
                idempotency_key=f"batch-reconcile:{partition_date.isoformat()}",
                event_type=None,
            )

            orchestrator = SharedComputeOrchestrator(self._session)
            compute_result = await orchestrator.run(shared_job)

            # Gate 5: Check Postgres I/O budget before silver upsert.
            # RESUMABILITY NOTE: The partition checkpoint may be marked "complete" by the
            # bronze stage (partition_checkpoints.py), indicating all pages from Partner
            # have been fetched. This is intentional — "partition complete" means "no need
            # to re-fetch from Partner," not "entire reconcile pipeline finished."
            # If postgres_io_throttled defers here, a resumed run will:
            # 1. Check is_complete() → True (bronze checkpoint exists)
            # 2. Proceed to Gate 4 (silver promotion) via the normal path
            # 3. Retry the silver_upsert that failed, picking up where it left off
            # This asymmetry (partner_budget defers before mark_complete; postgres_io defers
            # after) is correct: we only mark partition complete once bronze is durable.
            if compute_result.silver_promoted > 0:
                if not self._postgres_budget.try_silver_upsert(compute_result.silver_promoted):
                    postgres_log_fields = self._postgres_budget.finish(POSTGRES_IO_DEFER_REASON)
                    logger.info(
                        "batch_reconcile_deferred_postgres_io_throttled",
                        extra={
                            "shop_id": shop_id_str,
                            "defer_reason": POSTGRES_IO_DEFER_REASON,
                            **postgres_log_fields,
                        },
                    )
                    return BatchReconcileResult(
                        acquired=True,
                        deferred=True,
                        defer_reason=POSTGRES_IO_DEFER_REASON,
                        pages_fetched=partition_result.pages_fetched,
                        bronze_rows_appended=partition_result.bronze_rows_appended,
                        silver_promoted=compute_result.silver_promoted,
                    )

            # Success: mark budgets complete and log metrics
            partner_log_fields = self._partner_budget.finish("complete")
            postgres_log_fields = self._postgres_budget.finish("complete")
            logger.info(
                "batch_reconcile_completed",
                extra={
                    "shop_id": shop_id_str,
                    "pages_fetched": partition_result.pages_fetched,
                    "bronze_rows_appended": partition_result.bronze_rows_appended,
                    "silver_promoted": compute_result.silver_promoted,
                    "gold_written": compute_result.gold_written,
                    **partner_log_fields,
                    **postgres_log_fields,
                },
            )

            return BatchReconcileResult(
                acquired=True,
                deferred=False,
                pages_fetched=partition_result.pages_fetched,
                bronze_rows_appended=partition_result.bronze_rows_appended,
                silver_promoted=compute_result.silver_promoted,
                gold_written=compute_result.gold_written,
            )

        finally:
            # Always release the mutex on exit
            self._mutex.release(shop_id_str, "batch")
