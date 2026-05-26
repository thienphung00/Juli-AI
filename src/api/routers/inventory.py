import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_active_shop
from src.data import InventoryRepo, Shop, get_session

router = APIRouter(prefix="/inventory", tags=["inventory"])


class InventoryResponse(BaseModel):
    id: uuid.UUID
    tiktok_product_id: str
    tiktok_sku_id: str
    quantity: int
    velocity: str
    warehouse_id: str | None = None
    update_time: datetime

    model_config = {"from_attributes": True}


class PaginatedInventory(BaseModel):
    items: list[InventoryResponse]
    next_cursor: str | None = None


@router.get("", response_model=PaginatedInventory)
async def list_inventory(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedInventory:
    """List inventory items with stock levels and velocity indicators."""
    repo = InventoryRepo(session)
    items = await repo.list(shop.id, limit=limit + 1, after=after)

    has_more = len(items) > limit
    page = items[:limit]
    next_cursor = str(page[-1].id) if has_more and page else None

    return PaginatedInventory(
        items=[
            InventoryResponse(
                id=item.id,
                tiktok_product_id=item.tiktok_product_id,
                tiktok_sku_id=item.tiktok_sku_id,
                quantity=item.quantity,
                velocity=item.velocity,
                warehouse_id=item.warehouse_id,
                update_time=item.update_time,
            )
            for item in page
        ],
        next_cursor=next_cursor,
    )
