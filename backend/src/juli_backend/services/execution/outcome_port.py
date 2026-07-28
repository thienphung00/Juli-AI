"""Injectable port for workflow outcome recording — MMU-7 / #555."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution


class WorkflowOutcomeRecorder(Protocol):
    async def record_workflow_outcome(
        self,
        session: AsyncSession,
        execution: ToolExecution,
        *,
        execution_status: str,
        error_message: str | None = None,
    ) -> Any: ...


_outcome_recorder: WorkflowOutcomeRecorder | None = None


def get_workflow_outcome_recorder() -> WorkflowOutcomeRecorder:
    if _outcome_recorder is None:
        raise RuntimeError(
            "Workflow outcome recorder is not bound; call bind_celery_dispatchers() at startup"
        )
    return _outcome_recorder


def set_workflow_outcome_recorder(recorder: WorkflowOutcomeRecorder | None) -> None:
    global _outcome_recorder
    _outcome_recorder = recorder
