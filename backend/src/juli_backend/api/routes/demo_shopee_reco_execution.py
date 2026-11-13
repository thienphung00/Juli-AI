"""Seller scope: Thực hiện and Đo lường of Quyết định (P100 redesign), read-only.

- ``GET /v1/demo/shopee/recommendations/execution`` -- approved cards with their state
  (cho_dien / da_dien / khop / lech), the Connector line.
- ``GET /v1/demo/shopee/recommendations/measurements`` -- executed cards with days measured, the
  card's Δ lợi nhuận band, the reading and the verdict.

Registered before the card routes (``/execution`` must not be read as a ``{card_id}``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.database import Shop, get_session
from juli_backend.services.shopee_recommendations import execution_state

router = APIRouter(prefix="/demo/shopee/recommendations", tags=["demo-shopee"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/execution")
async def get_execution(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await execution_state.execution_states(session, _shopee(shop), now=_now())


@router.get("/measurements")
async def get_measurements(
    shop: Shop = Depends(get_active_shop), session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    return await execution_state.measurement_states(session, _shopee(shop), now=_now())
