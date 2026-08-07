"""Celery task entrypoint for material Analytics precompute (#532 / #627)."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.services.webhook.material_worker import run_material_analytics_compute
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return get_async_database_url()


def _ensure_session_factory() -> async_sessionmaker:
    from juli_backend.database.database import ensure_worker_session_factory

    return ensure_worker_session_factory(_database_url())


async def _compute_async(
    shop_key: str,
    *,
    event_type: str | None,
    enqueue_reason: str,
    idempotency_key: str,
) -> None:
    from juli_backend.services.webhook.material_dispatch import get_material_enqueue_gate

    factory = _ensure_session_factory()
    gate = get_material_enqueue_gate()
    async with factory() as session:
        await run_material_analytics_compute(
            session,
            shop_key=shop_key,
            event_type=event_type,
            enqueue_reason=enqueue_reason,
            idempotency_key=idempotency_key,
            gate=gate,
        )


def material_analytics_precompute_sync(
    shop_key: str,
    *,
    event_type: str | None = None,
    enqueue_reason: str = "reconcile_hourly",
    idempotency_key: str | None = None,
) -> None:
    job_key = idempotency_key or f"direct:{uuid.uuid4()}"
    asyncio.run(
        _compute_async(
            shop_key,
            event_type=event_type,
            enqueue_reason=enqueue_reason,
            idempotency_key=job_key,
        )
    )


@celery_app.task(name="juli_backend.material_analytics_precompute", bind=True)
def material_analytics_precompute(
    self,
    shop_key: str,
    *,
    event_type: str | None = None,
    enqueue_reason: str,
    idempotency_key: str | None = None,
) -> None:
    """Run Shared Compute orchestrator for a material webhook enqueue."""
    job_key = idempotency_key or str(self.request.id)
    material_analytics_precompute_sync(
        shop_key,
        event_type=event_type,
        enqueue_reason=enqueue_reason,
        idempotency_key=job_key,
    )
