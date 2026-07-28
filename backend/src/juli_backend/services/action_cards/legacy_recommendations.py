"""Legacy recommendations table writes — sole owner for retained recommendations rows."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.recommendations import (
    get_host_product_matching,
    get_product_push_suggestions,
)
from juli_backend.repositories.repos import RecommendationsRepo


async def persist_legacy_recommendations(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> None:
    """Upsert rule-based recommendations from the recommendations engine."""
    repo = RecommendationsRepo(session)
    expires = datetime.now(UTC).replace(hour=23, minute=59, second=59, microsecond=0)

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
