"""Celery worker tasks.

Every module defining a task on the beat schedule must be imported here.
celery_app.autodiscover_tasks imports this package, not each module in it, so a
task file that is never imported registers nowhere — beat then dispatches to a
name no worker claims and the schedule silently does nothing.
test_beat_schedule_tasks_are_registered pins this.

Issue #1207: the same trap catches API-dispatched tasks, which that beat test
does not cover. `agent_workflow` was missing here, so `run_agent_workflow` and
`resume_agent_workflow` were never registered and the worker answered
`Received unregistered task ... KeyError` when the API enqueued one.
`test_routed_tasks_are_registered` now pins every task in `task_routes` too.

Every name below is declared in `__all__` rather than suppressed with
`# noqa: F401` — the imports are for their side effect (Celery task
registration), but the names themselves are this package's public surface,
so declaring them exported is accurate, not a workaround, and ruff's F401
does not fire against a name listed in `__all__`.
"""

from juli_backend.workers.tasks import (
    action_card_refresh,
    agent_workflow,
    analytics_backfill_topup,
    cdp_batch_reconcile,
    credential_refresh_beat,
    fujiwa_poll_beat,
    impact_reader,
    mock_analytics_reconcile,
    reaper,
    tool_execution,
)

__all__ = [
    "action_card_refresh",
    "agent_workflow",
    "analytics_backfill_topup",
    "cdp_batch_reconcile",
    "credential_refresh_beat",
    "fujiwa_poll_beat",
    "impact_reader",
    "mock_analytics_reconcile",
    "reaper",
    "tool_execution",
]
