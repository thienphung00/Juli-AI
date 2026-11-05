"""Juli Ops: "Giá thị trường" of one product (P92 B-10) -- the Ops mirror of
``demo_shopee_market``, Xem+, under ``/v1/ops/shops/{id}/shopee``."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.api.routes import shopee_market_common as market
from juli_backend.api.routes.ops import MaskedRoute, OpsContext, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)
BASE = "/shops/{shop_id}/shopee"
AsOf = Annotated[date | None, Query()]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _read(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    variation_id: str | None,
    price: float | None,
    as_of: date | None,
    closest: bool,
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id):
        return await market.h_market_price(
            session,
            shop_id,
            item_id,
            variation_id=variation_id,
            price=price,
            as_of=as_of,
            now=_now(),
            closest=closest,
        )


@router.get(BASE + "/products/{item_id}/market-price")
async def ops_market_price(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    variation_id: market.VariationQuery = None,
    price: market.PriceQuery = None,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _read(
        session, shop_id, item_id, variation_id=variation_id, price=price, as_of=as_of, closest=True
    )


@router.get(BASE + "/builder/products/{item_id}/market-range")
async def ops_market_range(
    shop_id: uuid.UUID,
    item_id: common.ItemPath,
    variation_id: market.VariationQuery = None,
    price: market.PriceQuery = None,
    as_of: AsOf = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _read(
        session,
        shop_id,
        item_id,
        variation_id=variation_id,
        price=price,
        as_of=as_of,
        closest=False,
    )
