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
- ``GET /demo/shopee/kols`` -- Phân tích › KOL: KOL x sản phẩm x kênh (P91 D-9).
- ``GET /demo/shopee/products/{item_id}/kols`` -- the product's Tiếp thị liên kết tab.
- ``GET /demo/shopee/kols/compare`` -- Phân tích › KOL › So sánh: by kênh / loại chiến dịch / KOL,
  and Affiliate vs Ads vs the shop's own flows (P100).
- ``GET /demo/shopee/exports/tong-quan.xlsx`` / ``.../exports/ke-hoach.xlsx?month=`` -- the two
  Excel reports (P100): the period + level of Tổng quan, the month of Kế hoạch.

Read-only. W3: the analytics routes (not the two exports) answer a TikTok shop too, from the
platform-neutral layer-4 rows; the exports stay Shopee-only (409 ``not_a_shopee_shop``). A shop
without numbers answers 409 ``no_shopee_data`` / ``no_tiktok_data``. The logic is
``services/shopee_analytics``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.capability_gate import ANALYTICS_DATA_PLATFORMS, require_capability
from juli_backend.api.reviewer import reviewer_context
from juli_backend.api.routes.shopee_analytics_common import (
    REFUSALS,
    DateQ,
    MonthQ,
    PeriodQ,
    PlanPeriodQ,
    export_ke_hoach,
    export_ke_hoach_all,
    export_tong_quan,
    export_tong_quan_all,
    refusal,
    stamped,
    window_args,
)
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_analytics import channel_split, metric_view, queries

router = APIRouter(prefix="/demo/shopee", tags=["demo-shopee"])

_gate_r = require_capability("read_shop_totals", requires_data_on=ANALYTICS_DATA_PLATFORMS)
#: the two Excel exports stay Shopee-only (TikTok exports are not in W3)
_gate_x = require_capability("read_shop_totals")

PLATFORM = "shopee"


