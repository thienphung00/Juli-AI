"""Single-shop daily scoring pipeline: aggregates → signals → recommendations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories.repos import ProductsRepo
from juli_backend.services.aggregates.builder import build_feature_aggregates
from juli_backend.services.aggregates.types import ShopLifecycleContext
from juli_backend.services.scoring.copy_layer import build_reasoning_for_recommendations
from juli_backend.services.scoring.recommendations import rank_workflow_recommendations
from juli_backend.services.scoring.signals import compute_scoring_signals
from juli_backend.services.scoring.types import DailyScoringResult


async def run_daily_scoring_for_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    lifecycle: ShopLifecycleContext | None = None,
    computed_at: datetime | None = None,
    list_limit: int = 10_000,
) -> DailyScoringResult:
    """Run rules-based scoring for one shop over synced Postgres aggregates."""
    lifecycle = lifecycle or ShopLifecycleContext()
    computed_at = computed_at or datetime.now(UTC)

    aggregates = await build_feature_aggregates(
        session,
        shop_id,
        lifecycle=lifecycle,
        list_limit=list_limit,
        computed_at=computed_at,
    )
    products = await ProductsRepo(session).list(shop_id, limit=list_limit)
    signals = compute_scoring_signals(
        aggregates,
        lifecycle=lifecycle,
        computed_at=computed_at,
        products=products,
    )
    recommendations = rank_workflow_recommendations(aggregates.shop_profile, signals)
    reasoning_summaries = build_reasoning_for_recommendations(recommendations, signals)

    return DailyScoringResult(
        aggregates=aggregates,
        signals=signals,
        recommendations=recommendations,
        reasoning_summaries=reasoning_summaries,
    )
