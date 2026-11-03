"""Seller scope: the Shopee shop screens' read APIs (P90 step 7) -- Tổng quan, Phân tích,
Sản phẩm, Xếp hạng. ``/v1/demo/shopee/*``, authenticated like every seller route
(``get_active_shop``: the X-Shop-Id header resolves one of the user's own shops, and the
request runs under that shop's tenant scope).

- ``GET /demo/shopee/overview``  -- five flows + Chênh lệch nguồn, the five numbers, shop profit.
- ``GET /demo/shopee/matrix``    -- product x source matrix (traffic flows, price levers, ads).
- ``GET /demo/shopee/critical``  -- the critical-metric list ranked by ₫ at stake.
- ``GET /demo/shopee/ranking``   -- a cell's rows (products / campaigns / KOLs / vouchers /
  keywords), ``source`` and ``xep_theo`` parameters, closing rows that add up.
- ``GET /demo/shopee/products/{item_id}`` -- one product's page payload.

Read-only. A shop that is not on Shopee answers 409 ``not_a_shopee_shop``; a shop without Shopee
numbers 409 ``no_shopee_data``. The logic is ``services/shopee_analytics``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.api.routes.shopee_analytics_common import (
    REFUSALS,
    DateQ,
    MonthQ,
    PeriodQ,
    refusal,
    window_args,
)
from juli_backend.database import Shop, get_session
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_analytics import queries

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])

PLATFORM = "shopee"


def _shopee(shop: Shop) -> uuid.UUID:
    if shop.platform != PLATFORM:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "not_a_shopee_shop", "message": "this shop is not on Shopee"},
        )
    return shop.id


@router.get("/overview")
async def shopee_overview(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        return await queries.overview(
            session, shop_id, **window_args(period, month, start, end, as_of)
        )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get("/matrix")
async def shopee_matrix(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    sort: Annotated[str, Query(pattern="^(gmv|bien|orders|profit)$")] = "gmv",
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        body = await queries.matrix(
            session,
            shop_id,
            sort=sort,
            limit=limit,
            **window_args(period, month, start, end, as_of),
        )
        return await reco.attach_card_refs(session, shop_id, "matrix", body, audience="seller")
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get("/critical")
async def shopee_critical(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        body = await queries.critical(
            session, shop_id, **window_args(period, month, start, end, as_of)
        )
        return await reco.attach_card_refs(session, shop_id, "critical", body, audience="seller")
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get("/ranking")
async def shopee_ranking(
    kind: Annotated[
        str, Query(pattern="^(products|campaigns|kols|vouchers|keywords)$")
    ] = "products",
    source: str = "all",
    sub: str | None = None,
    xep_theo: str = "gmv_per_day",
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        body = await queries.ranking(
            session,
            shop_id,
            kind=kind,
            source=source,
            sub=sub,
            xep_theo=xep_theo,
            **window_args(period, month, start, end, as_of),
        )
        return await reco.attach_card_refs(session, shop_id, "ranking", body, audience="seller")
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get("/products/{item_id}")
async def shopee_product(
    item_id: Annotated[str, Path(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")],
    period: Annotated[str, Query(pattern="^(7d|30d|90d)$")] = "30d",
    as_of: DateQ = None,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = _shopee(shop)
    try:
        body = await queries.product_page(session, shop_id, item_id, period=period, as_of=as_of)
        return await reco.attach_card_refs(session, shop_id, "product", body, audience="seller")
    except REFUSALS as exc:
        raise refusal(exc) from None
