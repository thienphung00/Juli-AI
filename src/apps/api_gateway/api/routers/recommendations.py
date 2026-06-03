import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.apps.api_gateway.api.dependencies import get_active_shop
from src.shared.utils.data import RecommendationsRepo, Shop, get_session
from src.shared.utils.data.models import Recommendation
from src.modules.catalog.domain.recommendations import (
    get_host_product_matching,
    get_product_push_suggestions,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class PredictedOutcomePayload(BaseModel):
    gmv_vnd_week: dict[str, int]
    conversion_pct: float
    engagement_index: float
    risk_factors: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    id: uuid.UUID
    recommendation_type: str
    message: str
    cta: str
    match_score: float | None = None
    confidence: str | None = None
    action_type: str | None = None
    predicted_outcome: PredictedOutcomePayload | None = None
    source: str | None = None
    computed_at: str | None = None
    payload: dict | None = None


class RecommendationsResponse(BaseModel):
    success: bool = True
    data: list[RecommendationItem]
    error: str | None = None


@router.get("", response_model=RecommendationsResponse)
async def list_recommendations(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> RecommendationsResponse:
    """Return current active recommendations with CTAs for the shop."""
    rows = await _list_active(session, shop.id)
    if not rows:
        await _refresh_recommendations(session, shop.id)
        rows = await _list_active(session, shop.id)
    return RecommendationsResponse(data=[_to_item(row) for row in rows])


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _list_active(
    session: AsyncSession, shop_id: uuid.UUID
) -> list[Recommendation]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(Recommendation)
        .where(
            Recommendation.shop_id == shop_id,
            Recommendation.status == "active",
        )
        .order_by(Recommendation.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    return [
        row
        for row in rows
        if row.expires_at is None or _as_utc(row.expires_at) > now
    ]


async def _refresh_recommendations(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Upsert rule-based recommendations from the recommendations engine."""
    repo = RecommendationsRepo(session)
    expires = datetime.now(timezone.utc).replace(
        hour=23, minute=59, second=59, microsecond=0
    )

    push_suggestions = await get_product_push_suggestions(session, shop_id, limit=5)
    for suggestion in push_suggestions:
        await repo.create(
            shop_id=shop_id,
            recommendation_type="product_push",
            status="active",
            expires_at=expires,
            payload=json.dumps(
                {
                    "message": suggestion.message,
                    "cta": suggestion.cta,
                    "tiktok_product_id": suggestion.tiktok_product_id,
                    "product_name": suggestion.product_name,
                    "sku_id": suggestion.sku_id,
                    "composite_score": suggestion.composite_score,
                }
            ),
        )

    matches = await get_host_product_matching(session, shop_id, limit=3)
    for match in matches:
        await repo.create(
            shop_id=shop_id,
            recommendation_type="host_product_match",
            status="active",
            expires_at=expires,
            payload=json.dumps(
                {
                    "message": match.message,
                    "cta": match.cta,
                    "creator_id": match.creator_id,
                    "creator_name": match.creator_name,
                    "tiktok_product_id": match.tiktok_product_id,
                    "product_name": match.product_name,
                    "match_score": match.match_score,
                    "source": match.source,
                    "action_type": match.action_type,
                    "confidence": match.confidence,
                    "computed_at": match.computed_at.isoformat(),
                    "predicted_outcome": {
                        "gmv_vnd_week": match.predicted_outcome.gmv_vnd_week,
                        "conversion_pct": match.predicted_outcome.conversion_pct,
                        "engagement_index": match.predicted_outcome.engagement_index,
                        "risk_factors": match.predicted_outcome.risk_factors,
                    },
                }
            ),
        )


def _to_item(row: Recommendation) -> RecommendationItem:
    payload: dict = {}
    message = ""
    cta = ""
    if row.payload:
        try:
            payload = json.loads(row.payload)
            message = str(payload.get("message", ""))
            cta = str(payload.get("cta", ""))
        except json.JSONDecodeError:
            payload = {"raw": row.payload}

    predicted_raw = payload.get("predicted_outcome")
    predicted: PredictedOutcomePayload | None = None
    if isinstance(predicted_raw, dict):
        predicted = PredictedOutcomePayload(
            gmv_vnd_week=predicted_raw.get("gmv_vnd_week", {"low": 0, "high": 0}),
            conversion_pct=float(predicted_raw.get("conversion_pct", 0)),
            engagement_index=float(predicted_raw.get("engagement_index", 0)),
            risk_factors=list(predicted_raw.get("risk_factors", [])),
        )

    match_score = payload.get("match_score")
    if isinstance(match_score, (int, float)):
        match_score_val: float | None = float(match_score)
    else:
        match_score_val = None

    return RecommendationItem(
        id=row.id,
        recommendation_type=row.recommendation_type,
        message=message,
        cta=cta,
        match_score=match_score_val,
        confidence=payload.get("confidence") if isinstance(payload.get("confidence"), str) else None,
        action_type=payload.get("action_type") if isinstance(payload.get("action_type"), str) else None,
        predicted_outcome=predicted,
        source=payload.get("source") if isinstance(payload.get("source"), str) else None,
        computed_at=payload.get("computed_at") if isinstance(payload.get("computed_at"), str) else None,
        payload=payload or None,
    )
