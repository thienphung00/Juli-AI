"""Shared Compute Orchestrator — bronze → silver → gold for material triggers (#627)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import BronzeOrderRawPayload, BronzeReturnRawPayload
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import BronzeAppendTracker
from juli_backend.services.cdp_speed.targeted_fetch_executor import (
    TargetedFetchExecutor,
    execute_targeted_fetch_to_bronze,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import TargetedFetchPlan
from juli_backend.services.etl.silver_promotion import SilverOrdersReturnsPromoter
from juli_backend.services.gold_kpi_envelope_serving import compute_demo_main_kpis_payload

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

        bronze_tracker = await self._bronze_stage(self._session, job)
        silver_promoted = await self._silver_stage(
            self._session,
            job.shop_id,
            bronze_tracker,
        )
        gold_written = await self._gold_stage(self._session, job.shop_id)

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

        promoter = SilverOrdersReturnsPromoter(session)
        promoted = 0

        if bronze_tracker.order_row_ids:
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
            for order_row in rows:
                await promoter.promote_order(order_row)
                promoted += 1

        if bronze_tracker.return_row_ids:
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
            for return_row in return_rows:
                await promoter.promote_return(return_row)
                promoted += 1

        return promoted

    @staticmethod
    async def _default_gold_stage(session: AsyncSession, shop_id: uuid.UUID) -> bool:
        from juli_backend.repositories.repos import GoldKpiEnvelopesRepo
        from juli_backend.services.gold_kpi_envelope_contract import ENVELOPE_VERSION

        # Compute the five Demo Main KPIs from silver orders
        payload = await compute_demo_main_kpis_payload(session, shop_id)
        computed_at = datetime.now(tz=UTC)

        repo = GoldKpiEnvelopesRepo(session)
        await repo.upsert(
            shop_id=shop_id,
            envelope_version=ENVELOPE_VERSION,
            payload=payload,
            computed_at=computed_at,
        )
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
