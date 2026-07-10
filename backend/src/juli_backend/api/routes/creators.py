import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.database import CreatorsRepo, NotFound, Shop, get_session
from juli_backend.models.models import Creator, Livestream

router = APIRouter(prefix="/creators", tags=["creators"])


class CreatorResponse(BaseModel):
    id: uuid.UUID
    tiktok_creator_id: str
    name: str
    follower_count: int | None = None
    total_gmv: str
    commission_efficiency: str

    model_config = {"from_attributes": True}


class PaginatedCreators(BaseModel):
    items: list[CreatorResponse]
    next_cursor: str | None = None


class ContentSessionResponse(BaseModel):
    tiktok_livestream_id: str
    title: str | None = None
    views: int | None = None
    clicks: int | None = None
    orders: int | None = None


class CreatorContentResponse(BaseModel):
    creator_id: uuid.UUID
    sessions: list[ContentSessionResponse]


@router.get("", response_model=PaginatedCreators)
async def list_creators(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedCreators:
    """List creators with GMV attribution and commission efficiency."""
    repo = CreatorsRepo(session)
    creators = await repo.list(shop.id, limit=limit + 1, after=after)

    has_more = len(creators) > limit
    items = creators[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return PaginatedCreators(
        items=[_creator_to_response(c) for c in items],
        next_cursor=next_cursor,
    )


@router.get("/{creator_id}/content", response_model=CreatorContentResponse)
async def get_creator_content(
    creator_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> CreatorContentResponse:
    """Return content-to-conversion funnel for a creator: views → clicks → orders."""
    creators_repo = CreatorsRepo(session)
    try:
        creator = await creators_repo.get(shop.id, creator_id)
    except NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found",
        )

    stmt = (
        select(Livestream)
        .where(
            Livestream.shop_id == shop.id,
            Livestream.creator_id == creator.id,
        )
        .order_by(Livestream.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    sessions = list(result.scalars().all())

    return CreatorContentResponse(
        creator_id=creator.id,
        sessions=[_session_to_funnel(ls) for ls in sessions],
    )


def _creator_to_response(c: Creator) -> CreatorResponse:
    efficiency = (c.total_gmv * c.commission_rate).quantize(Decimal("0.0001"))
    return CreatorResponse(
        id=c.id,
        tiktok_creator_id=c.tiktok_creator_id,
        name=c.name,
        follower_count=c.follower_count,
        total_gmv=str(c.total_gmv),
        commission_efficiency=str(efficiency),
    )


def _session_to_funnel(ls: Livestream) -> ContentSessionResponse:
    return ContentSessionResponse(
        tiktok_livestream_id=ls.tiktok_livestream_id,
        title=ls.title,
        views=ls.viewer_count,
        clicks=ls.click_count,
        orders=ls.order_count,
    )
