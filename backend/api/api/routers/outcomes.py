"""Campaign outcome recording — P1-3 / Issue #94."""

import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.api.dependencies import get_active_shop
from backend.integrations.catalog.domain.feedback import ingest_campaign_outcome
from backend.database import Shop, get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


class OutcomeIngestRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    creator_id: uuid.UUID
    product_ids: list[uuid.UUID] = Field(min_length=1)
    realized_gmv: Decimal = Field(gt=0)
    realized_conversion: Decimal | None = Field(default=None, ge=0, le=1)
    predicted_gmv: Decimal | None = Field(default=None, gt=0)
    predicted_conversion: Decimal | None = Field(default=None, ge=0, le=1)
    campaign_id: uuid.UUID | None = None


class OutcomeIngestData(BaseModel):
    campaign_id: uuid.UUID
    idempotency_key: str
    is_duplicate: bool
    edge_count: int
    calibration_weight: float | None = None


class OutcomeIngestResponse(BaseModel):
    success: bool = True
    data: OutcomeIngestData | None = None
    error: str | None = None


@router.post("", response_model=OutcomeIngestResponse)
async def record_outcome(
    body: OutcomeIngestRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> OutcomeIngestResponse:
    """Record realized campaign outcomes for calibration (P1-3)."""
    try:
        result = await ingest_campaign_outcome(
            session,
            shop.id,
            idempotency_key=body.idempotency_key,
            creator_id=body.creator_id,
            product_ids=body.product_ids,
            realized_gmv=body.realized_gmv,
            realized_conversion=body.realized_conversion,
            predicted_gmv=body.predicted_gmv,
            predicted_conversion=body.predicted_conversion,
            campaign_id=body.campaign_id,
        )
    except ValueError as exc:
        logger.warning(
            "outcome_ingest_validation_failed",
            extra={"shop_id": str(shop.id), "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception(
            "outcome_ingest_failed",
            extra={"shop_id": str(shop.id)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record outcome",
        ) from None

    weight: float | None = None
    if result.calibration_weight is not None:
        weight = float(result.calibration_weight)

    return OutcomeIngestResponse(
        data=OutcomeIngestData(
            campaign_id=result.campaign_id,
            idempotency_key=result.idempotency_key,
            is_duplicate=result.is_duplicate,
            edge_count=result.edge_count,
            calibration_weight=weight,
        )
    )
