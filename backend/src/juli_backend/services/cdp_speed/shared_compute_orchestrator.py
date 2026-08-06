"""Shared Compute Orchestrator — bronze → silver → gold for material triggers (#627)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
        if bronze_tracker.appended_count <= 0:
            return 0

        promoted = 0

        # Batch order promotion: load all existing orders once, then upsert
        if bronze_tracker.order_row_ids:
            # Load all bronze order rows (one query)
            rows = (
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

            # Extract all tiktok_order_ids to batch-load existing records
            tiktok_order_ids = set()
            for bronze_row in rows:
                if isinstance(bronze_row.payload, dict):
                    tiktok_id = bronze_row.payload.get("order_id")
                    if tiktok_id:
                        tiktok_order_ids.add(tiktok_id)

            # Batch load all existing orders (one query instead of N)
            existing_orders_stmt = select(Order).where(
                Order.shop_id == shop_id,
                Order.tiktok_order_id.in_(tiktok_order_ids),
            )
            existing_orders_result = await session.execute(existing_orders_stmt)
            existing_orders_by_id = {
                order.tiktok_order_id: order for order in existing_orders_result.scalars()
            }

            # Now upsert each row without additional SELECT per row
            from juli_backend.services.etl.transform import (
                bronze_order_to_upsert_kwargs,
            )

            for bronze_row in rows:
                if not isinstance(bronze_row.payload, dict):
                    continue
                received_at = bronze_row.received_at
                if received_at.tzinfo is None:
                    from datetime import UTC

                    received_at = received_at.replace(tzinfo=UTC)
                kwargs = bronze_order_to_upsert_kwargs(bronze_row.payload, received_at=received_at)

                # Look up existing order (already loaded) instead of querying per row
                existing = existing_orders_by_id.get(kwargs["tiktok_order_id"])
                if existing is not None:
                    # Update existing order
                    for key, value in kwargs.items():
                        setattr(existing, key, value)
                else:
                    # Create new order
                    order = Order(id=uuid.uuid4(), shop_id=bronze_row.shop_id, **kwargs)
                    session.add(order)

                promoted += 1

            # Flush all order upserts at once
            await session.flush()

        # Batch return promotion: same pattern as orders
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

            # Extract all tiktok_order_ids for batch lookup of related orders
            tiktok_return_ids = set()
            tiktok_order_ids_for_returns = set()
            for bronze_row in return_rows:
                if isinstance(bronze_row.payload, dict):
                    tiktok_return_id = bronze_row.payload.get("return_id")
                    tiktok_order_id = bronze_row.payload.get("order_id")
                    if tiktok_return_id:
                        tiktok_return_ids.add(tiktok_return_id)
                    if tiktok_order_id:
                        tiktok_order_ids_for_returns.add(tiktok_order_id)

            # Batch load existing returns and related orders (two queries total)
            existing_returns_stmt = select(Return).where(
                Return.shop_id == shop_id,
                Return.tiktok_return_id.in_(tiktok_return_ids),
            )
            existing_returns_result = await session.execute(existing_returns_stmt)
            existing_returns_by_id = {
                ret.tiktok_return_id: ret for ret in existing_returns_result.scalars()
            }

            existing_orders_stmt = select(Order).where(
                Order.shop_id == shop_id,
                Order.tiktok_order_id.in_(tiktok_order_ids_for_returns),
            )
            existing_orders_result = await session.execute(existing_orders_stmt)
            existing_orders_by_tiktok_id = {
                order.tiktok_order_id: order for order in existing_orders_result.scalars()
            }

            # Now upsert each return row without additional SELECT per row
            from juli_backend.services.etl.transform import (
                bronze_return_to_upsert_kwargs,
            )

            for bronze_row in return_rows:
                if not isinstance(bronze_row.payload, dict):
                    continue
                received_at = bronze_row.received_at
                if received_at.tzinfo is None:
                    from datetime import UTC

                    received_at = received_at.replace(tzinfo=UTC)
                kwargs = bronze_return_to_upsert_kwargs(bronze_row.payload, received_at=received_at)

                # Look up existing return (already loaded) instead of querying per row
                existing_return = existing_returns_by_id.get(kwargs.get("tiktok_return_id"))

                # Look up related order (already batch-loaded)
                related_order = existing_orders_by_tiktok_id.get(kwargs.get("tiktok_order_id"))
                if related_order is not None:
                    kwargs["order_id"] = related_order.id

                if existing_return is not None:
                    # Update existing return
                    for key, value in kwargs.items():
                        setattr(existing_return, key, value)
                else:
                    # Create new return
                    ret = Return(id=uuid.uuid4(), shop_id=bronze_row.shop_id, **kwargs)
                    session.add(ret)

                promoted += 1

            # Flush all return upserts at once
            await session.flush()

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
