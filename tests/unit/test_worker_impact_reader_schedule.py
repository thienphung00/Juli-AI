"""Daily impact-reader beat schedule — registered and scheduled strictly
after `analytics-backfill-topup` (#1044, ADR-077 decision 5).

Ordering matters, not just registration: the reader is scheduled to run
after the day's analytics top-up so it reads the freshest partitions the
top-up produced (reference shop only — see the reference-shop-gap trap
covered in ``test_worker_impact_reader_pipeline.py``).
"""

from __future__ import annotations

from celery.schedules import crontab


def test_daily_impact_reader_entry_registered():
    from juli_backend.workers.celery_app import celery_app

    assert "daily-impact-reader" in celery_app.conf.beat_schedule


def test_daily_impact_reader_entry_targets_correct_task_name():
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["daily-impact-reader"]
    assert entry["task"] == "juli_backend.daily_impact_reader"


def test_daily_impact_reader_task_is_registered_on_worker():
    """The #791 guard: a beat entry with no matching import in
    ``workers/tasks/__init__.py`` dispatches into nothing, silently."""
    from juli_backend.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    assert "juli_backend.daily_impact_reader" in set(celery_app.tasks)


def test_daily_impact_reader_scheduled_after_analytics_backfill_topup():
    """Assert the ORDERING, not just registration — the issue's own
    acceptance criterion."""
    from juli_backend.workers.celery_app import celery_app

    topup_schedule = celery_app.conf.beat_schedule["analytics-backfill-topup"]["schedule"]
    reader_schedule = celery_app.conf.beat_schedule["daily-impact-reader"]["schedule"]
    assert isinstance(topup_schedule, crontab)
    assert isinstance(reader_schedule, crontab)

    topup_hour = min(topup_schedule.hour)
    reader_hour = min(reader_schedule.hour)
    assert reader_hour > topup_hour, (
        "daily-impact-reader must run strictly after analytics-backfill-topup "
        f"(topup hour={topup_hour}, reader hour={reader_hour})"
    )
