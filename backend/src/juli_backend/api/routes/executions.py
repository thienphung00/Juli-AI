"""Approved tool execution API — enqueue to Celery, query status (#305)."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import NotFound, Shop, get_session
from juli_backend.repositories.repos import ToolExecutionsRepo
from juli_backend.services.execution.dispatch import enqueue_approved_tool
from juli_backend.services.execution.types import ExecutionStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/executions", tags=["executions"])


class ExecutionEnqueueRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)


class ExecutionEnqueueData(BaseModel):
    execution_id: uuid.UUID
    status: str
    celery_task_id: str | None = None


class ExecutionEnqueueResponse(BaseModel):
    success: bool = True
    data: ExecutionEnqueueData | None = None
    error: str | None = None


class ExecutionStatusData(BaseModel):
    execution_id: uuid.UUID
    approval_id: str
    tool_name: str
    status: str
    celery_task_id: str | None = None
    outcome: dict | None = None
    error: str | None = None


class ExecutionStatusResponse(BaseModel):
    success: bool = True
    data: ExecutionStatusData | None = None
    error: str | None = None


@router.post("", response_model=ExecutionEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_execution(
    body: ExecutionEnqueueRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ExecutionEnqueueResponse:
    """Enqueue an approved tool call — never executes inline in the HTTP handler."""
    try:
        record = await enqueue_approved_tool(
            session,
            shop_id=shop.id,
            approval_id=body.approval_id,
            tool_name=body.tool_name,
            payload=body.payload,
        )
        await session.commit()
    except ValueError as exc:
        logger.warning(
            "execution_enqueue_validation_failed",
            extra={"shop_id": str(shop.id), "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception(
            "execution_enqueue_failed",
            extra={"shop_id": str(shop.id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue execution",
        ) from None

    return ExecutionEnqueueResponse(
        data=ExecutionEnqueueData(
            execution_id=record.id,
            status=ExecutionStatus.QUEUED.value,
            celery_task_id=record.celery_task_id,
        )
    )


@router.get("/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(
    execution_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ExecutionStatusResponse:
    """Return persisted execution status and outcome."""
    repo = ToolExecutionsRepo(session)
    try:
        record = await repo.get(shop.id, execution_id)
    except NotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    outcome = None
    if record.outcome_json:
        outcome = json.loads(record.outcome_json)

    return ExecutionStatusResponse(
        data=ExecutionStatusData(
            execution_id=record.id,
            approval_id=record.approval_id,
            tool_name=record.tool_name,
            status=record.status,
            celery_task_id=record.celery_task_id,
            outcome=outcome,
            error=record.error_message,
        )
    )
