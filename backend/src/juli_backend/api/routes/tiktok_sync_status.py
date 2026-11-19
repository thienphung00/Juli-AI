"""``GET /v1/shops/me/sync-status`` -- backfill progress and data freshness (P101 W2 B-5).

HTTP skin only: the shop comes from ``X-Shop-Id`` (tenant-scoped, 404 for a
shop that is not the caller's), the behaviour lives in
``services.tiktok_sync_status``. Read-only, no TikTok call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import Shop, get_session
from juli_backend.services.tiktok_sync_status import shop_sync_status

router = APIRouter(prefix="/shops", tags=["shops"])


class SyncStatusResponse(BaseModel):
    state: str
    backfilling: bool
    history_days_done: int
    history_days_total: int
    #: ISO date of the last fully fetched analytics day, or null before any landed.
    data_through: str | None
    late: bool


@router.get("/me/sync-status", response_model=SyncStatusResponse)
async def get_current_shop_sync_status(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Connection state, days backfilled out of 90, and the data-through date."""
    return (await shop_sync_status(session, shop.id)).to_json()
