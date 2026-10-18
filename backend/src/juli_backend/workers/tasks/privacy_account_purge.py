"""Celery beat task: delete accounts whose deletion date has passed (fast track P50-B).

``juli_backend.privacy_account_purge`` (default queue, nightly)
    D60.10: 30 days after the seller asked (``users.deletion_scheduled_for``),
    the account, its shops and every row of their shop data are deleted;
    ``shop_subscription_periods`` (contract / payment records, 10 years) are kept,
    detached from the shop. Runs as ``juli_ops`` through migration 094's SECURITY
    DEFINER functions (``services/privacy/purge.py``). One transaction per
    account: one account's failure rolls back only that account, and tomorrow's
    run retries it.

    The Supabase Auth user is NOT deleted: the backend holds no Supabase admin
    (service-role) client. ``auth_users_pending`` counts them (DEBT). A deleted
    seller who signs in again gets a fresh, empty account.

    Logs counts only -- never a user id, e-mail or shop name.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from juli_backend.services.privacy import due_account_ids, purge_account
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

PRIVACY_ACCOUNT_PURGE_TASK = "juli_backend.privacy_account_purge"


async def run_privacy_account_purge(
    session_factory: Any, *, now: datetime | None = None
) -> dict[str, int]:
    moment = now or datetime.now(UTC)
    async with session_factory() as session:
        due = await due_account_ids(session, now=moment)
        await session.commit()
    summary = {
        "due": len(due),
        "purged": 0,
        "failed": 0,
        "shops": 0,
        "rows": 0,
        "kept_periods": 0,
        "auth_users_pending": 0,
    }
    for user_id in due:
        async with session_factory() as session:
            try:
                counts = await purge_account(session, user_id)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                summary["failed"] += 1
                logger.error(
                    "privacy_account_purge_account_failed",
                    extra={"error_type": type(exc).__name__},
                )
                continue
        summary["purged"] += 1
        summary["shops"] += counts.shops
        summary["rows"] += counts.rows
        summary["kept_periods"] += counts.kept_periods
        summary["auth_users_pending"] += 1
    logger.info("privacy_account_purge", extra=dict(summary))
    return summary


@celery_app.task(name=PRIVACY_ACCOUNT_PURGE_TASK)
def privacy_account_purge() -> dict[str, int]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        return asyncio.run(run_privacy_account_purge(factory))
    except Exception as exc:
        logger.error(
            "privacy_account_purge_failed",
            extra={"error_type": type(exc).__name__},
            exc_info=False,
        )
        return {}


__all__ = [
    "PRIVACY_ACCOUNT_PURGE_TASK",
    "privacy_account_purge",
    "run_privacy_account_purge",
]
