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

from juli_backend.repositories import PlatformItemSnapshotsRepo
from juli_backend.services.capabilities import Route, can
from juli_backend.services.ingest import read_days
from juli_backend.services.shopee_analytics import (
    ads_gate,
    default_period,
    kol,
    loaders,
    service,
    stored,
)
from juli_backend.services.shopee_analytics import kol_compare as kol_compare_mod
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.critical import build_critical
from juli_backend.services.shopee_analytics.default_period import DefaultPick
from juli_backend.services.shopee_analytics.fmt import pct
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.matrix import (
    SORTS,
    build_matrix,
    margin_basis,
    price_block,
)
from juli_backend.services.shopee_analytics.orders import build_orders
from juli_backend.services.shopee_analytics.overview import build_overview
from juli_backend.services.shopee_analytics.product import build_product_page
from juli_backend.services.shopee_analytics.rankings import build_ranking
from juli_backend.services.shopee_analytics.shared import shop_profit_fields
from juli_backend.services.shopee_analytics.windows import InvalidWindow, Window
from juli_backend.services.shopee_profit.shop_profit import product_margin_pct_shown

PRODUCT_PERIODS: tuple[str, ...] = ("7d", "30d", "90d")


def freshness_json(latest: dict[str, Any], anchor: date) -> dict[str, Any]:
    """Per dataset the newest stored day and how many days it trails ``anchor`` (the window end);
    the screens decide when "old" begins."""
    return {
        "as_of": anchor.isoformat(),
        "datasets": {
            name: {
                "kind": v["kind"],
                "latest_day": v["latest_day"].isoformat(),
                "age_days": (anchor - v["latest_day"]).days,
            }
            for name, v in sorted(latest.items())
        },
    }


async def unsettled_freshness(
    session: AsyncSession, shop_id: uuid.UUID, platform: str
) -> dict[str, Any] | None:
    """7b: ``freshness.unsettled_orders`` -- completed orders still unpaid over 2 days later
    (``{count, oldest_completed_on}``), Shopee shops only. The one computation behind the
    overview and the channel split (Tổng quan reads the latter); a platform without the
    ``unsettled_orders`` capability (TikTok) gets ``None``."""
    if can(platform, "unsettled_orders").route is Route.none:
        return None
    return await read_days.unsettled_status(session, shop_id, platform)


class NoShopeeData(LookupError):
    """The shop has no numbers (Shopee or TikTok) to anchor a window on; the route words the
    refusal by the shop's platform."""


