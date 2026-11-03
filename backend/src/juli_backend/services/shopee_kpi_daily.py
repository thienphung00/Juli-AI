"""The daily Shopee KPI run across the fleet (ADR-117 step 3; the beat's body).

Every day, for each Shopee shop with a current KPI contract (newest version not
``superseded``), run :func:`~juli_backend.services.shopee_kpi.run_shop_kpi` and store
its ``kpi_forecasts`` -- unless nothing changed. Seller exports arrive weekly, so on
most days nothing changed and a new run would only duplicate its rows: that shop is
skipped. Two checks, cheapest first:

- :func:`landed_since_last_run` -- one ``max()`` per input table against the newest
  stored run's ``run_at``: has an ingest (``platform_daily_metrics.updated_at``, bumped
  by every upsert) or an Ops edit (contract, targets, adjustments, base lever plan)
  landed since? No -> skip without reading the series. This keeps the daily read to a
  few index lookups (Supabase egress). ``kpi_exclusions`` has no timestamp and no writer
  yet; a writer must touch ``kpi_contracts.updated_at`` or the beat will not see it.
- :func:`inputs_unchanged` -- only when something landed: load the inputs and compare
  ``inputs_sha256`` with the newest stored run (a re-upload of identical rows bumps
  ``updated_at`` but changes nothing).

A module of its own at ``services/`` depth 2 so the worker task reaches it without a
deep import into ``services.shopee_kpi``; the job module is untouched.

Each shop runs in its own session and transaction: a refusal (no contract / metrics /
measure start, bad terms) or any unexpected error is counted and logged and never
stops the rest. Logs carry counts and shop ids only -- never metric values (client
data).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.kpi_contracts import (
    CONTRACT_SUPERSEDED,
    KpiAdjustment,
    KpiContract,
    KpiForecast,
    KpiTarget,
    LeverPlan,
)
from juli_backend.services.ops import ops_role
from juli_backend.services.ops.overview import list_shops
from juli_backend.services.shopee_kpi import job
from juli_backend.services.shopee_kpi.rules import ContractTermsError

logger = logging.getLogger(__name__)

SHOPEE = "shopee"

#: Refusals the job raises by design: counted, not failures.
REFUSALS = (
    job.NoKpiContract,
    job.NoMetrics,
    job.MeasureStartMissing,
    ContractTermsError,
)

SessionFactory = Callable[[], Any]


@dataclass(frozen=True)
class DailyKpiSummary:
    """Per-run counts, logged by the beat (counts only)."""

    scanned: int
    ran: int
    skipped_nothing_landed: int
    skipped_unchanged: int
    refused: int
    failed: int


async def contract_shop_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Shopee shops that have a current contract version, in a stable order."""
    shopee = {s.shop_id for s in await list_shops(session) if s.platform == SHOPEE}
    async with ops_role(session):
        with_contract = (
            (
                await session.execute(
                    select(KpiContract.shop_id)
                    .where(KpiContract.status != CONTRACT_SUPERSEDED)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
    return sorted(shopee.intersection(with_contract), key=str)


async def landed_since_last_run(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    """True when an input row was written after the shop's newest stored base run for its
    current contract, or when there is no such run. Index lookups only, no series read.

    Raises :class:`job.NoKpiContract` (a refusal); the caller counts it.
    """
    contract = await job.current_contract(session, shop_id)
    async with ops_role(session):
        last_run = (
            await session.execute(
                select(func.max(KpiForecast.run_at)).where(
                    KpiForecast.shop_id == shop_id,
                    KpiForecast.contract_id == contract.id,
                    KpiForecast.scenario_id.is_(None),
                )
            )
        ).scalar_one()
        if last_run is None:
            return True
        versions = select(KpiContract.id).where(
            KpiContract.shop_id == shop_id, KpiContract.contract_ref == contract.contract_ref
        )
        ops_marks = [
            select(func.max(KpiContract.updated_at)).where(KpiContract.id == contract.id),
            select(func.max(KpiTarget.created_at)).where(KpiTarget.contract_id == contract.id),
            select(func.max(KpiAdjustment.created_at)).where(
                KpiAdjustment.contract_id.in_(versions)
            ),
            select(func.max(LeverPlan.updated_at)).where(
                LeverPlan.shop_id == shop_id, LeverPlan.scenario_id.is_(None)
            ),
        ]
        marks = [(await session.execute(q)).scalar_one() for q in ops_marks]
    m = PlatformDailyMetric
    sources = job.FLOW_SOURCES.values()
    async with with_shop_scope(session, shop_id):
        marks.append(
            (
                await session.execute(
                    select(func.max(m.updated_at)).where(
                        m.shop_id == shop_id,
                        m.platform == job.PLATFORM,
                        m.order_type == job.ORDER_TYPE,
                        m.item_id == job.SHOP_LEVEL_ITEM,
                        m.dataset.in_({s.dataset for s in sources}),
                        m.stream.in_({s.stream for s in sources}),
                        m.segment.in_({s.segment for s in sources}),
                    )
                )
            ).scalar_one()
        )
    return any(mark is not None and mark > last_run for mark in marks)


async def inputs_unchanged(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    """True when the shop's newest stored run for its current contract has the same
    ``inputs_sha256`` a run now would produce.

    Raises what :func:`job.load_inputs` raises (a refusal); the caller counts it.
    """
    inputs = await job.load_inputs(session, shop_id)
    sha = job.inputs_sha256(inputs, inputs.default_as_of())
    async with ops_role(session):
        stored = (
            await session.execute(
                select(KpiForecast.inputs_sha256)
                .where(
                    KpiForecast.shop_id == shop_id,
                    KpiForecast.contract_id == inputs.contract.id,
                    KpiForecast.scenario_id.is_(None),
                )
                .order_by(KpiForecast.run_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return stored == sha


async def run_daily_kpi(
    session_factory: SessionFactory, *, now: datetime | None = None
) -> DailyKpiSummary:
    """Run every contract shop in its own session; one shop never aborts the others."""
    reference = now if now is not None else datetime.now(UTC).replace(tzinfo=None)
    async with session_factory() as session:
        shop_ids = await contract_shop_ids(session)

    ran = nothing_landed = skipped = refused = failed = 0
    for shop_id in shop_ids:
        try:
            async with session_factory() as session:
                if not await landed_since_last_run(session, shop_id):
                    nothing_landed += 1
                    continue
                if await inputs_unchanged(session, shop_id):
                    skipped += 1
                    continue
                await job.run_shop_kpi(session, shop_id, now=reference)
                await session.commit()
            ran += 1
        except REFUSALS as exc:
            refused += 1
            logger.info(
                "shopee_kpi_daily_refused",
                extra={"shop_id": str(shop_id), "reason": type(exc).__name__},
            )
        except Exception as exc:
            failed += 1
            # Type only: a message can carry row values (client data).
            logger.error(
                "shopee_kpi_daily_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )

    summary = DailyKpiSummary(
        scanned=len(shop_ids),
        ran=ran,
        skipped_nothing_landed=nothing_landed,
        skipped_unchanged=skipped,
        refused=refused,
        failed=failed,
    )
    logger.info(
        "shopee_kpi_daily_complete",
        extra={
            "scanned": summary.scanned,
            "ran": summary.ran,
            "skipped_nothing_landed": summary.skipped_nothing_landed,
            "skipped_unchanged": summary.skipped_unchanged,
            "refused": summary.refused,
            "failed": summary.failed,
        },
    )
    return summary
