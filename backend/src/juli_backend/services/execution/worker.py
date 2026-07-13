"""Async worker-side execution logic for approved tool calls."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.repositories.repos import ToolExecutionsRepo
from juli_backend.services.execution.dispatch import mark_execution_finished
from juli_backend.services.execution.errors import classify_execution_error
from juli_backend.services.execution.runner import run_tool_async
from juli_backend.services.execution.types import ExecutionStatus
from juli_backend.services.operations.outcome_tracking import record_workflow_outcome

logger = logging.getLogger(__name__)


def _tool_payload(record: ToolExecution, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge persisted execution metadata into the handler payload."""
    enriched = dict(payload)
    if record.idempotency_key:
        enriched["idempotency_key"] = record.idempotency_key
    return enriched


async def run_approved_tool(session: AsyncSession, execution_id: uuid.UUID) -> None:
    repo = ToolExecutionsRepo(session)
    record = await repo.get_by_id(execution_id)
    await repo.update_status(
        record.shop_id,
        record.id,
        status=ExecutionStatus.RUNNING.value,
    )
    payload = _tool_payload(record, json.loads(record.payload_json or "{}"))
    try:
        outcome = await run_tool_async(session, record.tool_name, payload)
    except Exception as exc:
        error_category, error_message = classify_execution_error(exc)
        logger.exception(
            "tool_execution_failed",
            extra={
                "execution_id": str(execution_id),
                "tool_name": record.tool_name,
                "error_category": error_category.value,
            },
        )
        await mark_execution_finished(
            session,
            record.shop_id,
            record.id,
            status=ExecutionStatus.FAILED,
            error_message=error_message,
            error_category=error_category.value,
        )
        try:
            await record_workflow_outcome(
                session,
                record,
                execution_status=ExecutionStatus.FAILED,
                error_message=error_message,
            )
        except ValueError as outcome_exc:
            logger.warning(
                "workflow_outcome_skipped",
                extra={
                    "execution_id": str(execution_id),
                    "error": str(outcome_exc),
                },
            )
        await session.commit()
        raise

    await mark_execution_finished(
        session,
        record.shop_id,
        record.id,
        status=ExecutionStatus.SUCCEEDED,
        outcome=outcome,
    )
    try:
        await record_workflow_outcome(
            session,
            record,
            execution_status=ExecutionStatus.SUCCEEDED,
        )
    except ValueError as outcome_exc:
        logger.warning(
            "workflow_outcome_skipped",
            extra={
                "execution_id": str(execution_id),
                "error": str(outcome_exc),
            },
        )
    await session.commit()
