"""Workers binding: Celery dispatch adapters for domain enqueue ports (MMU-6 / #554)."""

from __future__ import annotations

from dataclasses import dataclass

from juli_backend.services.action_cards.dispatch import set_refresh_dispatcher
from juli_backend.services.execution.dispatch import set_task_dispatcher


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


def bind_celery_dispatchers() -> None:
    """Register production Celery adapters on domain injectors (API + worker startup)."""
    set_refresh_dispatcher(CeleryRefreshDispatcher())
    set_task_dispatcher(CeleryTaskDispatcher())
