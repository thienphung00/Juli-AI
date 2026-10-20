"""Daily impact-reader beat schedule registration — ADR-077 decision 5 (#1044).

`celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])` imports the
*package*, not each module inside it (see #791/test_beat_schedule_registration.py's
own module docstring for the failure mode this guards against). This module
pins two additional, feature-specific invariants that generic test does not:
the entry's name/schedule, and that the task name it points at is actually
claimed by a worker. (ADR-077 decision 5 ordered it after the reference-shop
`analytics-backfill-topup`; fast track P61-D retired that beat -- every shop's
daily analytics now lands through its own `poll_shop` cycle.)
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


def test_the_reference_shop_topup_beat_is_gone():
    """P61-D (D71.4): no beat reads DEMO_REFERENCE_SHOP_ID any more."""
    from juli_backend.workers.celery_app import celery_app

    assert "analytics-backfill-topup" not in celery_app.conf.beat_schedule
    reader_schedule = celery_app.conf.beat_schedule["daily-impact-reader"]["schedule"]
    assert reader_schedule == crontab(hour=3, minute=23)


def test_daily_impact_reader_task_is_registered_on_worker(registered_task_names: set[str]):
    """The guard #791 was missing: a beat entry pointing at a task name no
    worker actually claims dispatches into nothing, silently."""
    assert "juli_backend.daily_impact_reader" in registered_task_names
