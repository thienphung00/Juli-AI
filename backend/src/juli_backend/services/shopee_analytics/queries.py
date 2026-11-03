"""The read APIs as functions: one per screen, session + shop in, JSON-ready dict out.

Each call resolves its window from the request (``7d`` / ``30d`` / ``90d`` / ``month`` /
``custom``, ending on the newest day the shop has data for unless ``as_of`` is given), loads that
window and the previous one (same length, the days before it), and hands both views to the
matching builder. Nothing is written. The caller runs inside the shop's scope.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.critical import build_critical
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.matrix import SORTS, build_matrix
from juli_backend.services.shopee_analytics.overview import build_overview
from juli_backend.services.shopee_analytics.product import build_product_page
from juli_backend.services.shopee_analytics.rankings import build_ranking
from juli_backend.services.shopee_analytics.windows import Window

PRODUCT_PERIODS: tuple[str, ...] = ("7d", "30d", "90d")


class NoShopeeData(LookupError):
    """The shop has no Shopee numbers to anchor a window on."""


class ProductNotFound(LookupError):
    pass


async def _views(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str,
    month: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
) -> tuple[ShopContext, PeriodView, PeriodView]:
    window = await service.resolve(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    now = await service.load_view(session, shop_id, ctx, window)
    before = await service.load_view(session, shop_id, ctx, window.previous())
    return ctx, now, before


async def overview(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    ctx, now, before = await _views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    body = build_overview(ctx, now, before)
    body["period"]["kind"] = period
    return body


async def matrix(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    sort: str = "gmv",
    limit: int | None = None,
) -> dict[str, Any]:
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {list(SORTS)}")
    _, now, _ = await _views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return build_matrix(now, sort=sort, limit=limit)


async def critical(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    ctx, now, _ = await _views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    series = await loaders.load_flow_series(session, shop_id, now.window.end)
    return build_critical(ctx, now, series)


async def ranking(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    kind: str = "products",
    source: str = "all",
    sub: str | None = None,
    xep_theo: str = "gmv_per_day",
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    _, now, before = await _views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return build_ranking(now, before, kind=kind, source=source, sub=sub, xep_theo=xep_theo)


async def product_page(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    period: str = "30d",
    as_of: date | None = None,
) -> dict[str, Any]:
    if period not in PRODUCT_PERIODS:
        raise ValueError(f"period must be one of {list(PRODUCT_PERIODS)}")
    anchor = as_of or await loaders.default_as_of(session, shop_id)
    if anchor is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{anchor:%Y-%m}"))
    views: dict[str, tuple[PeriodView, PeriodView]] = {}
    for key in PRODUCT_PERIODS:
        window = await service.resolve(session, shop_id, period=key, as_of=anchor)
        assert isinstance(window, Window)
        views[key] = (
            await service.load_view(session, shop_id, ctx, window),
            await service.load_view(session, shop_id, ctx, window.previous()),
        )
    known = (
        item_id in ctx.catalog.items
        or any(item_id in v[0].matrix.totals for v in views.values())
        or any(item_id in v[0].data.product_flows.totals for v in views.values())
    )
    if not known:
        raise ProductNotFound(item_id)
    snap = await loaders.load_item_header(session, shop_id, item_id)
    seeds = await loaders.load_keyword_seeds(session, shop_id, item_id)
    market = await loaders.load_keyword_market(session, [s.keyword for s in seeds])
    return build_product_page(ctx, item_id, views, period, snap, seeds, market, anchor)
