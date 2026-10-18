"""Celery beat task: the system OpenAI limit's 80 % e-mail (fast track P20, D28.3).

``juli_backend.ops_openai_system_alert`` (default queue, hourly at minute 19)
    Sends the month's ONE alert e-mail to the active Admins when the whole
    system's OpenAI spend reaches 80 % of the system cap (and says so if it
    already reached 100 %) -- ``services/ops/system_cap.check_alert``. Remembered
    in ``ops_system_settings['openai_alert_sent']``; without SMTP it logs
    ``openai_system_alert_unsent`` and tries again next hour. A failure is
    logged; the next run catches up.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

logger = logging.getLogger(__name__)

OPS_OPENAI_ALERT_TASK = "juli_backend.ops_openai_system_alert"


async def run_ops_openai_alert(
    session_factory: Any, *, mailer: Any = None, now: datetime | None = None
) -> bool:
    """Check once and commit; True when the e-mail went out on this run."""
    from juli_backend.services.ops import check_alert

    async with session_factory() as session:
        sent = await check_alert(session, mailer=mailer, now=now)
        await session.commit()
    return sent


@celery_app.task(name=OPS_OPENAI_ALERT_TASK)
def ops_openai_system_alert() -> bool:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    try:
        return asyncio.run(run_ops_openai_alert(factory))
    except Exception as exc:
        logger.error(
            "ops_openai_system_alert_failed",
            extra={"error_type": type(exc).__name__, "error_message": str(exc)[:200]},
            exc_info=True,
        )
        return False


__all__ = ["OPS_OPENAI_ALERT_TASK", "ops_openai_system_alert", "run_ops_openai_alert"]
