"""Celery beat task: the daily stock e-mail of every Shopee shop (Part S).

``juli_backend.stock_alert_daily`` (default queue, 00:00 UTC = 07:00 GMT+7): ``services/stock_alert
.job.run_all``. One e-mail per shop per local day (a send-log row with a unique (shop, day));
shops whose ``stock_alert_status`` is ``off`` (the default) and the reviewer's sample shop are
skipped. One session per shop; a failure is counted and never stops the rest.
"""

from __future__ import annotations

import asyncio

from juli_backend.services.stock_alert import job
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks.database import get_async_database_url

STOCK_ALERT_TASK = "juli_backend.stock_alert_daily"


@celery_app.task(name=STOCK_ALERT_TASK)
def stock_alert_daily() -> dict[str, int]:
    from juli_backend.database.database import ensure_worker_session_factory

    factory = ensure_worker_session_factory(get_async_database_url())
    summary = asyncio.run(job.run_all(factory))
    return {"shops": summary.shops, "done": summary.done, "failed": summary.failed}


__all__ = ["STOCK_ALERT_TASK", "stock_alert_daily"]
