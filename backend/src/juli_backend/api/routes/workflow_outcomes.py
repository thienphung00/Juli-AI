"""Workflow outcome metrics API — P2-B5 / Issue #306."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import NotFound, Shop, get_session
from juli_backend.services.operations.outcome_tracking import load_workflow_outcome_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow-outcomes", tags=["workflow-outcomes"])


class WorkflowOutcomeMetricsResponse(BaseModel):
    success: bool = True
    data: dict | None = None
    error: str | None = None


@router.get("/{approval_id}", response_model=WorkflowOutcomeMetricsResponse)
async def get_workflow_outcome_metrics(
    approval_id: str,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> WorkflowOutcomeMetricsResponse:
    """Return persisted workflow_outcome_metrics for internal validation."""
    try:
        metrics = await load_workflow_outcome_metrics(session, shop.id, approval_id)
    except NotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception(
            "workflow_outcome_load_failed",
            extra={"shop_id": str(shop.id), "approval_id": approval_id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load workflow outcome metrics",
        ) from None

    return WorkflowOutcomeMetricsResponse(data=metrics)
