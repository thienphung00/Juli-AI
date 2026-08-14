"""Celery worker tasks.

Every module defining a task on the beat schedule must be imported here.
celery_app.autodiscover_tasks imports this package, not each module in it, so a
task file that is never imported registers nowhere — beat then dispatches to a
name no worker claims and the schedule silently does nothing.
test_beat_schedule_tasks_are_registered pins this.
"""

from juli_backend.workers.tasks import (
    analytics_backfill_topup,  # noqa: F401
    cdp_batch_reconcile,  # noqa: F401
    impact_reader,  # noqa: F401
    mock_analytics_reconcile,  # noqa: F401
    reaper,  # noqa: F401
)
