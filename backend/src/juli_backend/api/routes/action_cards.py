"""Action Card API — manual refresh and persisted listing (#303, ADR-021)."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.repositories.repos import ActionCardsRepo
from juli_backend.services.action_cards.dispatch import enqueue_action_card_refresh

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/action-cards", tags=["action-cards"])


class ActionCardRefreshData(BaseModel):
    status: str
    celery_task_id: str


class ActionCardRefreshResponse(BaseModel):
    success: bool = True
    data: ActionCardRefreshData | None = None
    error: str | None = None


class ActionCardItem(BaseModel):
    id: uuid.UUID
    workflow_key: str
    priority: int
    severity: str
    title: str
    description: str
    status: str
    recommendation: dict
    metadata: dict | None = None
    created_at: str
    updated_at: str


class ActionCardsListResponse(BaseModel):
    success: bool = True
    data: list[ActionCardItem]
    error: str | None = None


@router.post(
    "/refresh",
    response_model=ActionCardRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_action_cards(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ActionCardRefreshResponse:
    """Enqueue manual refresh — never runs the pipeline inline."""
    try:
        celery_task_id = await enqueue_action_card_refresh(session, shop_id=shop.id)
    except Exception:
        logger.exception(
            "action_card_refresh_enqueue_failed",
            extra={"shop_id": str(shop.id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue action card refresh",
        ) from None

    return ActionCardRefreshResponse(
        data=ActionCardRefreshData(status="queued", celery_task_id=celery_task_id)
    )


@router.get("", response_model=ActionCardsListResponse)
async def list_action_cards(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> ActionCardsListResponse:
    """Return persisted action cards for the active shop — no regeneration."""
    repo = ActionCardsRepo(session)
    rows = await repo.list_active(shop.id)
    return ActionCardsListResponse(data=[_to_item(row) for row in rows])


def _to_item(row) -> ActionCardItem:
    recommendation: dict = {}
    if row.recommendation_payload:
        try:
            recommendation = json.loads(row.recommendation_payload)
        except json.JSONDecodeError:
            recommendation = {"raw": row.recommendation_payload}

    metadata = None
    if row.metadata_json:
        try:
            metadata = json.loads(row.metadata_json)
        except json.JSONDecodeError:
            metadata = {"raw": row.metadata_json}

    return ActionCardItem(
        id=row.id,
        workflow_key=row.workflow_key,
        priority=row.priority,
        severity=row.severity,
        title=row.title,
        description=row.description,
        status=row.status,
        recommendation=recommendation,
        metadata=metadata,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )
