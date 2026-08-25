"""Action Card API — manual refresh and persisted listing (#303, ADR-021).

On-demand reorder inputs for inventory advisory (#721).
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.forecasting import compute_reorder_quantity, get_low_stock_risks
from juli_backend.api.tenant_context_middleware import get_active_shop_and_set_context
from juli_backend.database import Shop, get_session
from juli_backend.repositories.repos import ActionCardsRepo
from juli_backend.services.action_cards import (
    enqueue_action_card_refresh,
    get_refresh_cooldown_gate,
)

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


class ReorderBasis(BaseModel):
    daily_velocity: float
    lead_time_days: int
    safety_stock_days: int
    days_until_stockout: float


class ActionCardInputsData(BaseModel):
    workflow_key: str
    sku_id: str | None = None
    tiktok_product_id: str | None = None
    current_stock: int | None = None
    reorder_quantity: float | None = None
    editable: bool = True
    basis: ReorderBasis | None = None


class ActionCardInputsResponse(BaseModel):
    success: bool = True
    data: ActionCardInputsData
    error: str | None = None


@router.post(
    "/refresh",
    response_model=ActionCardRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_action_cards(
    shop: Shop = Depends(get_active_shop_and_set_context),
    session: AsyncSession = Depends(get_session),
) -> ActionCardRefreshResponse:
    """Enqueue manual refresh — never runs the pipeline inline.

    Per-shop cooldown (#899, ADR-061 §2b): a second refresh for the same shop
    inside the cooldown window is rejected before enqueueing. This is the one
    app-level rate limit in the epic — it is keyed on shop identity, which
    Nginx (network-origin only, issue #898) cannot express.
    """
    decision = await get_refresh_cooldown_gate().try_acquire(str(shop.id))
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Action card refresh is on cooldown for this shop; "
                f"retry in {decision.retry_after_seconds}s"
            ),
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

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
    shop: Shop = Depends(get_active_shop_and_set_context),
    session: AsyncSession = Depends(get_session),
) -> ActionCardsListResponse:
    """Return persisted action cards for the active shop — no regeneration."""
    repo = ActionCardsRepo(session)
    rows = await repo.list_active(shop.id)
    return ActionCardsListResponse(data=[_to_item(row) for row in rows])


@router.get(
    "/{workflow_key}/inputs",
    response_model=ActionCardInputsResponse,
)
async def get_action_card_inputs(
    workflow_key: str,
    shop: Shop = Depends(get_active_shop_and_set_context),
    session: AsyncSession = Depends(get_session),
) -> ActionCardInputsResponse:
    """Compute on-demand reorder inputs for a workflow.

    Returns the highest-urgency low-stock risk with computed reorder quantity.
    Computed per-request; no persistence or scoring pipeline invocation.
    """
    risks = await get_low_stock_risks(session, shop.id)

    if not risks:
        # Empty state: well-formed 200 response with null subject
        return ActionCardInputsResponse(
            data=ActionCardInputsData(
                workflow_key=workflow_key,
                sku_id=None,
                tiktok_product_id=None,
                current_stock=None,
                reorder_quantity=None,
                editable=True,
                basis=None,
            )
        )

    # Use highest-urgency risk (first element after sort by urgency_score desc)
    risk = risks[0]
    reorder_qty = compute_reorder_quantity(risk)

    return ActionCardInputsResponse(
        data=ActionCardInputsData(
            workflow_key=workflow_key,
            sku_id=risk.sku_id,
            tiktok_product_id=risk.tiktok_product_id,
            current_stock=risk.quantity,
            reorder_quantity=reorder_qty,
            editable=True,
            basis=ReorderBasis(
                daily_velocity=risk.daily_velocity,
                lead_time_days=3,
                safety_stock_days=2,
                days_until_stockout=risk.days_until_stockout,
            ),
        )
    )


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
