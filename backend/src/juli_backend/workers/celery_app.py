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
    # ADR-074 decision 4 — dedicated queue for the two agent-run tasks
    # (`workers/tasks/agent_workflow.py`) so multi-minute runs never starve
    # beat or the analytics tasks below, which stay on the (unlisted, thus
    # default) "celery" queue unchanged.
    task_routes={
        "juli_backend.run_agent_workflow": {"queue": "agent_runs"},
        "juli_backend.resume_agent_workflow": {"queue": "agent_runs"},
    },
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
        # ADR-077 decision 5 — Daily impact-reader beat task (#1044).
        # Scheduled strictly after analytics-backfill-topup (hour=2) so it reads
        # analytics_performance_intervals partitions that day's top-up has already
        # refreshed. Scans terminal listing.optimize_product executions whose
        # T+7/T+14 has elapsed and writes impact_readings rows.
        "daily-impact-reader": {
            "task": "juli_backend.daily_impact_reader",
            "schedule": crontab(hour=3, minute=0),
        },
        # #1130, ADR-074 decision 4 — the reaper. Every 5 minutes, closes the
        # two run-abandonment holes through the normal EventSink path: stale
        # running/queued (no event + no live task -> worker_lost -> failed)
        # and expired waiting_approval (past approval_timeout_h ->
        # confirmation_expired -> cancelled). See
        # workers/tasks/reaper.py for the full contract.
        "reap-abandoned-workflow-runs": {
            "task": "juli_backend.reap_abandoned_workflow_runs",
            "schedule": crontab(minute="*/5"),
        },
    },
)

celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])

from juli_backend.workers.agent_broker_guard import run_agent_broker_startup_check  # noqa: E402
from juli_backend.workers.dispatch_binding import bind_celery_dispatchers  # noqa: E402

bind_celery_dispatchers()

# ADR-074 decision 4, "the trap" — agent-enabled deployments must not boot on
# the in-memory broker. No-op (memory:// stays the unit-test default) unless
# AGENT_WORKFLOWS_ENABLED is set; see agent_broker_guard for the full story.
run_agent_broker_startup_check(celery_app.conf.broker_url)
