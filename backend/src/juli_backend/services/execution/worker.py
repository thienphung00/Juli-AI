"""Async worker-side execution logic for approved tool calls."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import ToolExecutionsRepo
from juli_backend.services.execution.dispatch import mark_execution_finished
from juli_backend.services.execution.runner import run_tool
from juli_backend.services.execution.types import ExecutionStatus

logger = logging.getLogger(__name__)


async def run_approved_tool(session: AsyncSession, execution_id: uuid.UUID) -> None:
    repo = ToolExecutionsRepo(session)
    record = await repo.get_by_id(execution_id)
    await repo.update_status(
        record.shop_id,
        record.id,
        status=ExecutionStatus.RUNNING.value,
    )
    payload = json.loads(record.payload_json or "{}")
    try:
        outcome = run_tool(record.tool_name, payload)
    except Exception as exc:
        logger.exception(
            "tool_execution_failed",
            extra={"execution_id": str(execution_id), "tool_name": record.tool_name},
        )
        await mark_execution_finished(
            session,
            record.shop_id,
            record.id,
            status=ExecutionStatus.FAILED,
            error_message=str(exc),
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
    await session.commit()
