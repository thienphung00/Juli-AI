"""Workers binding: Celery dispatch adapters for domain enqueue ports (MMU-6 / #554)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.services.action_cards.dispatch import set_refresh_dispatcher
from juli_backend.services.execution.dispatch import set_task_dispatcher
from juli_backend.services.execution.outcome_port import set_workflow_outcome_recorder


@dataclass
class CeleryRefreshDispatcher:
    """Enqueue action-card refresh via Celery — lives in workers, not domain."""

    def enqueue(self, shop_id: str) -> str:
        from juli_backend.workers.tasks.action_card_refresh import refresh_action_cards

        async_result = refresh_action_cards.delay(shop_id)
        return async_result.id


@dataclass
class CeleryTaskDispatcher:
    """Enqueue approved tool execution via Celery — lives in workers, not domain."""

    def enqueue(self, execution_id: str) -> str:
        from juli_backend.workers.tasks.tool_execution import execute_approved_tool

        async_result = execute_approved_tool.delay(execution_id)
        return async_result.id


@dataclass
class OperationsWorkflowOutcomeRecorder:
    """Record workflow outcomes via operations public API — lives in workers, not domain."""

    async def record_workflow_outcome(
        self,
        session: AsyncSession,
        execution: ToolExecution,
        *,
        execution_status: str,
        error_message: str | None = None,
    ) -> Any:
        from juli_backend.services.operations import record_workflow_outcome

        return await record_workflow_outcome(
            session,
            execution,
            execution_status=execution_status,
            error_message=error_message,
        )


def bind_celery_dispatchers() -> None:
    """Register production Celery adapters on domain injectors (API + worker startup)."""
    set_refresh_dispatcher(CeleryRefreshDispatcher())
    set_task_dispatcher(CeleryTaskDispatcher())
    set_workflow_outcome_recorder(OperationsWorkflowOutcomeRecorder())
