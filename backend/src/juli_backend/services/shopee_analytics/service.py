"""Session-level entry points: load a window, compute its view, hand it to a builder.

Callers (the Demo and Ops routes, the acceptance script) run inside the shop's own scope
(``with_shop_scope`` / ``get_active_shop``); every read goes through a repository, so RLS and
the explicit ``shop_id`` filter both apply.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.compute import PeriodData, PeriodView, compute_view
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.windows import Window, resolve_window


async def load_period_data(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> PeriodData:
    return PeriodData(
        window=window,
        lines=await loaders.load_order_lines(session, shop_id, window),
        totals=await loaders.load_shop_totals(session, shop_id, window),
        traffic=await loaders.load_shop_traffic(session, shop_id, window),
        ads_daily=await loaders.load_ads_daily(session, shop_id, window),
        product_flows=await loaders.load_product_flows(session, shop_id, window),
        ads_reports=await loaders.load_ads_reports(session, shop_id, window),
        vouchers=await loaders.load_vouchers(session, shop_id, window),
        promotions=await loaders.load_promotions(session, shop_id, window),
        affiliate=await loaders.load_affiliate(session, shop_id, window),
    )


async def load_view(
    session: AsyncSession, shop_id: uuid.UUID, ctx: ShopContext, window: Window
) -> PeriodView:
    return compute_view(ctx, await load_period_data(session, shop_id, window))


async def resolve(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> Window | None:
    """The window for a request; None when the shop has no Shopee data at all."""
    anchor = as_of or await loaders.default_as_of(session, shop_id)
    if anchor is None:
        return None
    return resolve_window(period, as_of=anchor, month=month, start=start, end=end)
