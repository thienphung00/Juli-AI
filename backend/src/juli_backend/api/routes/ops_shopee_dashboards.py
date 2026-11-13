"""Juli Ops: Shopee dashboards (ADR-117 step 4, owner decisions G3 / G5). Read-only, Xem+.

- ``GET /v1/ops/shops/{id}/shopee/products`` -- per-product funnel for one export period,
  flags and 12-month history (Sản phẩm).
- ``GET /v1/ops/shops/{id}/shopee/flows`` -- GMV by flow; "Trang shop" is a child of
  "Thẻ sản phẩm" and never summed into the total (G3).
- ``GET /v1/ops/shops/{id}/shopee/ads`` -- cost / orders / ROAS by ad type, monthly and
  daily, with the low-ROAS alert.
- ``GET /v1/ops/shops/{id}/shopee/promotions`` -- the promotion programme timeline.

A shop that is not on Shopee answers 409 ``not_a_shopee_shop``. The service is
``services/ops/shopee_dashboards.py``; the tables are read under the shop's own scope.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _shop, viewer
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ops import shopee_dashboards as dash

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

OrderType = Literal["placed", "paid", "confirmed"]
FromDay = Annotated[date | None, Query(alias="from")]
ToDay = Annotated[date | None, Query(alias="to")]


async def _shopee_shop(session: AsyncSession, shop_id: uuid.UUID) -> str:
    """404 for an unknown shop, 409 unless it is a Shopee shop; returns the shop's name.

    The platform comes from the Ops listing, not from a read under ``shops.user_id``: since
    P93 that user may be a removed member, and ``shops`` RLS then hides the shop from them.
    """
    listing = await _shop(session, shop_id)
    await session.commit()
    if listing.platform != dash.PLATFORM:
        raise HTTPException(
            status_code=409,
            detail={"code": "not_a_shopee_shop", "message": "this shop is not on Shopee"},
        )
    return listing.shop_name


def _window(start: date | None, end: date | None, latest: date | None) -> dash.DateRange:
    try:
        return dash.resolve_range(start, end, latest)
    except dash.InvalidRange as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_range", "message": str(exc)}
        ) from None


@router.get("/shops/{shop_id}/shopee/products")
async def ops_shopee_products(
    shop_id: uuid.UUID,
    order_type: OrderType = "confirmed",
    period_from: Annotated[date | None, Query()] = None,
    period_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=dash.MAX_PRODUCTS)] = 50,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if (period_from is None) != (period_to is None) or (
        period_from is not None and period_to is not None and period_from > period_to
    ):
        raise HTTPException(status_code=422, detail={"code": "invalid_range"})
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id, transaction_ends_after=True):
        return await dash.products(
            session,
            shop_id,
            order_type=order_type,
            period_start=period_from,
            period_end=period_to,
            limit=limit,
        )


@router.get("/shops/{shop_id}/shopee/flows")
async def ops_shopee_flows(
    shop_id: uuid.UUID,
    start: FromDay = None,
    end: ToDay = None,
    order_type: OrderType = "confirmed",
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id, transaction_ends_after=True):
        window = _window(start, end, await dash.latest_day(session, shop_id, "traffic_overview"))
        return await dash.flows(session, shop_id, window, order_type)


@router.get("/shops/{shop_id}/shopee/ads")
async def ops_shopee_ads(
    shop_id: uuid.UUID,
    start: FromDay = None,
    end: ToDay = None,
    order_type: OrderType = "placed",
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id, transaction_ends_after=True):
        window = _window(start, end, await dash.latest_day(session, shop_id, "traffic_overview"))
        return await dash.ads(session, shop_id, window, order_type)


@router.get("/shops/{shop_id}/shopee/promotions")
async def ops_shopee_promotions(
    shop_id: uuid.UUID,
    start: FromDay = None,
    end: ToDay = None,
    order_type: OrderType = "confirmed",
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    async with with_shop_scope(session, shop_id, transaction_ends_after=True):
        window = _window(start, end, await dash.latest_day(session, shop_id, "promotion_daily"))
        return await dash.promotions(session, shop_id, window, order_type)
