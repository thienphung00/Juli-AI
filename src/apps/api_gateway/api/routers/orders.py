import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.apps.api_gateway.api.dependencies import get_active_shop
from src.shared.utils.data import NotFound, Order, OrdersRepo, Shop, get_session

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderResponse(BaseModel):
    id: uuid.UUID
    tiktok_order_id: str
    status: str
    total_amount: str
    currency: str
    update_time: datetime
    shipped_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedOrders(BaseModel):
    items: list[OrderResponse]
    next_cursor: str | None = None


@router.get("", response_model=PaginatedOrders)
async def list_orders(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedOrders:
    """List orders with optional filtering and cursor pagination."""
    repo = OrdersRepo(session)
    orders = await repo.list_filtered(
        shop.id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit + 1,
        after=after,
    )

    has_more = len(orders) > limit
    items = orders[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return PaginatedOrders(
        items=[_order_to_response(o) for o in items],
        next_cursor=next_cursor,
    )


@router.post("/{order_id}/confirm-shipment", response_model=OrderResponse)
async def confirm_shipment(
    order_id: uuid.UUID,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> OrderResponse:
    """Mark an order as shipped."""
    repo = OrdersRepo(session)
    try:
        order = await repo.confirm_shipment(shop.id, order_id)
    except NotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    await session.commit()
    return _order_to_response(order)


def _order_to_response(order: Order) -> OrderResponse:
    shipped_at = order.update_time if order.status == "SHIPPED" else None
    return OrderResponse(
        id=order.id,
        tiktok_order_id=order.tiktok_order_id,
        status=order.status,
        total_amount=str(order.total_amount),
        currency=order.currency,
        update_time=order.update_time,
        shipped_at=shipped_at,
    )
