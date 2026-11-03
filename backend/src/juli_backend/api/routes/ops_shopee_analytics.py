"""Juli Ops: the Shopee shop screens' read APIs for one shop (P90 step 7), for staff.

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth dependencies
(Cloudflare Access → Supabase → active staff row → role ``viewer``) and the PII-masking route
class. The payloads are the seller's own (``api/routes/demo_shopee_analytics.py``): same service,
same numbers, read under the shop's own tenant scope. Read-only; nothing is audited because
nothing is written.

- ``GET /v1/ops/shops/{id}/shopee/analytics/overview``
- ``GET /v1/ops/shops/{id}/shopee/analytics/matrix``
- ``GET /v1/ops/shops/{id}/shopee/analytics/critical``
- ``GET /v1/ops/shops/{id}/shopee/analytics/ranking``
- ``GET /v1/ops/shops/{id}/shopee/analytics/products/{item_id}``

A shop that is not on Shopee answers 409 ``not_a_shopee_shop``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, viewer
from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop
from juli_backend.api.routes.shopee_analytics_common import (
    REFUSALS,
    DateQ,
    MonthQ,
    PeriodQ,
    refusal,
    window_args,
)
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.shopee_analytics import queries

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

BASE = "/shops/{shop_id}/shopee/analytics"
FromQ = Annotated[date | None, Query(alias="from")]
ToQ = Annotated[date | None, Query(alias="to")]


@router.get(f"{BASE}/overview")
async def ops_shopee_overview(
    shop_id: uuid.UUID,
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await queries.overview(
                session, shop_id, **window_args(period, month, start, end, as_of)
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/matrix")
async def ops_shopee_matrix(
    shop_id: uuid.UUID,
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    sort: Annotated[str, Query(pattern="^(gmv|bien|orders|profit)$")] = "gmv",
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await queries.matrix(
                session,
                shop_id,
                sort=sort,
                limit=limit,
                **window_args(period, month, start, end, as_of),
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/critical")
async def ops_shopee_critical(
    shop_id: uuid.UUID,
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await queries.critical(
                session, shop_id, **window_args(period, month, start, end, as_of)
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/ranking")
async def ops_shopee_ranking(
    shop_id: uuid.UUID,
    kind: Annotated[
        str, Query(pattern="^(products|campaigns|kols|vouchers|keywords)$")
    ] = "products",
    source: str = "all",
    sub: str | None = None,
    xep_theo: str = "gmv_per_day",
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await queries.ranking(
                session,
                shop_id,
                kind=kind,
                source=source,
                sub=sub,
                xep_theo=xep_theo,
                **window_args(period, month, start, end, as_of),
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/products/{{item_id}}")
async def ops_shopee_product(
    shop_id: uuid.UUID,
    item_id: Annotated[str, Path(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")],
    period: Annotated[str, Query(pattern="^(7d|30d|90d)$")] = "30d",
    as_of: DateQ = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await queries.product_page(session, shop_id, item_id, period=period, as_of=as_of)
    except REFUSALS as exc:
        raise refusal(exc) from None
