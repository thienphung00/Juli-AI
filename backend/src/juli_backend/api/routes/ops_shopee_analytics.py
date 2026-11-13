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
- ``GET /v1/ops/shops/{id}/shopee/analytics/kols`` and ``.../products/{item_id}/kols`` (P91 D-9)
- ``GET /v1/ops/shops/{id}/shopee/analytics/kols/compare?group=channel|campaign_type|kol`` (P100)

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
    PlanPeriodQ,
    refusal,
    window_args,
)
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_analytics import channel_split, metric_view, queries

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
            body = await queries.matrix(
                session,
                shop_id,
                sort=sort,
                limit=limit,
                **window_args(period, month, start, end, as_of),
            )
            return await reco.attach_card_refs(session, shop_id, "matrix", body, audience="ops")
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
            body = await queries.critical(
                session, shop_id, **window_args(period, month, start, end, as_of)
            )
            return await reco.attach_card_refs(session, shop_id, "critical", body, audience="ops")
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
            body = await queries.ranking(
                session,
                shop_id,
                kind=kind,
                source=source,
                sub=sub,
                xep_theo=xep_theo,
                **window_args(period, month, start, end, as_of),
            )
            return await reco.attach_card_refs(session, shop_id, "ranking", body, audience="ops")
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
            body = await queries.product_page(session, shop_id, item_id, period=period, as_of=as_of)
            return await reco.attach_card_refs(session, shop_id, "product", body, audience="ops")
    except REFUSALS as exc:
        raise refusal(exc) from None


KolSortQ = Annotated[str, Query(pattern="^(net_profit|orders|gmv|roi_incl_samples|commission)$")]


@router.get(f"{BASE}/kols")
async def ops_shopee_kols(
    shop_id: uuid.UUID,
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    channel: Annotated[str | None, Query(max_length=64)] = None,
    item_id: Annotated[str | None, Query(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")] = None,
    kol: Annotated[str | None, Query(max_length=120)] = None,
    sort: KolSortQ = "net_profit",
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Phân tích › KOL (P91 D-9)."""
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            body = await queries.kol_table(
                session,
                shop_id,
                channel=channel,
                item_id=item_id,
                kol_key=kol,
                sort=sort,
                limit=limit,
                **window_args(period, month, start, end, as_of),
            )
            return await reco.attach_kol_cards(session, shop_id, body, audience="ops")
    except REFUSALS as exc:
        raise refusal(exc) from None


KolGroupQ = Annotated[str, Query(pattern="^(channel|campaign_type|kol)$")]


@router.get(f"{BASE}/kols/compare")
async def ops_shopee_kols_compare(
    shop_id: uuid.UUID,
    group: KolGroupQ = "channel",
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Phân tích › KOL › So sánh: by kênh / loại chiến dịch / KOL, and Affiliate vs Ads vs
    the shop's own flows (P100)."""
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await queries.kol_compare(
                session, shop_id, group=group, **window_args(period, month, start, end, as_of)
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/products/{{item_id}}/kols")
async def ops_shopee_product_kols(
    shop_id: uuid.UUID,
    item_id: Annotated[str, Path(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")],
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Sản phẩm › Tiếp thị liên kết (P91 D-9)."""
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            body = await queries.kol_product_tab(
                session, shop_id, item_id, **window_args(period, month, start, end, as_of)
            )
            return await reco.attach_kol_cards(session, shop_id, body, audience="ops")
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/channel-split")
async def ops_shopee_channel_split(
    shop_id: uuid.UUID,
    period: PlanPeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await channel_split.channel_split(
                session,
                shop_id,
                product_id=product_id,
                **window_args(period, month, start, end, as_of),
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/channel-split/products")
async def ops_shopee_channel_split_products(
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
            return await channel_split.channel_split_products(
                session, shop_id, **window_args(period, month, start, end, as_of)
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


MetricQ = Annotated[str, Query(pattern="^(views|ctr|ctor|aov|orders|gmv|margin)$")]


@router.get(f"{BASE}/metric-view")
async def ops_shopee_metric_view(
    shop_id: uuid.UUID,
    metric: MetricQ = "gmv",
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: FromQ = None,
    end: ToQ = None,
    as_of: DateQ = None,
    channel: Annotated[str | None, Query(max_length=32)] = None,
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shopee_shop(session, shop_id)
    try:
        async with with_shop_scope(session, shop_id, transaction_ends_after=True):
            return await metric_view.metric_view(
                session,
                shop_id,
                metric=metric,
                audience="ops",
                channel=channel,
                product_id=product_id,
                **window_args(period, month, start, end, as_of),
            )
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get(f"{BASE}/kol-section")
async def ops_shopee_kol_section(
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
            return await metric_view.kol_section(
                session, shop_id, audience="ops", **window_args(period, month, start, end, as_of)
            )
    except REFUSALS as exc:
        raise refusal(exc) from None
