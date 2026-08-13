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
        # CDP-A2-9 — Staggered daily batch reconcile for fleet (#622).
        # Mixed-version hazard: task must be registered on all workers before enabling flag.
        # Flag defaults OFF; enable via CDP_BATCH_STAGGERED_RECONCILE_ENABLED env var.
        "cdp-batch-staggered-reconcile": {
            "task": "juli_backend.cdp_batch_staggered_reconcile",
            "schedule": crontab(),  # Every minute
        },
        # P2-9-6 — Automatic analytics history top-up for reference shop (#791).
        # Runs daily at 2 AM UTC to top up missing or stale partitions.
        # A1 scope: single-shop only (DEMO_REFERENCE_SHOP_ID). Fleet-wide belongs in A2 (#601).
        # Idempotent via resumable checkpoints (AnalyticsBackfillPartitionsRepo).
        "analytics-backfill-topup": {
            "task": "juli_backend.analytics_backfill_topup",
            "schedule": crontab(hour=2, minute=0),
        },
        # P-IM — Daily impact-reader beat task (ADR-077 decision 5, #1044).
        # Scheduled strictly after analytics-backfill-topup (02:00) so it
        # reads the day's freshest reference-shop partitions. Not shop-
        # scoped itself (scans terminal runs across every shop); missing
        # daily rows for a non-reference shop degrade to a suppressed
        # reading, never a crash (see workers/impact_reader/pipeline.py).
        # Idempotent via the impact_readings unique constraint (#1040) plus
        # the task's own pre-write existence checks.
        "daily-impact-reader": {
            "task": "juli_backend.daily_impact_reader",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])

from juli_backend.workers.dispatch_binding import bind_celery_dispatchers  # noqa: E402

bind_celery_dispatchers()
