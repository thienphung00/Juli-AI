import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.apps.api_gateway.api.dependencies import get_active_shop
from src.shared.utils.data import SettlementsRepo, Shop, get_session
from src.shared.utils.data.models import Settlement

router = APIRouter(prefix="/settlements", tags=["settlements"])


class SettlementResponse(BaseModel):
    id: uuid.UUID
    tiktok_settlement_id: str
    currency: str
    status: str
    gross_amount: str
    platform_commission: str
    affiliate_commission: str
    shipping_fee: str
    net_revenue: str

    model_config = {"from_attributes": True}


class PaginatedSettlements(BaseModel):
    items: list[SettlementResponse]
    next_cursor: str | None = None


@router.get("", response_model=PaginatedSettlements)
async def list_settlements(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedSettlements:
    """List settlements with net revenue after all deductions."""
    repo = SettlementsRepo(session)
    settlements = await repo.list(shop.id, limit=limit + 1, after=after)

    has_more = len(settlements) > limit
    items = settlements[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return PaginatedSettlements(
        items=[_to_response(s) for s in items],
        next_cursor=next_cursor,
    )


def _to_response(s: Settlement) -> SettlementResponse:
    net = s.amount - s.platform_commission - s.affiliate_commission - s.shipping_fee
    return SettlementResponse(
        id=s.id,
        tiktok_settlement_id=s.tiktok_settlement_id,
        currency=s.currency,
        status=s.status,
        gross_amount=str(s.amount),
        platform_commission=str(s.platform_commission),
        affiliate_commission=str(s.affiliate_commission),
        shipping_fee=str(s.shipping_fee),
        net_revenue=str(net),
    )