@router.get("/overview")
async def shopee_overview(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = shop.id
    try:
        return stamped(
            await queries.overview(
                session,
                shop_id,
                platform=shop.platform,
                **window_args(period, month, start, end, as_of),
            ),
            shop.platform,
            "overview",
        )
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/matrix")
async def shopee_matrix(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    sort: Annotated[str, Query(pattern="^(gmv|bien|orders|profit)$")] = "gmv",
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = shop.id
    try:
        body = await queries.matrix(
            session,
            shop_id,
            platform=shop.platform,
            sort=sort,
            limit=limit,
            **window_args(period, month, start, end, as_of),
        )
        body = await reco.attach_card_refs(session, shop_id, "matrix", body, audience="seller")
        return stamped(body, shop.platform, "matrix")
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/critical")
async def shopee_critical(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = shop.id
    try:
        body = await queries.critical(
            session,
            shop_id,
            platform=shop.platform,
            **window_args(period, month, start, end, as_of),
        )
        body = await reco.attach_card_refs(session, shop_id, "critical", body, audience="seller")
        return stamped(body, shop.platform, "critical")
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


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
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = shop.id
    try:
        body = await queries.ranking(
            session,
            shop_id,
            kind=kind,
            source=source,
            sub=sub,
            xep_theo=xep_theo,
            platform=shop.platform,
            **window_args(period, month, start, end, as_of),
        )
        body = await reco.attach_card_refs(session, shop_id, "ranking", body, audience="seller")
        return stamped(body, shop.platform, "ranking")
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/products/{item_id}")
async def shopee_product(
    item_id: Annotated[str, Path(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")],
    period: Annotated[str, Query(pattern="^(7d|30d|90d)$")] = "30d",
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = shop.id
    try:
        body = await queries.product_page(
            session, shop_id, item_id, period=period, as_of=as_of, platform=shop.platform
        )
        body = await reco.attach_card_refs(session, shop_id, "product", body, audience="seller")
        return stamped(body, shop.platform, "product")
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


# -- KOL (P91 D-9, D-11) -----------------------------------------------------------------

KolSortQ = Annotated[str, Query(pattern="^(net_profit|orders|gmv|roi_incl_samples|commission)$")]


@router.get("/kols")
async def shopee_kols(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    channel: Annotated[str | None, Query(max_length=64)] = None,
    item_id: Annotated[str | None, Query(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")] = None,
    kol: Annotated[str | None, Query(max_length=120)] = None,
    sort: KolSortQ = "net_profit",
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Phân tích › KOL: KOL x sản phẩm x kênh."""
    shop_id = shop.id
    try:
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
        body = await reco.attach_kol_cards(session, shop_id, body, audience="seller")
        return stamped(body, shop.platform, "kols")
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


KolGroupQ = Annotated[str, Query(pattern="^(channel|campaign_type|kol)$")]


@router.get("/kols/compare")
async def shopee_kols_compare(
    group: KolGroupQ = "channel",
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Phân tích › KOL › So sánh (P100)."""
    shop_id = shop.id
    try:
        return stamped(
            await queries.kol_compare(
                session, shop_id, group=group, **window_args(period, month, start, end, as_of)
            ),
            shop.platform,
            "kols_compare",
        )
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/products/{item_id}/kols")
async def shopee_product_kols(
    item_id: Annotated[str, Path(pattern=r"^[0-9A-Za-z:_\-]{1,64}$")],
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Sản phẩm › Tiếp thị liên kết: the product's KOLs."""
    shop_id = shop.id
    try:
        body = await queries.kol_product_tab(
            session, shop_id, item_id, **window_args(period, month, start, end, as_of)
        )
        body = await reco.attach_kol_cards(session, shop_id, body, audience="seller")
        return stamped(body, shop.platform, "product_kols")
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/channel-split")
async def shopee_channel_split(
    period: PlanPeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """P100 Tổng quan: Organic / Quảng cáo / Tiếp thị liên kết of the shop or one product."""
    shop_id = shop.id
    try:
        return stamped(
            await channel_split.channel_split(
                session,
                shop_id,
                product_id=product_id,
                platform=shop.platform,
                **window_args(period, month, start, end, as_of),
            ),
            shop.platform,
            "channel_split",
        )
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/channel-split/products")
async def shopee_channel_split_products(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    shop_id = shop.id
    try:
        return stamped(
            await channel_split.channel_split_products(
                session,
                shop_id,
                platform=shop.platform,
                **window_args(period, month, start, end, as_of),
            ),
            shop.platform,
            "channel_split_products",
        )
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


MetricQ = Annotated[str, Query(pattern="^(views|ctr|ctor|aov|orders|gmv|margin)$")]


@router.get("/metric-view")
async def shopee_metric_view(
    metric: MetricQ = "gmv",
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    channel: Annotated[str | None, Query(max_length=32)] = None,
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """P100 Phân tích: one metric by luồng and by sản phẩm, now vs the previous period."""
    shop_id = shop.id
    try:
        return stamped(
            await metric_view.metric_view(
                session,
                shop_id,
                metric=metric,
                audience="seller",
                channel=channel,
                product_id=product_id,
                platform=shop.platform,
                **window_args(period, month, start, end, as_of),
            ),
            shop.platform,
            "metric_view",
        )
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/kol-section")
async def shopee_kol_section(
    period: PeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    shop: Shop = Depends(_gate_r),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """P100 Phân tích: Tiếp thị liên kết theo KOL, with the previous period."""
    shop_id = shop.id
    try:
        return stamped(
            await metric_view.kol_section(
                session, shop_id, audience="seller", **window_args(period, month, start, end, as_of)
            ),
            shop.platform,
            "kol_section",
        )
    except REFUSALS as exc:
        raise refusal(exc, shop.platform) from None


@router.get("/exports/tong-quan.xlsx")
async def shopee_export_tong_quan(
    request: Request,
    period: PlanPeriodQ = "30d",
    month: MonthQ = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    as_of: DateQ = None,
    product_id: Annotated[str | None, Query(max_length=64)] = None,
    all_shops: Annotated[bool, Query()] = False,
    shop: Shop = Depends(_gate_x),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Tổng quan as an Excel file: the period and level (shop / one product) of the screen.
    ``all_shops`` (G23, "Tất cả shop"): a column per accessible shop plus a Tổng."""
    if all_shops and reviewer_context(request) is None:
        try:
            return await export_tong_quan_all(
                session, user.id, **window_args(period, month, start, end, as_of)
            )
        except REFUSALS as exc:
            raise refusal(exc) from None
    shop_id = shop.id
    try:
        return await export_tong_quan(
            session, shop_id, shop.shop_name, product_id=product_id,
            **window_args(period, month, start, end, as_of),
        )  # fmt: skip
    except REFUSALS as exc:
        raise refusal(exc) from None


@router.get("/exports/ke-hoach.xlsx")
async def shopee_export_ke_hoach(
    request: Request,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    all_shops: Annotated[bool, Query()] = False,
    shop: Shop = Depends(_gate_x),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Kế hoạch as an Excel file: the cards active in the range, the goals, the KOLs.
    ``all_shops`` (G23): every accessible shop, Shop and Platform columns."""
    if all_shops and reviewer_context(request) is None:
        try:
            return await export_ke_hoach_all(session, user.id, start, end)
        except REFUSALS as exc:
            raise refusal(exc) from None
    shop_id = shop.id
    try:
        return await export_ke_hoach(session, shop_id, shop.shop_name, start, end)
    except REFUSALS as exc:
        raise refusal(exc) from None
