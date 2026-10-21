"""Every scheduled task must actually be registered on the worker.

`celery_app.autodiscover_tasks(["juli_backend.workers.tasks"])` imports the
*package*, not each module inside it. So a task file that nothing imports is never
registered, and Celery Beat happily dispatches to a name no worker claims — the
schedule silently does nothing, with no error anywhere.

#791 added analytics_backfill_topup with a beat entry but did not add it to
workers/tasks/__init__.py, so its 02:00 schedule could never have run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

# What a worker does at boot, run in a FRESH interpreter. Reading `celery_app.tasks`
# in this process would see every task module any earlier test imported, so a module
# missing from workers/tasks/__init__.py still looks registered whenever the suite
# happens to import it first. That is how `product_history` (P23's beat) went
# unregistered in production while this test stayed green in the full run (fast
# track P53, D62).
_FRESH_WORKER_REGISTRY = """
import json
from juli_backend.workers.celery_app import celery_app
celery_app.loader.import_default_modules()
print(json.dumps(sorted(celery_app.tasks)))
"""


@pytest.fixture(scope="module")
def registered_task_names() -> set[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    # The fresh interpreter must not reach a real database or broker; the import
    # path only needs the boot-time variables tests/conftest.py defaults.
    env["DATABASE_URL"] = ""
    env.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-collection-default")
    env.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
    out = subprocess.run(
        [sys.executable, "-c", _FRESH_WORKER_REGISTRY],
        capture_output=True,
        text=True,
        env=env,
        timeout=25,
        check=False,
    )
    assert out.returncode == 0, f"fresh worker import failed:\n{out.stderr[-2000:]}"
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


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
        "juli_backend.cdp_batch_staggered_reconcile",
        "juli_backend.product_history_fanout",
    ],
)
def test_known_scheduled_tasks_register(task_name: str, registered_task_names: set[str]):
    assert task_name in registered_task_names


def test_the_reference_shop_beats_are_retired():
    """P61-D (owner D72.5): both DEMO_REFERENCE_SHOP_ID beats went with /v1/demo/analytics."""
    from juli_backend.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    for name in ("mock-analytics-hourly-reconcile", "analytics-backfill-topup"):
        assert name not in schedule
    tasks = {entry["task"] for entry in schedule.values()}
    assert "juli_backend.mock_analytics_hourly_reconcile" not in tasks
    assert "juli_backend.analytics_backfill_topup" not in tasks


# ---------------------------------------------------------------------------
# Collision guard (#1659)
# ---------------------------------------------------------------------------


def _fire_minutes(schedule) -> set[tuple[int, int]]:
    """Every (hour, minute) a crontab fires in a day, resolved from the schedule.

    Read off `crontab.hour` / `crontab.minute`, which Celery has already expanded
    from whatever string or kwargs built it. Comparing the cron STRINGS would
    miss `minute=0` colliding with `minute="*/30"` — the two look nothing alike
    and fire together twice an hour.
    """
    return {(h, m) for h in schedule.hour for m in schedule.minute}


def _daily_beats(beat_schedule) -> dict[str, object]:
    """Beats that fire at most once a day. These are the heavy, batch ones."""
    return {
        name: entry["schedule"]
        for name, entry in beat_schedule.items()
        if len(_fire_minutes(entry["schedule"])) == 1
    }


def test_no_two_daily_beats_share_a_fire_minute():
    """#1659: two daily batch beats in one minute took both of them down.

    `analytics_backfill_topup` was `crontab(hour=2, minute=0)` and the hourly
    reconcile is `crontab(minute=0)`, so at 02:00 UTC they fired 7ms apart. Both
    work `analytics_performance_intervals`; the contention pushed a single-row
    UPDATE past the 2-minute `statement_timeout` and both tasks raised.

    The evidence was the hour: the reconcile succeeded at 16 consecutive hours
    and failed only at 02:00.
    """
    from juli_backend.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    daily = _daily_beats(schedule)

    seen: dict[tuple[int, int], str] = {}
    for name, cron in sorted(daily.items()):
        (slot,) = _fire_minutes(cron)
        clash = seen.get(slot)
        assert clash is None, (
            f"{name} and {clash} both fire at {slot[0]:02d}:{slot[1]:02d} UTC. "
            "Two daily batch beats in one minute is what #1659 was."
        )
        seen[slot] = name