async def default_anchor(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    """The window end every screen shares (``loaders.default_as_of``); a shop with none of
    the raw anchors (a TikTok shop, W3) anchors on its newest complete layer-4 day."""
    return await loaders.default_as_of(session, shop_id) or await stored.last_complete_day(
        session, shop_id
    )


async def resolve_screen_window(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> tuple[Window | None, DefaultPick | None]:
    """:func:`resolve_window` plus, for ``period`` ``auto`` (the screen's default, nothing chosen),
    the :class:`default_period.DefaultPick` whose dates the payload names (``default_period``)."""
    if period != default_period.AUTO:
        return await resolve_window(
            session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
        ), None
    newest = await resolve_window(
        session, shop_id, period=f"{default_period.DEFAULT_DAYS}d", as_of=as_of
    )
    if newest is None:
        return None, None
    pick = await default_period.default_window(session, shop_id, newest.end)
    return pick.window, pick


def with_default(body: dict[str, Any], pick: DefaultPick | None) -> dict[str, Any]:
    """Owner #85/#94: a payload opened on the default period names it (``default_period``: its
    ``from`` / ``to``); a period the seller chose adds nothing."""
    if pick is not None:
        body["default_period"] = pick.json()
    return body


async def resolve_window(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> Window | None:
    """``service.resolve``, anchored on the newest complete layer-4 day when the raw tables give
    none. A shop that has a raw anchor (every Shopee shop with data) resolves exactly as before.
    ``period`` ``auto``: the default period (:mod:`.default_period`)."""
    if period == default_period.AUTO:
        window, _ = await resolve_screen_window(session, shop_id, period=period, as_of=as_of)
        return window
    window = await service.resolve(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is not None or as_of is not None:
        return window
    day = await stored.last_complete_day(session, shop_id)
    if day is None:
        return None
    return await service.resolve(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=day
    )


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
    ctx, now, before, _ = await _screen_views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return ctx, now, before


async def _screen_views(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str,
    month: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
) -> tuple[ShopContext, PeriodView, PeriodView, DefaultPick | None]:
    window, pick = await resolve_screen_window(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    now = await service.load_view(session, shop_id, ctx, window, funnel=True)
    # P99b: the comparison window never errors the screen; without stored rows it is withheld
    before = await service.load_view(
        session, shop_id, ctx, window.previous(), funnel=True, rows="soft"
    )
    return ctx, now, before, pick


async def overview(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    platform: str = "shopee",
) -> dict[str, Any]:
    ctx, now, before, pick = await _screen_views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    anchor = await service.anchor_for(session, shop_id, as_of)
    body = build_overview(ctx, now, before, anchor, platform)
    body["period"]["kind"] = period
    body["freshness"] = freshness_json(
        await loaders.load_freshness(session, shop_id), now.window.end
    )
    unsettled = await unsettled_freshness(session, shop_id, platform)
    if unsettled is not None:
        body["freshness"]["unsettled_orders"] = unsettled
    return with_default(body, pick)


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
    platform: str = "shopee",
) -> dict[str, Any]:
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {list(SORTS)}")
    _, now, before, pick = await _screen_views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return with_default(
        build_matrix(now, sort=sort, limit=limit, before=before, platform=platform), pick
    )


async def product_price_margin(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    start: date,
    end: date,
    item_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """P92 B-9: giá (min-max, list price) and biên with its basis label for ``item_ids`` over one
    exact window, the same figures the matrix shows. Used by the Ops / Demo funnel table, whose
    period is a Shopee export period rather than a rolling window. Empty when the shop has no
    Shopee order data (the table then shows dashes)."""
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{end:%Y-%m}"))
    window = await service.resolve(session, shop_id, period="custom", start=start, end=end)
    if window is None:
        return {}
    view = await service.load_view(session, shop_id, ctx, window)
    out: dict[str, dict[str, Any]] = {}
    for item_id in item_ids:
        pp = view.profit.products.get(item_id)
        out[item_id] = {
            **price_block(view, item_id),
            "margin_pct": None if pp is None else pct(product_margin_pct_shown(pp)),
            "margin_basis": margin_basis(view, item_id, pp),
        }
    return out


async def window_metrics(
    session: AsyncSession, shop_id: uuid.UUID, *, start: date, end: date
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """ShopMetrics for one exact window and the excluded listings (item id -> reason): what the
    Ops / Demo Sản phẩm + luồng tables put beside their per-flow SQL so their headline is the
    same number as every other screen (D85.2). None when the shop has no Shopee order data."""
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{end:%Y-%m}"))
    try:
        window = await service.resolve(session, shop_id, period="custom", start=start, end=end)
    except InvalidWindow:
        return None
    if window is None:
        return None
    view = await service.load_view(session, shop_id, ctx, window, funnel=True)
    # P100 B.5: the shop profit is the one known-cost figure, never the scaled stored sum
    return {**view.metrics.json(), **shop_profit_fields(view)}, dict(view.excluded)


async def orders(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    status: str | None = None,
    lever: str | None = None,
    sort: str = "date",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Đơn hàng: one row per confirmed order, hashed key, no buyer data."""
    window = await resolve_window(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    view = await service.load_view(session, shop_id, ctx, window)
    return build_orders(view, status=status, lever=lever, sort=sort, limit=limit, offset=offset)


async def critical(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    platform: str = "shopee",
) -> dict[str, Any]:
    ctx, now, before, pick = await _screen_views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    series = await loaders.load_flow_series(session, shop_id, now.window.end)
    return with_default(build_critical(ctx, now, series, before, platform), pick)


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
    platform: str = "shopee",
) -> dict[str, Any]:
    reason = ads_gate.ads_unknown(platform)
    if reason is not None and xep_theo in ads_gate.PROFIT_RANKINGS:
        # W3-Q5: a profit ranking needs ads spend: refused, not ranked on a before-ads figure
        return {
            "platform": platform,
            "kind": kind,
            "source": source,
            "sub": sub,
            "supported": False,
            "reason": reason,
            "message": "Chưa có chi phí quảng cáo nên chưa xếp hạng được theo lợi nhuận.",
        }
    _, now, before, pick = await _screen_views(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return with_default(
        build_ranking(
            now, before, kind=kind, source=source, sub=sub, xep_theo=xep_theo, platform=platform
        ),
        pick,
    )


async def product_page(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    period: str = "30d",
    as_of: date | None = None,
    platform: str = "shopee",
) -> dict[str, Any]:
    if period not in (*PRODUCT_PERIODS, default_period.AUTO):
        raise ValueError(f"period must be one of {list(PRODUCT_PERIODS)}")
    pick: DefaultPick | None = None
    if period == default_period.AUTO:
        # owner #85/#94: the page opens on the default 30 days; its 7 / 90 days share that end
        window_auto, pick = await resolve_screen_window(
            session, shop_id, period=period, as_of=as_of
        )
        if window_auto is None:
            raise NoShopeeData(str(shop_id))
        period, as_of = f"{default_period.DEFAULT_DAYS}d", window_auto.end
    anchor = as_of or await default_anchor(session, shop_id)
    if anchor is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{anchor:%Y-%m}"))
    views: dict[str, tuple[PeriodView, PeriodView]] = {}
    for key in PRODUCT_PERIODS:
        window = await service.resolve(session, shop_id, period=key, as_of=anchor)
        assert isinstance(window, Window)
        views[key] = (
            await service.load_view(session, shop_id, ctx, window, funnel=True),
            await service.load_view(
                session, shop_id, ctx, window.previous(), funnel=True, rows="soft"
            ),
        )
    known = (
        item_id in ctx.catalog.items
        or any(item_id in v[0].matrix.totals for v in views.values())
        or any(item_id in v[0].data.product_flows.totals for v in views.values())
    )
    if not known:
        raise ProductNotFound(item_id)
    snap = await loaders.load_item_header(session, shop_id, item_id)
    history = await PlatformItemSnapshotsRepo(session).history(shop_id, item_id)
    selected_window = views[period][0].window
    daily = await loaders.load_product_daily(session, shop_id, item_id, selected_window)
    freshness = freshness_json(await loaders.load_freshness(session, shop_id), anchor)
    seeds = await loaders.load_keyword_seeds(session, shop_id, item_id)
    market = await loaders.load_keyword_market(session, [s.keyword for s in seeds])
    body = build_product_page(
        ctx,
        item_id,
        views,
        period,
        snap,
        seeds,
        market,
        anchor,
        history=history,
        daily=daily,
        freshness=freshness,
        platform=platform,
    )
    return with_default(body, pick)


# ---------------------------------------------------------------------------- KOL (P91 D-9)


async def _kol_view_model(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str,
    month: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
) -> tuple[PeriodView, kol.KolModel]:
    window = await resolve_window(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    view = await service.load_view(session, shop_id, ctx, window)
    return view, await kol.load_model(session, shop_id, ctx, view)


async def _kol_model(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str,
    month: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
) -> kol.KolModel:
    _, model = await _kol_view_model(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return model


async def kol_table(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    channel: str | None = None,
    item_id: str | None = None,
    kol_key: str | None = None,
    sort: str = "net_profit",
    limit: int | None = None,
) -> dict[str, Any]:
    """Phân tích › KOL: KOL x sản phẩm x kênh."""
    model = await _kol_model(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return kol.table(model, channel=channel, item_id=item_id, kol=kol_key, sort=sort, limit=limit)


async def kol_product_tab(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Sản phẩm › Tiếp thị liên kết: the KOLs who sold (or got a sample of) one product."""
    model = await _kol_model(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    return kol.product_tab(model, item_id)


async def kol_compare(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    group: str = "channel",
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Phân tích › KOL › So sánh: the KOL rows by kênh / loại chiến dịch / KOL, and Affiliate vs
    Ads vs the shop's own flows for the same window (P100)."""
    if group not in kol_compare_mod.GROUPS:
        raise ValueError(f"group must be one of {list(kol_compare_mod.GROUPS)}")
    view, model = await _kol_view_model(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    body = kol_compare_mod.compare(view, model, group)
    body["window"] = {**body["window"], "kind": period}
    return body
