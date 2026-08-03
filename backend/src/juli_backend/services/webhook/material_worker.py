"""Material webhook worker: Shared Compute orchestrator for material triggers (#627)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import ShopsRepo
from juli_backend.services.cdp_speed import (
    SharedComputeJob,
    SharedComputeResult,
    TargetedFetchExecutor,
    job_correlation_token,
    plan_targeted_fetch,
    run_shared_compute_job,
)
from juli_backend.services.tiktok.webhook_catalog import catalog_id_for_event
from juli_backend.services.webhook.material_gate import MaterialEnqueueGate

logger = logging.getLogger(__name__)

ComputeHook = Callable[[AsyncSession, SharedComputeJob], Awaitable[SharedComputeResult]]


async def _default_shared_compute(
    session: AsyncSession,
    job: SharedComputeJob,
    *,
    fetch_executor: TargetedFetchExecutor | None = None,
) -> SharedComputeResult:
    return await run_shared_compute_job(session, job, fetch_executor=fetch_executor)


async def run_material_analytics_compute(
    session: AsyncSession,
    *,
    shop_key: str,
    enqueue_reason: str,
    event_type: str | None = None,
    idempotency_key: str,
    gate: MaterialEnqueueGate | None = None,
    compute_hook: ComputeHook | None = None,
    fetch_executor: TargetedFetchExecutor | None = None,
) -> SharedComputeResult | None:
    """Run Shared Compute (bronze→silver→gold) for a TikTok shop key."""
    shop = await ShopsRepo(session).get_by_tiktok_id(shop_key)
    if shop is None:
        logger.warning(
            "material_analytics_unknown_shop",
            extra={
                "correlation_id": job_correlation_token(
                    uuid.UUID(int=0),
                    f"unknown:{idempotency_key}",
                ),
            },
        )
        return None

    fetch_plan = plan_targeted_fetch(
        shop_id=shop_key,
        event_type=event_type,
        catalog_id=catalog_id_for_event(event_type) if event_type else None,
    )
    job = SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop_key,
        enqueue_reason=enqueue_reason,
        fetch_plan=fetch_plan,
        idempotency_key=idempotency_key,
        event_type=event_type,
    )

    try:
        if compute_hook is not None:
            result = await compute_hook(session, job)
        else:
            result = await _default_shared_compute(
                session,
                job,
                fetch_executor=fetch_executor,
            )
        await session.commit()
        return result
    finally:
        if gate is not None:
            gate.release(shop_key)
