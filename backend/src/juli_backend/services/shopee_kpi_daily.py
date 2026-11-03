"""The daily Shopee KPI run across the fleet (ADR-117 step 3; the beat's body).

Every day, for each Shopee shop with a current KPI contract (newest version not
``superseded``), run :func:`~juli_backend.services.shopee_kpi.run_shop_kpi` and store
its ``kpi_forecasts`` -- unless nothing changed. Seller exports arrive weekly, so on
most days the inputs hash to the same ``inputs_sha256`` as the shop's newest stored
run and a new run would only duplicate its rows: that shop is skipped
(:func:`inputs_unchanged`).

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.kpi_contracts import CONTRACT_SUPERSEDED, KpiContract, KpiForecast
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

    ran = skipped = refused = failed = 0
    for shop_id in shop_ids:
        try:
            async with session_factory() as session:
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
        scanned=len(shop_ids), ran=ran, skipped_unchanged=skipped, refused=refused, failed=failed
    )
    logger.info(
        "shopee_kpi_daily_complete",
        extra={
            "scanned": summary.scanned,
            "ran": summary.ran,
            "skipped_unchanged": summary.skipped_unchanged,
            "refused": summary.refused,
            "failed": summary.failed,
        },
    )
    return summary
