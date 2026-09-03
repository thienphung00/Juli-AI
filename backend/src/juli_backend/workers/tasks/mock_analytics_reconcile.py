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

from juli_backend.services.cdp_speed import (
    FetchResource,
    SharedComputeJob,
    TargetedFetchPlan,
    decision_rules_scoring_stage,
    is_quota_guarded,
    run_shared_compute_job,
    static_fetch_resource,
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


def get_demo_reference_shop_key() -> str | None:
    """Return the configured TikTok shop key for the demo reference shop.

    WHY THIS IS CONFIGURATION RATHER THAN A LOOKUP (#1518).

    The key used to be read from `public.shops`, which is user-keyed:

        shops | SELECT | (user_id = app_current_user_id())

    This task has a shop but no user, and `with_shop_scope` withholds the user
    GUC by design, so as `juli_app` that read returns zero rows — measured, not
    assumed. The task then returned early and did nothing, with a warning and
    no error, which is the successful no-op ADR-089 exists to remove.

    It cannot be fixed by widening the scope either: resolving the user means
    reading `shops.user_id`, which is the denied read. That circularity is
    called out in `with_shop_scope`'s own docstring.

    So the read is removed rather than authorized, per ADR-089 decision 5 — a
    task that does not need a cross-tenant read does not get one. The shop id
    beside it is already server-bound configuration; its key now is too.
    """
    raw = os.getenv("DEMO_REFERENCE_SHOP_KEY", "").strip()
    return raw or None


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory():
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


def _make_hourly_gap_fetch_plan(shop_key: str) -> TargetedFetchPlan:
    """Create a bounded gap-targeted fetch plan for hourly reconciliation.

    Not the material matrix — orders, analytics_shop, ctor (A-34), and
    live_hours (A-28) for hourly reconciliation, with quota guards applied
    (#632, extended #880). The Fujiwa Mock reference shop is driven entirely
    by this hourly reconcile (no webhook material trigger reaches it), so
    ctor/live_hours freshness depends on this plan requesting them — the
    material webhook matrix (catalog id 5 -> ``ctor``) does not cover it.

    Resources reference the planner's canonical static definitions
    (``static_fetch_resource``) rather than duplicating endpoint-path
    literals inline, so this plan cannot drift from the material matrix's
    definitions of the same named resources.
    """
    base_resources: list[FetchResource] = [
        static_fetch_resource("orders"),
        static_fetch_resource("analytics_shop"),
        static_fetch_resource("ctor"),
        static_fetch_resource("live_hours"),
    ]

    # Filter out any quota-guarded resources (A-38/A-39/A-31/A-33) — ctor and
    # live_hours are not in QUOTA_GUARDED_RESOURCE_NAMES (see
    # tests/unit/test_mock_analytics_hourly_reconcile.py
    # ::TestHourlyGapPlanIncludesCtorAndLiveHours) so this filter is a
    # defensive no-op for them today, not how they get included.
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
        # Continuous-trigger scoring callable (#714 / B-2): hourly Mock reconcile
        # is a continuous trigger too (PRD #599 user story 30) — gap reconciliation
        # must heal Decision staleness the same way it heals KPI envelope staleness.
        # Execution stays gated by CDP_DECISIONS_SCORING_ENABLED (default OFF).
        await run_shared_compute_job(
            session,
            job,
            scoring_stage=decision_rules_scoring_stage,
        )

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

    shop_key = get_demo_reference_shop_key()
    if shop_key is None:
        logger.warning(
            "mock_analytics_reconcile_skipped",
            extra={
                "reason": "missing_demo_reference_shop_key",
                "shop_id": str(shop_id),
            },
        )
        return

    compute = precompute_fn or material_analytics_precompute_sync
    compute(shop_key)


async def _run_hourly_reconcile_async() -> None:
    """Run hourly reconciliation through SharedComputeOrchestrator."""
    from juli_backend.database.tenant_context import with_shop_scope

    shop_id = get_demo_reference_shop_id()
    if shop_id is None:
        logger.info(
            "mock_analytics_reconcile_skipped",
            extra={"reason": "missing_demo_reference_shop_id"},
        )
        return

    shop_key = get_demo_reference_shop_key()
    if shop_key is None:
        # Fail closed and say so. Silently falling back to the database read
        # would restore exactly the no-op this issue exists to remove: as
        # `juli_app` that read returns nothing, and the task would report a
        # clean cycle having recomputed no envelopes at all.
        logger.warning(
            "mock_analytics_reconcile_skipped",
            extra={
                "reason": "missing_demo_reference_shop_key",
                "shop_id": str(shop_id),
            },
        )
        return

    factory = _ensure_session_factory()
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
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
