"""Hourly Mock-mode Analytics reconciliation for the Demo reference shop (#533).

Phase 2.10 Mock-mode reconciliation only (ADR-038 §5): Celery Beat runs once per
hour and recomputes Analytics KPI envelopes for ``DEMO_REFERENCE_SHOP_ID`` only.
This is not global daily scoring and must not fan out to all shops.

Issue #632: Route through SharedComputeOrchestrator with reconcile_hourly enqueue_reason
and a bounded gap-targeted fetch plan, with quota guards applied.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop
from juli_backend.services.cdp_speed import (
    FetchResource,
    SharedComputeJob,
    TargetedFetchPlan,
    is_quota_guarded,
    run_shared_compute_job,
)
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url
from juli_backend.workers.tasks.material_analytics_precompute import (
    material_analytics_precompute_sync,
)

logger = logging.getLogger(__name__)


def get_demo_reference_shop_id() -> uuid.UUID | None:
    """Return configured Demo reference shop id, if set."""
    raw = os.getenv("DEMO_REFERENCE_SHOP_ID", "").strip()
    if not raw:
        return None
    return uuid.UUID(raw)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory():
    from sqlalchemy.ext.asyncio import create_async_engine

    from juli_backend.database.database import create_session_factory, init_session_factory

    engine = create_async_engine(_database_url())
    factory = create_session_factory(engine)
    init_session_factory(factory)
    return factory


async def _lookup_tiktok_shop_key_async(shop_id: uuid.UUID) -> str | None:
    factory = _ensure_session_factory()
    async with factory() as session:
        shop = await session.get(Shop, shop_id)
        if shop is None or not shop.tiktok_shop_id:
            logger.warning(
                "mock_analytics_reconcile_unknown_shop",
                extra={"shop_id": str(shop_id)},
            )
            return None
        return shop.tiktok_shop_id


def _lookup_tiktok_shop_key(shop_id: uuid.UUID) -> str | None:
    return asyncio.run(_lookup_tiktok_shop_key_async(shop_id))


def _make_hourly_gap_fetch_plan(shop_key: str) -> TargetedFetchPlan:
    """Create a bounded gap-targeted fetch plan for hourly reconciliation.

    Not the material matrix — just orders and analytics_shop for hourly reconciliation,
    with quota guards applied (#632).
    """
    # Bounded resources: orders and analytics_shop for hourly reconciliation
    base_resources: list[FetchResource] = [
        FetchResource("orders", "/orders/202309/list", "orders"),
        FetchResource("analytics_shop", "/analytics/202309/shop", "analytics"),
    ]

    # Filter out any quota-guarded resources (A-38/A-39/A-31/A-33)
    filtered_resources = tuple(r for r in base_resources if not is_quota_guarded(r.name))

    return TargetedFetchPlan(
        catalog_id=None,  # Gap plan, not material matrix
        shop_id=shop_key,
        resources=filtered_resources,
    )


async def run_mock_analytics_reconcile_orchestrated(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
    shop_key: str,
    orchestrator_run_fn: Callable | None = None,
) -> None:
    """Route hourly reconciliation through SharedComputeOrchestrator with reconcile_hourly reason.

    Uses a bounded gap-targeted fetch plan (not the material matrix) and applies
    quota guards (#632).
    """
    fetch_plan = _make_hourly_gap_fetch_plan(shop_key)

    # Idempotency key: unique per hour per shop
    # Use a simple hash of hour to ensure same-hour retries dedupe
    from datetime import UTC, datetime

    hour_key = datetime.now(UTC).strftime("%Y-%m-%d-%H:00")
    idempotency_key = f"hourly-reconcile-{shop_id}-{hour_key}"

    job = SharedComputeJob(
        shop_id=shop_id,
        shop_key=shop_key,
        enqueue_reason="reconcile_hourly",
        fetch_plan=fetch_plan,
        idempotency_key=idempotency_key,
    )

    if orchestrator_run_fn is not None:
        # Test-only: allow custom orchestrator function
        await orchestrator_run_fn(job)
    else:
        await run_shared_compute_job(session, job)

    logger.info(
        "mock_analytics_reconcile_orchestrated_completed",
        extra={
            "shop_id": str(shop_id),
            "enqueue_reason": job.enqueue_reason,
            "fetch_plan_size": len(job.fetch_plan.resources),
            "idempotency_key": idempotency_key,
        },
    )


def run_mock_analytics_reconcile_sync(
    *,
    precompute_fn: Callable[[str], None] | None = None,
) -> None:
    """Recompute Analytics envelopes for the configured reference shop only."""
    shop_id = get_demo_reference_shop_id()
    if shop_id is None:
        logger.info(
            "mock_analytics_reconcile_skipped",
            extra={"reason": "missing_demo_reference_shop_id"},
        )
        return

    shop_key = _lookup_tiktok_shop_key(shop_id)
    if shop_key is None:
        return

    compute = precompute_fn or material_analytics_precompute_sync
    compute(shop_key)


async def _run_hourly_reconcile_async() -> None:
    """Run hourly reconciliation through SharedComputeOrchestrator."""
    shop_id = get_demo_reference_shop_id()
    if shop_id is None:
        logger.info(
            "mock_analytics_reconcile_skipped",
            extra={"reason": "missing_demo_reference_shop_id"},
        )
        return

    # Await the async lookup directly — the sync `_lookup_tiktok_shop_key` wrapper
    # opens its own event loop, which raises inside this already-running one (#733).
    shop_key = await _lookup_tiktok_shop_key_async(shop_id)
    if shop_key is None:
        return

    factory = _ensure_session_factory()
    async with factory() as session:
        await run_mock_analytics_reconcile_orchestrated(
            session=session,
            shop_id=shop_id,
            shop_key=shop_key,
        )
        await session.commit()


@celery_app.task(name="juli_backend.mock_analytics_hourly_reconcile")
def mock_analytics_hourly_reconcile() -> None:
    """Hourly Celery Beat entrypoint for Mock-mode reference-shop reconciliation.

    Routes through SharedComputeOrchestrator with reconcile_hourly enqueue_reason (#632).
    """
    asyncio.run(_run_hourly_reconcile_async())
