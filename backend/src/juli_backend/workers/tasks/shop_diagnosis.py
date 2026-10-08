"""Celery task: build and store one shop's ADR-108 diagnosis report (fast track P7-A).

``juli_backend.build_shop_diagnosis`` (default queue)
    Enqueued by ``workers/tasks/shop_ingestion.py`` after a shop's daily
    analytics pass lands new days, and once after its bootstrap fast phase.
    The body is ``services.shop_diagnosis_daily.build_and_store_shop_diagnosis``
    (read-only TikTok fetch, per-shop read credential, idempotent per shop and
    report end date).

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


def budget_seconds() -> float:
    try:
        return max(60.0, float(os.getenv(BUDGET_SECONDS_ENV, "") or _DEFAULT_BUDGET_SECONDS))
    except ValueError:
        return _DEFAULT_BUDGET_SECONDS


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
    **kwargs: Any,
) -> Any:
    """Task body; returns the build result, or ``None`` after logging a failure."""
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

    async def go() -> None:
        from juli_backend.database.database import ensure_worker_session_factory

        await run_build_shop_diagnosis(
            shop_id,
            session_factory=ensure_worker_session_factory(get_async_database_url()),
            app_key=app_key,
            app_secret=app_secret,
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
    "build_shop_diagnosis",
    "enqueue_shop_diagnosis",
    "run_build_shop_diagnosis",
]
