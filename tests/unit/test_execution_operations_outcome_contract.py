"""MMU-7 (#555): one-way execution → operations outcome contract."""

from __future__ import annotations

import ast
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, User

REPO_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_PREFIX = "juli_backend.services.execution"
OPERATIONS_PREFIX = "juli_backend.services.operations"


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


def _assert_no_import(relative_path: str, forbidden_prefix: str) -> None:
    py_file = REPO_ROOT / relative_path
    modules = _collect_import_modules(py_file)
    offenders = {
        m for m in modules if m == forbidden_prefix or m.startswith(f"{forbidden_prefix}.")
    }
    assert not offenders, f"{relative_path} imports {forbidden_prefix}: {sorted(offenders)}"


def test_mmu7_operations_outcome_tracking_does_not_import_execution():
    """AC1: operations must not import execution internals."""
    _assert_no_import(
        "backend/src/juli_backend/services/operations/outcome_tracking.py",
        EXECUTION_PREFIX,
    )


def test_mmu7_execution_worker_does_not_deep_import_operations_submodules():
    """AC1: worker uses the outcome port, not operations.outcome_tracking."""
    py_file = REPO_ROOT / "backend/src/juli_backend/services/execution/worker.py"
    modules = _collect_import_modules(py_file)
    offenders = {m for m in modules if m.startswith(f"{OPERATIONS_PREFIX}.")}
    assert not offenders, f"worker deep-imports operations: {sorted(offenders)}"


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000555")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="MMU-7 Outcome Contract Shop",
        tiktok_shop_id="tiktok_shop_555",
    )
    session.add(s)
    await session.flush()
    return s


@dataclass
class FakeOutcomeRecorder:
    calls: list[dict] = field(default_factory=list)

    async def record_workflow_outcome(
        self,
        session,
        execution,
        *,
        execution_status: str,
        error_message: str | None = None,
    ) -> dict:
        self.calls.append(
            {
                "execution_id": execution.id,
                "execution_status": execution_status,
                "error_message": error_message,
            }
        )
        return {"recorded": True}


@pytest_asyncio.fixture
async def bound_fake_outcome_recorder():
    from juli_backend.services.execution.outcome_port import set_workflow_outcome_recorder

    fake = FakeOutcomeRecorder()
    set_workflow_outcome_recorder(fake)
    yield fake
    set_workflow_outcome_recorder(None)


@pytest.mark.asyncio
async def test_mmu7_worker_records_outcome_via_port_with_fake(
    session,
    shop,
    bound_fake_outcome_recorder,
    monkeypatch,
):
    """AC3: terminal finish path records outcome through injectable port (fake)."""
    from juli_backend.models.models import ToolExecution
    from juli_backend.services.execution.types import ExecutionStatus
    from juli_backend.services.execution.worker import run_approved_tool

    record = ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop.id,
        approval_id="approval-555-fake",
        tool_name="noop.ping",
        payload_json=json.dumps({"workflow_id": "npl"}),
        status=ExecutionStatus.QUEUED.value,
    )
    session.add(record)
    await session.flush()

    async def _noop_tool(_session, _tool_name, _payload):
        return {"ok": True}

    monkeypatch.setattr(
        "juli_backend.services.execution.worker.run_tool_async",
        _noop_tool,
    )

    await run_approved_tool(session, record.id)

    assert len(bound_fake_outcome_recorder.calls) == 1
    call = bound_fake_outcome_recorder.calls[0]
    assert call["execution_id"] == record.id
    assert call["execution_status"] == ExecutionStatus.SUCCEEDED.value


def test_mmu7_bind_celery_dispatchers_wires_outcome_recorder():
    """AC2: startup binding registers operations adapter on execution port."""
    from juli_backend.services.execution import outcome_port
    from juli_backend.workers.dispatch_binding import bind_celery_dispatchers

    outcome_port.set_workflow_outcome_recorder(None)
    bind_celery_dispatchers()

    recorder = outcome_port.get_workflow_outcome_recorder()
    assert recorder.__class__.__name__ == "OperationsWorkflowOutcomeRecorder"

    outcome_port.set_workflow_outcome_recorder(None)


def test_mmu7_unbound_outcome_recorder_raises():
    """Port raises when outcome recorder is not wired."""
    from juli_backend.services.execution.outcome_port import (
        get_workflow_outcome_recorder,
        set_workflow_outcome_recorder,
    )
    from juli_backend.workers.dispatch_binding import bind_celery_dispatchers

    bind_celery_dispatchers()
    set_workflow_outcome_recorder(None)
    with pytest.raises(RuntimeError, match="outcome recorder"):
        get_workflow_outcome_recorder()
    bind_celery_dispatchers()


def test_mmu7_operations_adapter_delegates_to_public_api():
    """Binding adapter calls operations public record_workflow_outcome."""
    from juli_backend.workers.dispatch_binding import OperationsWorkflowOutcomeRecorder

    session = object()
    execution = object()
    with patch(
        "juli_backend.services.operations.record_workflow_outcome",
        autospec=True,
    ) as record:
        recorder = OperationsWorkflowOutcomeRecorder()
        import asyncio

        asyncio.run(
            recorder.record_workflow_outcome(
                session,
                execution,
                execution_status="succeeded",
            )
        )
        record.assert_called_once_with(
            session,
            execution,
            execution_status="succeeded",
            error_message=None,
        )


def test_mmu7_cycle_audit_no_operations_to_execution_edge():
    """AC4: import graph has no operations → execution edge."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
    from common import collect_import_graph, parse_architecture_map

    modules = parse_architecture_map(REPO_ROOT / "docs" / "architecture" / "map.md")
    graph = collect_import_graph(modules)

    operations = "backend/src/juli_backend/services/operations"
    execution_prefix = "backend/src/juli_backend/services/execution"

    offenders = [
        imported
        for imported in graph.get(operations, set())
        if imported.startswith(execution_prefix)
    ]
    assert not offenders, f"operations imports execution: {offenders}"


def test_outcome_recording_callable_from_execution_finish_via_public_api() -> None:
    """AC2 alias for validate acceptance mapping."""
    test_mmu7_bind_celery_dispatchers_wires_outcome_recorder()


def test_cycle_check_clean_for_execution_operations_pair() -> None:
    """AC4 alias for validate acceptance mapping."""
    test_mmu7_cycle_audit_no_operations_to_execution_edge()
