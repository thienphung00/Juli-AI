"""Celery application for Juli backend workers."""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

celery_app = Celery(
    "juli_backend",
    broker=os.getenv("CELERY_BROKER_URL", "memory://"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "cache+memory://"),
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # ADR-038 §5 — Mock-mode hourly reconciliation for DEMO_REFERENCE_SHOP_ID only (#533).
        "mock-analytics-hourly-reconcile": {
            "task": "juli_backend.mock_analytics_hourly_reconcile",
            "schedule": crontab(minute=0),
        },
    },
)

celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])

from juli_backend.workers.dispatch_binding import bind_celery_dispatchers  # noqa: E402

bind_celery_dispatchers()
