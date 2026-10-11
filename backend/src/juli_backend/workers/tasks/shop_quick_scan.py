"""Celery task: the quick scan right after a shop connects (fast track P17, D26).

``juli_backend.shop_quick_scan`` (queue ``ingest_priority``)
    Enqueued by ``bootstrap_shop`` as it starts (``shop_ingestion``,
    de-duplicated by a ``quick_scan_queued`` marker), so it runs in another
    worker process in parallel with the fast phase. The body is
    ``services.onboarding.quick_scan.run_quick_scan``: 14 days of A-34 + TikTok's
    listing diagnosis for the top products -> 1-3 quick cards, surfaced by the
    emission budget. No LLM.

ONE SCAN PER SHOP AT A TIME. Its own per-shop Redis lock ``quick_scan`` --
never the ``cycle`` lock, which the fast phase holds. Skips when held.

SHARED RATE LIMIT. Every read takes a token from the poll path's Redis
per-endpoint window (``shop_diagnosis_daily.pacing``), like the diagnosis.

FAILURE ISOLATION. The scan records ``failed`` and returns; the full diagnosis
at the end of the fast phase writes the cards anyway.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

QUICK_SCAN_TASK = "juli_backend.shop_quick_scan"
QUEUE = "ingest_priority"
LOCK_NAME = "quick_scan"
#: The scan targets 2-3 minutes; the outer bound covers a rate-limit wait.
BUDGET_SECONDS = 600.0
_LOCK_GRACE_SECONDS = 60


def enqueue_quick_scan(shop_id: str) -> str | None:
    """Enqueue one scan on the priority queue; never raises."""
    try:
        return shop_quick_scan.apply_async(args=[shop_id], queue=QUEUE).id
    except Exception:
        logger.error("shop_quick_scan_enqueue_failed", extra={"shop_id": shop_id}, exc_info=True)
        return None


async def run_quick_scan_task(
    shop_id: str,
    *,
    session_factory: Any,
    app_key: str,
    app_secret: str,
    lock: Any,
    rate_limiter: Any | None = None,
    scan_kwargs: dict[str, Any] | None = None,
) -> Any:
    from juli_backend.services.onboarding import run_quick_scan

    token = lock.try_acquire(
        shop_id, LOCK_NAME, ttl_seconds=int(BUDGET_SECONDS) + _LOCK_GRACE_SECONDS
    )
    if token is None:
        logger.info("shop_quick_scan_skipped_locked", extra={"shop_id": shop_id})
        return None
    try:
        return await run_quick_scan(
            session_factory=session_factory,
            shop_id=uuid.UUID(shop_id),
            app_key=app_key,
            app_secret=app_secret,
            rate_limiter=rate_limiter,
            **(scan_kwargs or {}),
        )
    finally:
        lock.release(shop_id, LOCK_NAME, token)


@celery_app.task(name=QUICK_SCAN_TASK)
def shop_quick_scan(shop_id: str) -> None:
    """The quick scan for one shop (priority queue)."""
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not (app_key and app_secret and redis_url):
        logger.info(
            "shop_quick_scan_skipped",
            extra={"shop_id": shop_id, "reason": "missing_tiktok_or_redis_env"},
        )
        return

    async def go() -> None:
        import redis

        from juli_backend.database.database import ensure_worker_session_factory
        from juli_backend.services.shop_diagnosis_daily import shared_rate_limiter
        from juli_backend.workers.services.polling.shop_lock import RedisShopIngestLock

        client = redis.from_url(redis_url)
        await run_quick_scan_task(
            shop_id,
            session_factory=ensure_worker_session_factory(get_async_database_url()),
            app_key=app_key,
            app_secret=app_secret,
            lock=RedisShopIngestLock(client),
            rate_limiter=shared_rate_limiter(client),
        )

    try:
        asyncio.run(asyncio.wait_for(go(), timeout=BUDGET_SECONDS))
    except TimeoutError:
        logger.error(
            "shop_quick_scan_timeout", extra={"shop_id": shop_id, "timeout_seconds": BUDGET_SECONDS}
        )


__all__ = [
    "LOCK_NAME",
    "QUICK_SCAN_TASK",
    "enqueue_quick_scan",
    "run_quick_scan_task",
    "shop_quick_scan",
]
