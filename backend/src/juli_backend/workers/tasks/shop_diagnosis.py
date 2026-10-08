"""Celery task: build and store one shop's ADR-108 diagnosis report (fast track P7-A).

``juli_backend.build_shop_diagnosis`` (default queue)
    Enqueued by ``workers/tasks/shop_ingestion.py`` after a shop's daily
    analytics pass lands new days, and once after its bootstrap fast phase.
    The body is ``services.shop_diagnosis_daily.build_and_store_shop_diagnosis``
    (read-only TikTok fetch, per-shop read credential, idempotent per shop and
    report end date).

ONE BUILD PER SHOP AT A TIME. The body takes the per-shop Redis lock
``ingest:diagnosis:{shop_id}`` (``workers/services/polling/shop_lock.py``, the
P1-B poll-cycle lock) and skips -- never waits -- when another build for the
same shop holds it. TTL = budget + grace. On a timeout the lock is NOT
released: the fetch thread cannot be stopped mid-call, so the TTL bounds it.

SHARED RATE LIMIT. The production task hands the fetch the poll path's Redis
``RateLimiter`` (same client as the lock), so the report's reads draw from the
same per-endpoint window as the poll (``services/shop_diagnosis_daily/pacing.py``).

FAILURE ISOLATION. This is its own task, so nothing here can fail a poll
cycle: the enqueue helper swallows broker errors, and the task logs a failure
(``shop_diagnosis_failed``) and returns instead of raising -- tomorrow's
analytics pass enqueues it again.
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

BUILD_SHOP_DIAGNOSIS_TASK = "juli_backend.build_shop_diagnosis"
BUDGET_SECONDS_ENV = "SHOP_DIAGNOSIS_BUDGET_SECONDS"
_DEFAULT_BUDGET_SECONDS = 1800.0
LOCK_NAME = "diagnosis"
_LOCK_GRACE_SECONDS = 300


def budget_seconds() -> float:
    try:
        return max(60.0, float(os.getenv(BUDGET_SECONDS_ENV, "") or _DEFAULT_BUDGET_SECONDS))
    except ValueError:
        return _DEFAULT_BUDGET_SECONDS


def lock_ttl_seconds() -> int:
    return int(budget_seconds()) + _LOCK_GRACE_SECONDS


def enqueue_shop_diagnosis(shop_id: str) -> str | None:
    """Enqueue one build; never raises (a broker hiccup must not fail the caller)."""
    try:
        return build_shop_diagnosis.delay(shop_id).id
    except Exception:
        logger.error("shop_diagnosis_enqueue_failed", extra={"shop_id": shop_id}, exc_info=True)
        return None


async def run_build_shop_diagnosis(
    shop_id: str,
    *,
    session_factory: Any,
    app_key: str,
    app_secret: str,
    lock: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Task body; returns the build result, or ``None`` when skipped or after logging a failure."""
    token: str | None = None
    if lock is not None:
        token = lock.try_acquire(shop_id, LOCK_NAME, ttl_seconds=lock_ttl_seconds())
        if token is None:
            logger.info("shop_diagnosis_skipped_locked", extra={"shop_id": shop_id})
            return None
    cancelled = False
    try:
        return await _build(
            shop_id,
            session_factory=session_factory,
            app_key=app_key,
            app_secret=app_secret,
            **kwargs,
        )
    except asyncio.CancelledError:
        # Timed out: the fetch thread may still be calling TikTok. Leave the
        # lock to its TTL so a second build cannot start beside it.
        cancelled = True
        raise
    finally:
        if lock is not None and token is not None and not cancelled:
            lock.release(shop_id, LOCK_NAME, token)


async def _build(
    shop_id: str,
    *,
    session_factory: Any,
    app_key: str,
    app_secret: str,
    **kwargs: Any,
) -> Any:
    from juli_backend.services.shop_diagnosis_daily import build_and_store_shop_diagnosis

    try:
        return await build_and_store_shop_diagnosis(
            session_factory=session_factory,
            shop_id=uuid.UUID(shop_id),
            app_key=app_key,
            app_secret=app_secret,
            **kwargs,
        )
    except Exception as exc:
        logger.error(
            "shop_diagnosis_failed",
            extra={
                "shop_id": shop_id,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:200],
            },
            exc_info=True,
        )
        return None


@celery_app.task(name=BUILD_SHOP_DIAGNOSIS_TASK)
def build_shop_diagnosis(shop_id: str) -> None:
    """Build and store the shop's diagnosis report for its latest analytics day."""
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    if not (app_key and app_secret):
        logger.info(
            "shop_diagnosis_skipped", extra={"shop_id": shop_id, "reason": "missing_tiktok_env"}
        )
        return

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        # The lock and the shared rate limit both live in Redis; without them a
        # build could overlap another or starve the poll. The poll needs Redis
        # too, so this only happens on a misconfigured worker.
        logger.error("shop_diagnosis_skipped", extra={"shop_id": shop_id, "reason": "no_redis"})
        return

    async def go() -> None:
        import redis

        from juli_backend.database.database import ensure_worker_session_factory
        from juli_backend.services.shop_diagnosis_daily import shared_rate_limiter
        from juli_backend.workers.services.polling.shop_lock import RedisShopIngestLock

        client = redis.from_url(redis_url)
        await run_build_shop_diagnosis(
            shop_id,
            session_factory=ensure_worker_session_factory(get_async_database_url()),
            app_key=app_key,
            app_secret=app_secret,
            lock=RedisShopIngestLock(client),
            rate_limiter=shared_rate_limiter(client),
        )

    timeout = budget_seconds()
    try:
        asyncio.run(asyncio.wait_for(go(), timeout=timeout))
    except TimeoutError:
        logger.error(
            "shop_diagnosis_timeout", extra={"shop_id": shop_id, "timeout_seconds": timeout}
        )


__all__ = [
    "BUILD_SHOP_DIAGNOSIS_TASK",
    "LOCK_NAME",
    "build_shop_diagnosis",
    "enqueue_shop_diagnosis",
    "lock_ttl_seconds",
    "run_build_shop_diagnosis",
]
