import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_active_shop
from src.data import LivestreamsRepo, Shop, get_session
from src.data.models import Livestream

router = APIRouter(prefix="/livestreams", tags=["livestreams"])


class LivestreamResponse(BaseModel):
    id: uuid.UUID
    tiktok_livestream_id: str
    creator_id: uuid.UUID | None = None
    title: str | None = None
    duration_seconds: int | None = None
    viewer_count: int | None = None
    peak_concurrent_viewers: int | None = None
    order_count: int | None = None
    revenue: str | None = None

    model_config = {"from_attributes": True}


class PaginatedLivestreams(BaseModel):
    items: list[LivestreamResponse]
    next_cursor: str | None = None


@router.get("", response_model=PaginatedLivestreams)
async def list_livestreams(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedLivestreams:
    """List livestream sessions with per-session metrics."""
    repo = LivestreamsRepo(session)
    sessions = await repo.list(shop.id, limit=limit + 1, after=after)

    has_more = len(sessions) > limit
    items = sessions[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return PaginatedLivestreams(
        items=[_to_response(ls) for ls in items],
        next_cursor=next_cursor,
    )


def _to_response(ls: Livestream) -> LivestreamResponse:
    duration: int | None = None
    if ls.start_time is not None and ls.end_time is not None:
        duration = int((ls.end_time - ls.start_time).total_seconds())

    return LivestreamResponse(
        id=ls.id,
        tiktok_livestream_id=ls.tiktok_livestream_id,
        creator_id=ls.creator_id,
        title=ls.title,
        duration_seconds=duration,
        viewer_count=ls.viewer_count,
        peak_concurrent_viewers=ls.peak_concurrent_viewers,
        order_count=ls.order_count,
        revenue=str(ls.revenue) if ls.revenue is not None else None,
    )
