"""Seller scope: the four Ops shop pages, read-only (P92 B-8), under ``/v1/demo/shopee``.

Same services as the Ops routes, scoped to the seller's own shop with ``get_active_shop``; nothing
here writes and no buyer data is in any answer (order keys are hashes).

- ``GET /keywords[?min_volume=]``       Từ khóa: seeds, volumes, difficulty, coverage, ads keywords
- ``GET /dashboard/products``           Sản phẩm: funnel per product for one export period
- ``GET /dashboard/flows``              Sản phẩm + luồng: GMV by traffic flow
- ``GET /dashboard/ads``                Quảng cáo: cost / orders / ROAS by ad type
- ``GET /dashboard/promotions``         Khuyến mãi: the promotion programme timeline
- ``GET /orders``                       Đơn hàng: one row per order, levers, status, income
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.demo_shopee_analytics import _shopee
from juli_backend.api.routes.shopee_analytics_common import (
    REFUSALS,
    DateQ,
    MonthQ,
    PeriodQ,
    refusal,
    window_args,
)
from juli_backend.database import Shop, get_session
from juli_backend.services import shop_keywords
from juli_backend.services.ops import shopee_dashboards as dash
from juli_backend.services.shopee_analytics import orders as order_view
from juli_backend.services.shopee_analytics import queries

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])

OrderType = Literal["placed", "paid", "confirmed"]
FromDay = Annotated[date | None, Query(alias="from")]
ToDay = Annotated[date | None, Query(alias="to")]
MAX_MIN_VOLUME = 10_000_000


def _window(start: date | None, end: date | None, latest: date | None) -> dash.DateRange:
    try:
        return dash.resolve_range(start, end, latest)
    except dash.InvalidRange as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_range", "message": str(exc)}
        ) from None


@router.get("/keywords")
async def seller_keywords(
    min_volume: Annotated[int, Query(ge=0, le=MAX_MIN_VOLUME)] = shop_keywords.DEFAULT_MIN_VOLUME,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await shop_keywords.board(session, _shopee(shop), "shopee", min_volume=min_volume)
    await session.commit()
    return payload


@router.get("/dashboard/products")
async def seller_products(
    order_type: OrderType = "confirmed",
    period_from: Annotated[date | None, Query()] = None,
    period_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=dash.MAX_PRODUCTS)] = 50,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if (period_from is None) != (period_to is None) or (
        period_from is not None and period_to is not None and period_from > period_to
    ):
        raise HTTPException(status_code=422, detail={"code": "invalid_range"})
    return await dash.products(
        session,
        _shopee(shop),
        order_type=order_type,
        period_start=period_from,
        period_end=period_to,
        limit=limit,
    )


@router.get("/dashboard/flows")
async def seller_flows(
    start: FromDay = None,
    end: ToDay = None,
    order_type: OrderType = "confirmed",
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    window = _window(start, end, await dash.latest_day(session, shop_id, "traffic_overview"))
    return await dash.flows(session, shop_id, window, order_type)


@router.get("/dashboard/ads")
async def seller_ads(
    start: FromDay = None,
    end: ToDay = None,
    order_type: OrderType = "placed",
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    window = _window(start, end, await dash.latest_day(session, shop_id, "traffic_overview"))
    return await dash.ads(session, shop_id, window, order_type)


@router.get("/dashboard/promotions")
async def seller_promotions(
    start: FromDay = None,
    end: ToDay = None,
    order_type: OrderType = "confirmed",
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    window = _window(start, end, await dash.latest_day(session, shop_id, "promotion_daily"))
    return await dash.promotions(session, shop_id, window, order_type)


@router.get("/orders")
async def seller_orders(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromDay = None,
    end: ToDay = None,
    as_of: DateQ = None,
    status: Annotated[str | None, Query(pattern=f"^({'|'.join(order_view.STATUSES)})$")] = None,
    lever: Annotated[
        str | None, Query(pattern="^(promotion|flash_sale|voucher|combo|affiliate)$")
    ] = None,
    sort: Annotated[str, Query(pattern=f"^({'|'.join(order_view.SORTS)})$")] = "date",
    limit: Annotated[int, Query(ge=1, le=order_view.MAX_LIMIT)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await queries.orders(
            session,
            _shopee(shop),
            status=status,
            lever=lever,
            sort=sort,
            limit=limit,
            offset=offset,
            **window_args(period, month, start, end, as_of),
        )
    except REFUSALS as exc:
        raise refusal(exc) from None
