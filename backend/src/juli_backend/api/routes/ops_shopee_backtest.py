"""Juli Ops: the fee-formula backtest of one shop (P92 B-9, last bullet).

``GET /v1/ops/shops/{id}/shopee/fee-backtest?days=90&as_of=`` (Xem+): for the orders that have an
Income row, the formula's fees against the fees Shopee actually charged -- mean absolute gap (đ per
order), that gap as a percentage of what buyers paid (target <= 1 %), the signed bias and the five
worst orders (order key = the first 12 characters of the keyed hash; no buyer field). Ops only.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.capability_gate import require_ops_capability
from juli_backend.api.routes.ops import MaskedRoute, OpsContext, viewer
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.shopee_analytics import fee_backtest

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

_gate = require_ops_capability(None)


@router.get("/shops/{shop_id}/shopee/fee-backtest")
async def ops_fee_backtest(
    shop_id: uuid.UUID,
    days: Annotated[int, Query(ge=7, le=180)] = fee_backtest.DEFAULT_DAYS,
    as_of: Annotated[date | None, Query()] = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
    _shop_name: str = Depends(_gate),
) -> dict[str, Any]:
    try:
        async with with_shop_scope(session, shop_id):
            return await fee_backtest.run(session, shop_id, as_of=as_of, days=days)
    except fee_backtest.NoShopeeData:
        raise HTTPException(
            409, detail={"code": "reco_no_data", "message": "Shop chưa có số liệu Shopee."}
        ) from None
