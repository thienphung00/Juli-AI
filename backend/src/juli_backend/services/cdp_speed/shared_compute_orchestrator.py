"""Shared Compute Orchestrator — bronze → silver → gold for material triggers (#627)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
    Order,
    Return,
)
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import BronzeAppendTracker
from juli_backend.services.cdp_speed.targeted_fetch_executor import (
    TargetedFetchExecutor,
    execute_targeted_fetch_to_bronze,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import TargetedFetchPlan
from juli_backend.services.etl.transform import (
    bronze_order_to_upsert_kwargs,
    bronze_return_to_upsert_kwargs,
)
from juli_backend.services.gold_kpi_envelope_serving import write_demo_main_kpis_envelope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SharedComputeJob:
    """One shop-scoped Shared Compute run (ADR-046 Q4)."""

    shop_id: uuid.UUID
    shop_key: str
    enqueue_reason: str
    fetch_plan: TargetedFetchPlan
    idempotency_key: str
    event_type: str | None = None


@dataclass(frozen=True, slots=True)
class SharedComputeResult:
    """Stage counters for observability and tests."""

    bronze_appended: int
    silver_promoted: int
    gold_written: bool


BronzeStageFn = Callable[
    [AsyncSession, SharedComputeJob],
    Awaitable[BronzeAppendTracker],
]
SilverStageFn = Callable[
    [AsyncSession, uuid.UUID, BronzeAppendTracker],
    Awaitable[int],
]
GoldStageFn = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]


async def _batch_promote_silver_rows(
    session: AsyncSession,
    shop_id: uuid.UUID,
    bronze_rows: Sequence[Any],
    model_class: type,
    lookup_field: str,
    lookup_dict: dict,
    transform_fn: Callable,
    related_lookup_dict: dict | None = None,
) -> int:
    """Batch promote bronze rows to silver with stale-write guard.

    Extracts the common pattern from order and return promotion:
    - Loops through bronze rows
    - Looks up existing row in pre-loaded dict
    - Applies stale-write guard: skip if incoming update_time <= existing
    - Updates or creates row
    - Flushes all changes once

    CRITICAL: The stale-write guard MUST survive any refactoring. It prevents
    out-of-order webhook deliveries from corrupting data by moving update_time
    backward. See test_stale_order_write_guard_prevents_backward_update_time.

    Args:
        session: SQLAlchemy async session
        shop_id: Shop UUID for new row creation
        bronze_rows: List of bronze domain objects to promote
        model_class: Silver domain model class (Order or Return)
        lookup_field: Field name for upsert lookup (e.g. 'tiktok_order_id')
        lookup_dict: Pre-loaded dict of existing rows by lookup_field
        transform_fn: Function to transform bronze payload to kwargs
        related_lookup_dict: For returns, pre-loaded order lookup by tiktok_order_id

    Returns:
        Number of rows promoted (both updated and newly created)
    """
    promoted = 0

    for bronze_row in bronze_rows:
        if not isinstance(bronze_row.payload, dict):
            continue
        received_at = bronze_row.received_at
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        kwargs = transform_fn(bronze_row.payload, received_at=received_at)

        # Look up existing row (already batch-loaded)
        lookup_id = kwargs.get(lookup_field)
        existing = lookup_dict.get(lookup_id) if lookup_id else None

        if existing is not None:
            # CRITICAL: Stale-write guard prevents out-of-order writes from
            # corrupting data. Skip update if incoming update_time is not newer.
            incoming_ut = kwargs.get("update_time")
            if (
                incoming_ut is not None
                and getattr(existing, "update_time", None) is not None
                and incoming_ut <= existing.update_time
            ):
                # Stale write: keep existing unchanged
                promoted += 1
                continue
            # Update existing row
            for key, value in kwargs.items():
                setattr(existing, key, value)
        else:
            # Create new row
            if related_lookup_dict and "order_id" not in kwargs:
                # For returns, look up related order if needed
                related_order = related_lookup_dict.get(kwargs.get("tiktok_order_id"))
                if related_order:
                    kwargs["order_id"] = related_order.id
            row = model_class(id=uuid.uuid4(), shop_id=bronze_row.shop_id, **kwargs)
            session.add(row)

        promoted += 1

    # Flush all changes at once
    await session.flush()
    return promoted


class SharedComputeOrchestrator:
    """Runs medallion stages in order for one material trigger."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        fetch_executor: TargetedFetchExecutor | None = None,
        bronze_stage: BronzeStageFn | None = None,
        silver_stage: SilverStageFn | None = None,
        gold_stage: GoldStageFn | None = None,
    ) -> None:
        self._session = session
        self._fetch_executor = fetch_executor or execute_targeted_fetch_to_bronze
        self._bronze_stage = bronze_stage or self._default_bronze_stage
        self._silver_stage = silver_stage or self._default_silver_stage
        self._gold_stage = gold_stage or self._default_gold_stage

    async def run(self, job: SharedComputeJob) -> SharedComputeResult:
        """Run medallion stages (bronze → silver → gold) with per-stage commits.

        Per-stage commit semantics (issue #790):
        - After bronze stage: raw payloads committed
        - After silver stage: normalized domain tables committed
        - After gold stage: KPI envelopes committed

        If a stage fails, earlier-stage writes remain durable. Gold failures
        (e.g., KPI envelope write fails) do not discard bronze and silver
        progress. The next hourly run will recompute gold from the committed
        silver rows, allowing graceful self-healing.

        This staged approach bounds session memory growth (no accumulation of
        N rows across stages) and provides partial durability on cascading
        failures, while maintaining transactional safety via the job's
        idempotency key for deduplication.
        """
        correlation_id = job_correlation_token(job.shop_id, job.idempotency_key)
        logger.info(
            "shared_compute_job_started",
            extra={
                "correlation_id": correlation_id,
                "enqueue_reason": job.enqueue_reason,
                "fetch_plan_size": len(job.fetch_plan.resources),
            },
        )

        # Bronze stage: fetch and append raw payloads
        bronze_tracker = await self._bronze_stage(self._session, job)

        # Commit after bronze stage to bound session growth and give partial durability
        await self._session.commit()

        # Silver stage: promote bronze to normalized domain tables
        silver_promoted = await self._silver_stage(
            self._session,
            job.shop_id,
            bronze_tracker,
        )

        # Commit after silver stage for durability and to clear accumulated objects
        await self._session.commit()

        # Gold stage: compute and write KPI envelope
        gold_written = await self._gold_stage(self._session, job.shop_id)

        # Commit after gold stage for durability
        await self._session.commit()

        logger.info(
            "shared_compute_job_completed",
            extra={
                "correlation_id": correlation_id,
                "enqueue_reason": job.enqueue_reason,
                "fetch_plan_size": len(job.fetch_plan.resources),
                "bronze_appended": bronze_tracker.appended_count,
                "silver_promoted": silver_promoted,
                "gold_written": gold_written,
            },
        )

        return SharedComputeResult(
            bronze_appended=bronze_tracker.appended_count,
            silver_promoted=silver_promoted,
            gold_written=gold_written,
        )

    async def _default_bronze_stage(
        self,
        session: AsyncSession,
        job: SharedComputeJob,
    ) -> BronzeAppendTracker:
        return await self._fetch_executor(
            session,
            shop_id=job.shop_id,
            shop_key=job.shop_key,
            fetch_plan=job.fetch_plan,
            idempotency_key=job.idempotency_key,
        )

    @staticmethod
    async def _default_silver_stage(
        session: AsyncSession,
        shop_id: uuid.UUID,
        bronze_tracker: BronzeAppendTracker,
    ) -> int:
        """Promote bronze to silver using batched upserts with stale-write guard.

        Uses the shared _batch_promote_silver_rows helper for both orders and
        returns to prevent logic drift and ensure the stale-write guard survives.
        """
        if bronze_tracker.appended_count <= 0:
            return 0

        promoted = 0

        # Batch order promotion
        if bronze_tracker.order_row_ids:
            # Load all bronze order rows (one query)
            order_rows = (
                (
                    await session.execute(
                        select(BronzeOrderRawPayload).where(
                            BronzeOrderRawPayload.shop_id == shop_id,
                            BronzeOrderRawPayload.id.in_(bronze_tracker.order_row_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )

            # Extract tiktok_order_ids to batch-load existing orders
            tiktok_order_ids = set()
            for bronze_row in order_rows:
                if isinstance(bronze_row.payload, dict):
                    tiktok_id = bronze_row.payload.get("order_id")
                    if tiktok_id:
                        tiktok_order_ids.add(tiktok_id)

            # Batch load all existing orders
            existing_orders_result = await session.execute(
                select(Order).where(
                    Order.shop_id == shop_id,
                    Order.tiktok_order_id.in_(tiktok_order_ids),
                )
            )
            existing_orders_by_id = {
                order.tiktok_order_id: order for order in existing_orders_result.scalars()
            }

            # Use shared helper to promote orders with stale-write guard
            promoted += await _batch_promote_silver_rows(
                session=session,
                shop_id=shop_id,
                bronze_rows=order_rows,
                model_class=Order,
                lookup_field="tiktok_order_id",
                lookup_dict=existing_orders_by_id,
                transform_fn=bronze_order_to_upsert_kwargs,
            )

        # Batch return promotion
        if bronze_tracker.return_row_ids:
            # Load all bronze return rows (one query)
            return_rows = (
                (
                    await session.execute(
                        select(BronzeReturnRawPayload).where(
                            BronzeReturnRawPayload.shop_id == shop_id,
                            BronzeReturnRawPayload.id.in_(bronze_tracker.return_row_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )

            # Extract IDs for batch loading
            tiktok_return_ids = set()
            tiktok_order_ids_for_returns = set()
            for bronze_return_row in return_rows:
                if isinstance(bronze_return_row.payload, dict):
                    if tiktok_return_id := bronze_return_row.payload.get("return_id"):
                        tiktok_return_ids.add(tiktok_return_id)
                    if tiktok_order_id := bronze_return_row.payload.get("order_id"):
                        tiktok_order_ids_for_returns.add(tiktok_order_id)

            # Batch load existing returns and related orders
            existing_returns_result = await session.execute(
                select(Return).where(
                    Return.shop_id == shop_id,
                    Return.tiktok_return_id.in_(tiktok_return_ids),
                )
            )
            existing_returns_by_id = {
                ret.tiktok_return_id: ret for ret in existing_returns_result.scalars()
            }

            existing_orders_result = await session.execute(
                select(Order).where(
                    Order.shop_id == shop_id,
                    Order.tiktok_order_id.in_(tiktok_order_ids_for_returns),
                )
            )
            existing_orders_by_tiktok_id = {
                order.tiktok_order_id: order for order in existing_orders_result.scalars()
            }

            # Use shared helper to promote returns with stale-write guard
            promoted += await _batch_promote_silver_rows(
                session=session,
                shop_id=shop_id,
                bronze_rows=return_rows,
                model_class=Return,
                lookup_field="tiktok_return_id",
                lookup_dict=existing_returns_by_id,
                transform_fn=bronze_return_to_upsert_kwargs,
                related_lookup_dict=existing_orders_by_tiktok_id,
            )

        return promoted

    @staticmethod
    async def _default_gold_stage(session: AsyncSession, shop_id: uuid.UUID) -> bool:
        await write_demo_main_kpis_envelope(session, shop_id)
        return True


async def run_shared_compute_job(
    session: AsyncSession,
    job: SharedComputeJob,
    *,
    orchestrator: SharedComputeOrchestrator | None = None,
    fetch_executor: TargetedFetchExecutor | None = None,
) -> SharedComputeResult:
    """Convenience entry for one shop-scoped Shared Compute job."""
    if orchestrator is not None:
        runner = orchestrator
    else:
        runner = SharedComputeOrchestrator(session, fetch_executor=fetch_executor)
    return await runner.run(job)
