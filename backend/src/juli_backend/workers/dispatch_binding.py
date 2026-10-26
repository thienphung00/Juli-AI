"""Workers binding: Celery dispatch adapters for domain enqueue ports (MMU-6 / #554)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.services.action_cards.dispatch import set_refresh_dispatcher
from juli_backend.services.execution.dispatch import set_task_dispatcher
from juli_backend.services.execution.outcome_port import set_workflow_outcome_recorder
from juli_backend.services.ingestion import set_bootstrap_dispatcher
from juli_backend.services.product_history import HistoryWork, set_history_enqueuer
from juli_backend.services.shop_diagnosis_daily import (
    REFRESH_DEBOUNCE_SECONDS,
    set_report_refresh_enqueuer,
)


@dataclass
class CeleryRefreshDispatcher:
    """Enqueue action-card refresh via Celery — lives in workers, not domain."""

    def enqueue(self, shop_id: str) -> str:
        from juli_backend.workers.tasks.action_card_refresh import refresh_action_cards

        async_result = refresh_action_cards.delay(shop_id)
        return async_result.id


@dataclass
class CeleryBootstrapDispatcher:
    """Enqueue a shop's bootstrap on the high-priority queue (fast track SPEC §3.1)."""

    def enqueue(
        self,
        shop_id: str,
        *,
        connect_committed_at: str | None,
        enqueued_at: str | None,
    ) -> str:
        from juli_backend.workers.tasks.shop_ingestion import enqueue_bootstrap

        return enqueue_bootstrap(
            shop_id, connect_committed_at=connect_committed_at, enqueued_at=enqueued_at
        )


@dataclass
class CeleryHistoryEnqueuer:
    """Enqueue a webhook's product / activity re-read (fast track P23, D30.4)."""

    def __call__(self, shop_id: str, work: HistoryWork) -> str | None:
        from juli_backend.workers.tasks.product_history import (
            product_history_refresh_activity,
            product_history_refresh_product,
        )

        if work.subject == "product":
            return product_history_refresh_product.delay(
                shop_id, work.subject_id, work.source, work.hint_kind, list(work.hint_fields)
            ).id
        return product_history_refresh_activity.delay(shop_id, work.change, work.source).id


@dataclass
class CeleryReportRefreshEnqueuer:
    """Enqueue a delayed stored-report rebuild after an order change (P68, B12)."""

    def __call__(self, shop_id: str) -> str | None:
        from juli_backend.workers.tasks.shop_diagnosis import enqueue_shop_diagnosis_refresh

        return enqueue_shop_diagnosis_refresh(shop_id, countdown=REFRESH_DEBOUNCE_SECONDS)


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
    set_bootstrap_dispatcher(CeleryBootstrapDispatcher())
    set_task_dispatcher(CeleryTaskDispatcher())
    set_workflow_outcome_recorder(OperationsWorkflowOutcomeRecorder())
    set_history_enqueuer(CeleryHistoryEnqueuer())
    set_report_refresh_enqueuer(CeleryReportRefreshEnqueuer())
