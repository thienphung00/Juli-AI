import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.api.dependencies import get_active_shop
from backend.integrations.identity.infrastructure.auth import get_current_user
from backend.database import Shop, ShopsRepo, User, get_session

router = APIRouter(prefix="/shops", tags=["shops"])

DEFAULT_PAGE_LIMIT = 50


class ShopResponse(BaseModel):
    id: uuid.UUID
    shop_name: str
    tiktok_shop_id: str | None
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ShopResponse])
async def list_shops(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Shop]:
    """Return all shops belonging to the authenticated user."""
    shops = await ShopsRepo(session).list(user.id)
    return shops[offset : offset + limit]


@router.get("/me", response_model=ShopResponse)
async def get_current_shop(
    shop: Shop = Depends(get_active_shop),
) -> Shop:
    """Return the shop identified by the X-Shop-Id header."""
    return shop
