"""Seller scope: "Giá thị trường" of one product (P92 B-10), under ``/v1/demo/shopee``.

- ``GET /products/{item_id}/market-price`` -- price per unit against page 1 of Shopee's public
  search for the product's main keywords: ONLY the median and average of the similar products,
  their number, the unit, keyword, collected date and stale flag (owner decision 2026-11-05: no
  listing, shop name, title or P25-P75 for the seller; Ops sees the full block). Absent
  (``available: false`` + reason) without a capture.
- ``GET /builder/products/{item_id}/market-range`` -- the same without the listings, for the
  builder's price-panel marker (``price`` = the drafted selling price of ``variation_id``).

Read-only, own shop only. The logic is ``services/shopee_builder/market_price``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.capability_gate import require_capability
from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.api.routes import shopee_market_common as market
from juli_backend.database import Shop, get_session

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])

_gate_r = require_capability("read_shop_totals")
AsOf = Annotated[date | None, Query()]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/products/{item_id}/market-price")
async def product_market_price(
    item_id: common.ItemPath,
    variation_id: market.VariationQuery = None,
    price: market.PriceQuery = None,
    as_of: AsOf = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await market.h_market_price(
        session,
        shop.id,
        item_id,
        variation_id=variation_id,
        price=price,
        as_of=as_of,
        now=_now(),
        closest=False,
        seller=True,
    )


@router.get("/builder/products/{item_id}/market-range")
async def builder_market_range(
    item_id: common.ItemPath,
    variation_id: market.VariationQuery = None,
    price: market.PriceQuery = None,
    as_of: AsOf = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await market.h_market_price(
        session,
        shop.id,
        item_id,
        variation_id=variation_id,
        price=price,
        as_of=as_of,
        now=_now(),
        closest=False,
        seller=True,
    )
