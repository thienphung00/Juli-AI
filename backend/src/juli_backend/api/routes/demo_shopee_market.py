"""Seller scope: "Giá thị trường" of one product (P92 B-10), under ``/v1/demo/shopee``.

- ``GET /products/{item_id}/market-price`` -- price per unit against page 1 of Shopee's public
  search for the product's main keywords: median, P25-P75, the 5 closest similar listings,
  keyword, collected date, stale flag. Absent (``available: false`` + reason) without a capture.
- ``GET /builder/products/{item_id}/market-range`` -- the same without the listings, for the
  builder's price-panel marker (``price`` = the drafted selling price of ``variation_id``).

Read-only, own shop only. The logic is ``services/shopee_builder/market_price``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.api.routes import shopee_market_common as market
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.database import Shop, get_session

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])
AsOf = Annotated[date | None, Query()]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/products/{item_id}/market-price")
async def product_market_price(
    item_id: common.ItemPath,
    variation_id: market.VariationQuery = None,
    price: market.PriceQuery = None,
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await market.h_market_price(
        session,
        _shopee(shop),
        item_id,
        variation_id=variation_id,
        price=price,
        as_of=as_of,
        now=_now(),
        closest=True,
    )


@router.get("/builder/products/{item_id}/market-range")
async def builder_market_range(
    item_id: common.ItemPath,
    variation_id: market.VariationQuery = None,
    price: market.PriceQuery = None,
    as_of: AsOf = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await market.h_market_price(
        session,
        _shopee(shop),
        item_id,
        variation_id=variation_id,
        price=price,
        as_of=as_of,
        now=_now(),
        closest=False,
    )
