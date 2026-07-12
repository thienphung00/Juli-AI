"""Enqueue approved tool calls to Celery — HTTP handlers must not run tools inline."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.repositories.repos import ToolExecutionsRepo
from juli_backend.services.execution.types import ExecutionStatus


class TaskDispatcher(Protocol):
    def enqueue(self, execution_id: str) -> str: ...


@dataclass
class CeleryTaskDispatcher:
    """Production dispatcher — enqueues the Celery worker task."""

    def enqueue(self, execution_id: str) -> str:
        from juli_backend.workers.tasks.tool_execution import execute_approved_tool

        async_result = execute_approved_tool.delay(execution_id)
        return async_result.id


@dataclass
class _DefaultDispatcher:
    def enqueue(self, execution_id: str) -> str:
        return CeleryTaskDispatcher().enqueue(execution_id)


_task_dispatcher: TaskDispatcher | None = None


def get_task_dispatcher() -> TaskDispatcher:
    global _task_dispatcher
    if _task_dispatcher is None:
        _task_dispatcher = _DefaultDispatcher()
    return _task_dispatcher


def set_task_dispatcher(dispatcher: TaskDispatcher | None) -> None:
    global _task_dispatcher
    _task_dispatcher = dispatcher


async def create_queued_execution(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    approval_id: str,
    tool_name: str,
    payload: dict[str, Any],
    celery_task_id: str | None = None,
) -> ToolExecution:
    repo = ToolExecutionsRepo(session)
    return await repo.create(
        shop_id=shop_id,
        approval_id=approval_id,
        tool_name=tool_name,
        payload_json=json.dumps(payload),
        status=ExecutionStatus.QUEUED.value,
        celery_task_id=celery_task_id,
    )


async def enqueue_approved_tool(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    approval_id: str,
    tool_name: str,
    payload: dict[str, Any],
) -> ToolExecution:
    record = await create_queued_execution(
        session,
        shop_id=shop_id,
        approval_id=approval_id,
        tool_name=tool_name,
        payload=payload,
    )
    celery_task_id = get_task_dispatcher().enqueue(str(record.id))
    return await ToolExecutionsRepo(session).set_celery_task_id(
        shop_id,
        record.id,
        celery_task_id,
    )


async def mark_execution_finished(
    session: AsyncSession,
    shop_id: uuid.UUID,
    execution_id: uuid.UUID,
    *,
    status: ExecutionStatus,
    outcome: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> ToolExecution:
    repo = ToolExecutionsRepo(session)
    return await repo.update_status(
        shop_id,
        execution_id,
        status=status.value,
        outcome_json=json.dumps(outcome) if outcome is not None else None,
        error_message=error_message,
    )
