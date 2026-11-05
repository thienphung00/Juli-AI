"""P92 B-10 "Giá thị trường": the handler Demo and Ops share (the routes add auth and scope)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.services.shopee_builder import market_price
from juli_backend.services.shopee_builder import service as builder

VariationQuery = Annotated[str | None, Query(max_length=64)]
PriceQuery = Annotated[float | None, Query(gt=0, le=500_000_000)]


async def h_market_price(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    variation_id: str | None,
    price: float | None,
    as_of: date | None,
    now: datetime,
    closest: bool,
) -> dict[str, Any]:
    try:
        return await market_price.market_price(
            session,
            shop_id,
            item_id,
            variation_id=variation_id,
            draft_price=price,
            as_of=as_of,
            now=now,
            closest=closest,
        )
    except builder.NoShopeeData:
        raise common.no_data() from None
    except LookupError:
        raise common.not_found(item_id) from None
