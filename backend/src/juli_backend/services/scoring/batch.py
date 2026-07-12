"""Batch entry point for daily UTC scoring (#303)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop
from juli_backend.services.aggregates.types import ShopLifecycleContext
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.types import DailyScoringResult

LifecycleForShopFn = Callable[[uuid.UUID], ShopLifecycleContext]


async def _list_active_shop_ids(session: AsyncSession) -> list[uuid.UUID]:
    stmt = select(Shop.id).where(Shop.is_active.is_(True))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def run_daily_scoring_batch(
    session: AsyncSession,
    *,
    shop_ids: list[uuid.UUID] | None = None,
    lifecycle_for_shop: LifecycleForShopFn | None = None,
    computed_at: datetime | None = None,
) -> list[DailyScoringResult]:
    """Score all active shops (or an explicit subset) from synced aggregates."""
    computed_at = computed_at or datetime.now(UTC)
    lifecycle_for_shop = lifecycle_for_shop or (lambda _shop_id: ShopLifecycleContext())
    target_ids = shop_ids if shop_ids is not None else await _list_active_shop_ids(session)

    results: list[DailyScoringResult] = []
    for shop_id in target_ids:
        lifecycle = lifecycle_for_shop(shop_id)
        results.append(
            await run_daily_scoring_for_shop(
                session,
                shop_id,
                lifecycle=lifecycle,
                computed_at=computed_at,
            )
        )
    return results
