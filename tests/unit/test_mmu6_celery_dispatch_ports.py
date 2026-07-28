"""MMU-6 (#554): domain dispatch ports must not import workers.tasks."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PREFIX = "juli_backend.workers.tasks"


def _collect_import_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _assert_no_workers_tasks_import(relative_path: str) -> None:
    py_file = REPO_ROOT / relative_path
    modules = _collect_import_modules(py_file)
    offenders = {
        m for m in modules if m == FORBIDDEN_PREFIX or m.startswith(f"{FORBIDDEN_PREFIX}.")
    }
    assert not offenders, f"{relative_path} imports workers.tasks: {sorted(offenders)}"


def test_mmu6_action_cards_dispatch_does_not_import_workers_tasks():
    """AC: action_cards dispatch stays free of workers.tasks imports."""
    _assert_no_workers_tasks_import("backend/src/juli_backend/services/action_cards/dispatch.py")


def test_mmu6_execution_dispatch_does_not_import_workers_tasks():
    """AC: execution dispatch stays free of workers.tasks imports."""
    _assert_no_workers_tasks_import("backend/src/juli_backend/services/execution/dispatch.py")


def test_mmu6_celery_delay_apply_async_only_in_workers_binding_refresh():
    """Binding layer enqueues refresh_action_cards.delay with shop_id."""
    from juli_backend.workers.dispatch_binding import CeleryRefreshDispatcher

    mock_task = MagicMock()
    mock_async = MagicMock()
    mock_async.id = "refresh-task-554"
    mock_task.delay.return_value = mock_async

    with patch(
        "juli_backend.workers.tasks.action_card_refresh.refresh_action_cards",
        mock_task,
    ):
        task_id = CeleryRefreshDispatcher().enqueue("shop-554")

    assert task_id == "refresh-task-554"
    mock_task.delay.assert_called_once_with("shop-554")


def test_mmu6_celery_task_dispatcher_enqueues_execute_approved_tool():
    """Binding layer enqueues execute_approved_tool.delay with execution_id."""
    from juli_backend.workers.dispatch_binding import CeleryTaskDispatcher

    mock_task = MagicMock()
    mock_async = MagicMock()
    mock_async.id = "exec-task-554"
    mock_task.delay.return_value = mock_async

    with patch(
        "juli_backend.workers.tasks.tool_execution.execute_approved_tool",
        mock_task,
    ):
        task_id = CeleryTaskDispatcher().enqueue("exec-554")

    assert task_id == "exec-task-554"
    mock_task.delay.assert_called_once_with("exec-554")


def test_mmu6_bind_celery_dispatchers_wires_domain_injectors():
    """Startup binding registers Celery adapters on domain injectors."""
    from juli_backend.services.action_cards import dispatch as action_dispatch
    from juli_backend.services.execution import dispatch as execution_dispatch
    from juli_backend.services.execution import outcome_port
    from juli_backend.workers.dispatch_binding import bind_celery_dispatchers

    action_dispatch.set_refresh_dispatcher(None)
    execution_dispatch.set_task_dispatcher(None)
    outcome_port.set_workflow_outcome_recorder(None)

    bind_celery_dispatchers()

    refresh = action_dispatch.get_refresh_dispatcher()
    task = execution_dispatch.get_task_dispatcher()
    recorder = outcome_port.get_workflow_outcome_recorder()
    assert refresh.__class__.__name__ == "CeleryRefreshDispatcher"
    assert task.__class__.__name__ == "CeleryTaskDispatcher"
    assert recorder.__class__.__name__ == "OperationsWorkflowOutcomeRecorder"

    action_dispatch.set_refresh_dispatcher(None)
    execution_dispatch.set_task_dispatcher(None)
    outcome_port.set_workflow_outcome_recorder(None)


def test_mmu6_unbound_refresh_dispatcher_raises():
    """Domain get_refresh_dispatcher raises when Celery binding not wired."""
    from juli_backend.services.action_cards.dispatch import (
        get_refresh_dispatcher,
        set_refresh_dispatcher,
    )

    set_refresh_dispatcher(None)
    with pytest.raises(RuntimeError, match="refresh dispatcher"):
        get_refresh_dispatcher()
    set_refresh_dispatcher(None)


def test_mmu6_unbound_task_dispatcher_raises():
    """Domain get_task_dispatcher raises when Celery binding not wired."""
    from juli_backend.services.execution.dispatch import (
        get_task_dispatcher,
        set_task_dispatcher,
    )

    set_task_dispatcher(None)
    with pytest.raises(RuntimeError, match="task dispatcher"):
        get_task_dispatcher()
    set_task_dispatcher(None)


def test_mmu6_cycle_audit_no_action_cards_execution_workers_tasks_edges():
    """AC: import graph has no action_cards or execution → workers.tasks edges."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "agent-runtime" / "scripts" / "ci"))
    from common import collect_import_graph, parse_architecture_map

    modules = parse_architecture_map(repo_root / "docs" / "architecture" / "map.md")
    graph = collect_import_graph(modules)

    action_cards = "backend/src/juli_backend/services/action_cards"
    execution = "backend/src/juli_backend/services/execution"
    workers_tasks_prefix = "backend/src/juli_backend/workers/tasks"

    offenders: list[str] = []
    for owner in (action_cards, execution):
        for imported in graph.get(owner, set()):
            if imported.startswith(workers_tasks_prefix):
                offenders.append(f"{owner} -> {imported}")

    assert not offenders, f"domain modules import workers.tasks: {offenders}"
