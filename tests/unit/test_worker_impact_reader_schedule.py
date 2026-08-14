"""Daily impact-reader beat schedule registration — ADR-077 decision 5 (#1044).

`celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])` imports the
*package*, not each module inside it (see #791/test_beat_schedule_registration.py's
own module docstring for the failure mode this guards against). This module
pins two additional, feature-specific invariants that generic test does not:
the entry's name/schedule/ordering relative to `analytics-backfill-topup`
(ADR-077 decision 5: the reader must run *after* the analytics backfill
top-up so it reads freshly topped-up partitions), and that the task name it
points at is actually claimed by a worker.
"""

from __future__ import annotations

import pytest
from celery.schedules import crontab


@pytest.fixture(scope="module")
def registered_task_names() -> set[str]:
    from juli_backend.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    return set(celery_app.tasks)


def test_daily_impact_reader_entry_registered():
    from juli_backend.workers.celery_app import celery_app

    assert "daily-impact-reader" in celery_app.conf.beat_schedule


def test_daily_impact_reader_entry_targets_correct_task_name():
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["daily-impact-reader"]
    assert entry["task"] == "juli_backend.daily_impact_reader"


def test_daily_impact_reader_scheduled_after_analytics_backfill_topup():
    """ADR-077 decision 5: 'a daily impact-reader beat task scheduled after
    the analytics backfill top-up' — pinned as an hour ordering, not just a
    vague 'later' claim."""
    from juli_backend.workers.celery_app import celery_app

    topup_entry = celery_app.conf.beat_schedule["analytics-backfill-topup"]
    reader_entry = celery_app.conf.beat_schedule["daily-impact-reader"]
    topup_schedule = topup_entry["schedule"]
    reader_schedule = reader_entry["schedule"]
    assert isinstance(topup_schedule, crontab)
    assert isinstance(reader_schedule, crontab)

    def _hour(schedule: crontab) -> int:
        return min(schedule.hour)

    assert _hour(reader_schedule) > _hour(topup_schedule), (
        "daily-impact-reader must run strictly after analytics-backfill-topup "
        f"(topup hour(s)={topup_schedule.hour}, reader hour(s)={reader_schedule.hour})"
    )


def test_daily_impact_reader_task_is_registered_on_worker(registered_task_names: set[str]):
    """The guard #791 was missing: a beat entry pointing at a task name no
    worker actually claims dispatches into nothing, silently."""
    assert "juli_backend.daily_impact_reader" in registered_task_names
