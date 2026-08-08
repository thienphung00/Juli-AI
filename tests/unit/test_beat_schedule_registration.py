"""Every scheduled task must actually be registered on the worker.

`celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])` imports the
*package*, not each module inside it. So a task file that nothing imports is never
registered, and Celery Beat happily dispatches to a name no worker claims — the
schedule silently does nothing, with no error anywhere.

#791 added analytics_backfill_topup with a beat entry but did not add it to
workers/tasks/__init__.py, so its 02:00 schedule could never have run.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def registered_task_names() -> set[str]:
    from juli_backend.workers.celery_app import celery_app

    # This is what a worker does at boot; without it autodiscovery stays lazy
    # and the registry looks empty.
    celery_app.loader.import_default_modules()
    return set(celery_app.tasks)


@pytest.fixture(scope="module")
def beat_task_names() -> dict[str, str]:
    from juli_backend.workers.celery_app import celery_app

    return {
        entry_name: entry["task"] for entry_name, entry in celery_app.conf.beat_schedule.items()
    }


def test_beat_schedule_is_not_empty(beat_task_names: dict[str, str]):
    assert beat_task_names, "beat_schedule is empty — nothing would ever run"


def test_every_beat_task_is_registered(
    beat_task_names: dict[str, str], registered_task_names: set[str]
):
    """The guard that would have caught #791's unregistered top-up task."""
    missing = {
        entry: task for entry, task in beat_task_names.items() if task not in registered_task_names
    }
    assert not missing, (
        "beat schedule references tasks no worker registers, so they dispatch "
        f"into nothing: {missing}. Add the defining module to "
        "juli_backend/workers/tasks/__init__.py."
    )


@pytest.mark.parametrize(
    "task_name",
    [
        "juli_backend.mock_analytics_hourly_reconcile",
        "juli_backend.cdp_batch_staggered_reconcile",
        "juli_backend.analytics_backfill_topup",
    ],
)
def test_known_scheduled_tasks_register(task_name: str, registered_task_names: set[str]):
    assert task_name in registered_task_names


def test_hourly_reconcile_runs_on_the_hour():
    """ADR-038 §5: the Demo KPI reconcile is hourly at :00.

    Pinned because a schedule change here stops gold being recomputed, which
    surfaces as stale or unavailable KPIs rather than as an error.
    """
    from celery.schedules import crontab

    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["mock-analytics-hourly-reconcile"]
    assert entry["task"] == "juli_backend.mock_analytics_hourly_reconcile"
    assert entry["schedule"] == crontab(minute=0)
