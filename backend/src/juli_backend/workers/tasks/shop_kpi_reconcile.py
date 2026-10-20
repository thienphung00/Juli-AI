"""Hourly Analytics KPI envelope recompute, one task per connected shop (fast track P61-D, D71.4).

Replaces ``mock_analytics_reconcile.py`` (#533, ADR-038 §5), which recomputed the
envelope for ``DEMO_REFERENCE_SHOP_ID`` only -- every other shop's Analytics KPI
envelope (``gold.kpi_envelopes``) was never refreshed on a schedule. ADR-112 §6.5
names this change.

``juli_backend.shop_kpi_reconcile_fanout`` (beat, hourly at :00)
    Enumerates shops exactly as ``shop_poll_fanout`` does
    (``enumerate_pollable_shops``: migration 074's SECURITY DEFINER function,
    identifiers only, ADR-089 decision 3) and enqueues one
    ``shop_kpi_reconcile`` per shop past its fast phase. One shop's enqueue
    failure never stops the rest.

``juli_backend.shop_kpi_reconcile`` (default queue)
    One shop, under ``with_shop_scope(shop_id)``: resolves the shop's TikTok key
    inside the scope (#1518), then runs the Shared Compute job (bronze -> silver
    -> gold KPI envelope -> flag-gated Decision scoring) with
    ``enqueue_reason="reconcile_hourly"`` (#632). The orchestrator re-enters the
    scope around every stage itself (#1576).

THE FETCH IS THE TARGETED-FETCH EXECUTOR'S OWN DECISION, NOT A SHOP LIST. The
hourly gap plan (orders, analytics_shop, ctor, live_hours) is requested only for
a shop the executor can serve -- today ``resolve_job_production_read_credential``
accepts the configured production-read merchant only. Any other shop gets an
empty plan: no vendor call, and the envelope is recomputed from what the shop's
own ``poll_shop`` cycle already ingested (orders hourly, analytics daily). So no
shop is skipped and no shop id is named here. (DEBT P61-D: the ``live_hours``
KPI needs the A-28 bronze path, which is still production-merchant-only.)

COUNTS ARE HONEST (#1857). ``shop_kpi_reconcile_completed`` carries
``fetch_plan_size`` (requested) beside ``bronze_appended`` / ``silver_promoted``
(written) and ``duration_ms``. ``SharedComputeOrchestrator.run`` has no
try/except around its stages, so on a raise the counts are logged as ``None``
(unknown), never a fabricated ``0``, and the exception re-raises.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop
from juli_backend.services.cdp_speed import (
    FetchResource,
    SharedComputeJob,
    TargetedFetchExecutor,
    TargetedFetchPlan,
    decision_rules_scoring_stage,
    is_quota_guarded,
    run_shared_compute_job,
    static_fetch_resource,
)
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

FANOUT_TASK = "juli_backend.shop_kpi_reconcile_fanout"
SHOP_TASK = "juli_backend.shop_kpi_reconcile"
ENQUEUE_REASON = "reconcile_hourly"
#: Bound on the fan-out tick itself (enumerate + enqueue), not on a shop's job.
FANOUT_TIMEOUT_SECONDS = 120.0
#: The hourly gap plan's resources, by the planner's canonical names (#632, #880).
GAP_PLAN_RESOURCES = ("orders", "analytics_shop", "ctor", "live_hours")

SessionFactory = Callable[[], Any]
ResolveFetchCredentialFn = Callable[[AsyncSession, uuid.UUID], Awaitable[Any]]


def _session_factory() -> SessionFactory:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(get_async_database_url())


async def read_shop_key(session: AsyncSession, shop_id: uuid.UUID) -> str | None:
    """The shop's TikTok key, read on the caller's (shop-scoped) session (#1518)."""
    shop = await session.get(Shop, shop_id)
    if shop is None or not shop.tiktok_shop_id:
        logger.warning("shop_kpi_reconcile_unknown_shop", extra={"shop_id": str(shop_id)})
        return None
    return shop.tiktok_shop_id


def make_gap_fetch_plan(shop_key: str) -> TargetedFetchPlan:
    """The bounded hourly gap plan, quota guards applied (not the material matrix).

    Resources come from the planner's canonical definitions
    (``static_fetch_resource``), so this plan cannot drift from the material
    matrix's definitions of the same resources.
    """
    resources: list[FetchResource] = [static_fetch_resource(name) for name in GAP_PLAN_RESOURCES]
    return TargetedFetchPlan(
        catalog_id=None,
        shop_id=shop_key,
        resources=tuple(r for r in resources if not is_quota_guarded(r.name)),
    )


def empty_fetch_plan(shop_key: str) -> TargetedFetchPlan:
    """No vendor call: the envelope is recomputed from already-ingested silver."""
    return TargetedFetchPlan(catalog_id=None, shop_id=shop_key, resources=())


async def _default_fetch_credential(session: AsyncSession, shop_id: uuid.UUID) -> Any:
    from juli_backend.services.cdp_speed import resolve_job_production_read_credential

    return await resolve_job_production_read_credential(session, shop_id)


async def choose_fetch_plan(
    session: AsyncSession,
    shop_id: uuid.UUID,
    shop_key: str,
    *,
    resolve_fetch_credential: ResolveFetchCredentialFn | None = None,
) -> TargetedFetchPlan:
    """The gap plan when the targeted-fetch executor can serve this shop, else empty."""
    resolve = resolve_fetch_credential or _default_fetch_credential
    if await resolve(session, shop_id) is None:
        logger.info(
            "shop_kpi_reconcile_fetch_skipped",
            extra={"shop_id": str(shop_id), "reason": "no_targeted_fetch_credential"},
        )
        return empty_fetch_plan(shop_key)
    return make_gap_fetch_plan(shop_key)


def hourly_idempotency_key(shop_id: uuid.UUID, now: datetime | None = None) -> str:
    """Unique per shop per UTC hour, so same-hour retries dedupe."""
    hour = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%d-%H:00")
    return f"hourly-reconcile-{shop_id}-{hour}"


async def run_shop_kpi_reconcile_job(
    *,
    session: AsyncSession,
    shop_id: uuid.UUID,
    shop_key: str,
    fetch_plan: TargetedFetchPlan,
    orchestrator_run_fn: Callable[[SharedComputeJob], Awaitable[Any]] | None = None,
    fetch_executor: TargetedFetchExecutor | None = None,
    clock: Callable[[], float] | None = None,
) -> Any:
    """One Shared Compute job for one shop, with the #1857 completion line."""
    clock = clock or time.monotonic
    started_at = clock()
    job = SharedComputeJob(
        shop_id=shop_id,
        shop_key=shop_key,
        enqueue_reason=ENQUEUE_REASON,
        fetch_plan=fetch_plan,
        idempotency_key=hourly_idempotency_key(shop_id),
    )

    def _log(status: str, bronze: int | None, silver: int | None, *, failed: bool) -> None:
        extra = {
            "shop_id": str(shop_id),
            "enqueue_reason": job.enqueue_reason,
            "fetch_plan_size": len(job.fetch_plan.resources),
            "idempotency_key": job.idempotency_key,
            "bronze_appended": bronze,
            "silver_promoted": silver,
            "duration_ms": int((clock() - started_at) * 1000),
            "status": status,
        }
        if failed:
            logger.exception("shop_kpi_reconcile_completed", extra=extra)
        else:
            logger.info("shop_kpi_reconcile_completed", extra=extra)

    try:
        if orchestrator_run_fn is not None:
            result = await orchestrator_run_fn(job)
        else:
            # Decision scoring stays gated by CDP_DECISIONS_SCORING_ENABLED (#714).
            result = await run_shared_compute_job(
                session,
                job,
                fetch_executor=fetch_executor,
                scoring_stage=decision_rules_scoring_stage,
            )
    except Exception:
        _log("failed", None, None, failed=True)
        raise

    bronze = getattr(result, "bronze_appended", None) if result is not None else None
    silver = getattr(result, "silver_promoted", None) if result is not None else None
    _log("succeeded", bronze, silver, failed=False)
    return result


async def run_shop_kpi_reconcile(
    shop_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    resolve_fetch_credential: ResolveFetchCredentialFn | None = None,
    orchestrator_run_fn: Callable[[SharedComputeJob], Awaitable[Any]] | None = None,
    fetch_executor: TargetedFetchExecutor | None = None,
) -> Any:
    """The per-shop task body: scope -> shop key -> plan -> job -> commit."""
    from juli_backend.database.tenant_context import with_shop_scope

    async with session_factory() as session:
        async with with_shop_scope(session, shop_id):
            shop_key = await read_shop_key(session, shop_id)
            if shop_key is None:
                return None
            plan = await choose_fetch_plan(
                session, shop_id, shop_key, resolve_fetch_credential=resolve_fetch_credential
            )
            result = await run_shop_kpi_reconcile_job(
                session=session,
                shop_id=shop_id,
                shop_key=shop_key,
                fetch_plan=plan,
                orchestrator_run_fn=orchestrator_run_fn,
                fetch_executor=fetch_executor,
            )
            await session.commit()
            return result


async def run_fanout(
    session: AsyncSession,
    *,
    enqueue: Callable[[str], Any],
    enumerate_fn: Callable[[AsyncSession], Awaitable[list[Any]]] | None = None,
) -> int:
    """One ``shop_kpi_reconcile`` per pollable shop past its fast phase. Returns the count."""
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    shops = await (enumerate_fn or enumerate_pollable_shops)(session)
    enqueued = 0
    for shop in shops:
        if not shop.fast_done:
            continue
        try:
            enqueue(str(shop.shop_id))
            enqueued += 1
        except Exception:
            logger.error(
                "shop_kpi_reconcile_enqueue_failed",
                extra={"shop_id": str(shop.shop_id)},
                exc_info=True,
            )
    logger.info("shop_kpi_reconcile_fanout", extra={"shops": len(shops), "enqueued": enqueued})
    return enqueued


@celery_app.task(name="juli_backend.shop_kpi_reconcile_fanout")
def shop_kpi_reconcile_fanout() -> int:
    """Beat: enqueue one envelope recompute per connected shop."""

    async def go() -> int:
        async with _session_factory()() as session:
            return await run_fanout(session, enqueue=lambda sid: shop_kpi_reconcile.delay(sid))

    try:
        return int(asyncio.run(asyncio.wait_for(go(), timeout=FANOUT_TIMEOUT_SECONDS)) or 0)
    except TimeoutError:
        logger.error(
            "shop_kpi_reconcile_fanout_timeout",
            extra={"timeout_seconds": FANOUT_TIMEOUT_SECONDS},
        )
        raise


@celery_app.task(name="juli_backend.shop_kpi_reconcile")
def shop_kpi_reconcile(shop_id: str) -> None:
    """One shop's hourly envelope recompute (routes through SharedComputeOrchestrator)."""
    asyncio.run(run_shop_kpi_reconcile(uuid.UUID(shop_id), session_factory=_session_factory()))


__all__ = [
    "ENQUEUE_REASON",
    "FANOUT_TASK",
    "GAP_PLAN_RESOURCES",
    "SHOP_TASK",
    "choose_fetch_plan",
    "empty_fetch_plan",
    "hourly_idempotency_key",
    "make_gap_fetch_plan",
    "read_shop_key",
    "run_fanout",
    "run_shop_kpi_reconcile",
    "run_shop_kpi_reconcile_job",
    "shop_kpi_reconcile",
    "shop_kpi_reconcile_fanout",
]
