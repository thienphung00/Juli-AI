"""Dispatch-bound tasks must be registered on the worker (issue #1287).

`dispatch_binding.py` contains lazy imports of task modules that are not on the
beat schedule but are enqueued directly by API endpoints (via domain services).

Like `task_routes`, these tasks must be registered, or the worker answers
`Received unregistered task ... KeyError` when the API enqueues one.

This test pins every task referenced by `dispatch_binding.py`'s enqueue adapters
against future omissions — if a new dispatch-bound task is added without updating
`workers/tasks/__init__.py`, this test fails instead of shipping a silent defect.
"""

from __future__ import annotations


def test_dispatch_bound_tasks_are_registered():
    """Every task enqueued by dispatch_binding.py adapters must be registered.

    The defect #1287 caught: action_card_refresh and tool_execution modules
    were never imported in workers/tasks/__init__.py, so refresh_action_cards
    and execute_approved_tool never registered, even though dispatch_binding.py
    tried to enqueue them.
    """
    from juli_backend.workers import tasks as _tasks  # noqa: F401 -- triggers registration
    from juli_backend.workers.celery_app import celery_app

    # These are the task names enqueued by dispatch_binding.py's adapters
    dispatch_bound_tasks = {
        "juli_backend.refresh_action_cards",  # CeleryRefreshDispatcher.enqueue
        "juli_backend.execute_approved_tool",  # CeleryTaskDispatcher.enqueue
    }

    missing = sorted(name for name in dispatch_bound_tasks if name not in celery_app.tasks)
    assert not missing, (
        f"{missing} are enqueued by dispatch_binding.py adapters but not registered "
        "with the worker. Import their module in workers/tasks/__init__.py -- "
        "autodiscover_tasks imports the package, not each module, so an unimported "
        "task file registers nowhere."
    )


def test_refresh_action_cards_is_registered():
    """Explicitly pin refresh_action_cards, referenced by CeleryRefreshDispatcher."""
    from juli_backend.workers import tasks as _tasks  # noqa: F401
    from juli_backend.workers.celery_app import celery_app

    assert "juli_backend.refresh_action_cards" in celery_app.tasks, (
        "refresh_action_cards is not registered; CeleryRefreshDispatcher.enqueue() "
        "will fail at runtime"
    )


def test_execute_approved_tool_is_registered():
    """Explicitly pin execute_approved_tool, referenced by CeleryTaskDispatcher."""
    from juli_backend.workers import tasks as _tasks  # noqa: F401
    from juli_backend.workers.celery_app import celery_app

    assert "juli_backend.execute_approved_tool" in celery_app.tasks, (
        "execute_approved_tool is not registered; CeleryTaskDispatcher.enqueue() "
        "will fail at runtime"
    )
