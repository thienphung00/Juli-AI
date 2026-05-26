import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_active_shop
from src.data import ProductsRepo, Shop, get_session

router = APIRouter(prefix="/products", tags=["products"])


class ProductResponse(BaseModel):
    id: uuid.UUID
    tiktok_product_id: str
    name: str
    status: str
    revenue: str
    units_sold: int
    update_time: datetime

    model_config = {"from_attributes": True}


class PaginatedProducts(BaseModel):
    items: list[ProductResponse]
    next_cursor: str | None = None


@router.get("", response_model=PaginatedProducts)
async def list_products(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedProducts:
    """List products ranked by revenue (descending) with units sold."""
    repo = ProductsRepo(session)
    products = await repo.list_by_revenue(
        shop.id,
        limit=limit + 1,
        after=after,
    )

    has_more = len(products) > limit
    items = products[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return PaginatedProducts(
        items=[
            ProductResponse(
                id=p.id,
                tiktok_product_id=p.tiktok_product_id,
                name=p.name,
                status=p.status,
                revenue=str(p.revenue),
                units_sold=p.units_sold,
                update_time=p.update_time,
            )
            for p in items
        ],
        next_cursor=next_cursor,
    )
