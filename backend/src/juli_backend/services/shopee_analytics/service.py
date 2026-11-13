"""Session-level entry points: load a window, compute its view, hand it to a builder.

Callers (the Demo and Ops routes, the acceptance script) run inside the shop's own scope
(``with_shop_scope`` / ``get_active_shop``); every read goes through a repository, so RLS and
the explicit ``shop_id`` filter both apply.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.ingest import readers
from juli_backend.services.shopee_analytics import funnel as funnel_mod
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics import stored as stored_mod
from juli_backend.services.shopee_analytics.compute import PeriodData, PeriodView, compute_view
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.windows import Anchor, Window, resolve_window


async def load_period_data(
    session: AsyncSession, shop_id: uuid.UUID, window: Window, *, rows: str = "raw"
) -> PeriodData:
    """``rows`` (P99b): "require" / "soft" / "raw" -- see ``PeriodData.rows_policy``; the data
    days of the window are read for the first two."""
    return PeriodData(
        rows_policy=rows,
        data_days=None
        if rows == "raw"
        else await stored_mod.data_days_in(session, shop_id, window),
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
        ad_spend=await loaders.load_resolved_ad_spend(session, shop_id, window),
        voucher_join=await readers.load_voucher_join(session, shop_id),
        stored=await stored_mod.load_stored(session, shop_id, window),
    )


async def load_view(
    session: AsyncSession,
    shop_id: uuid.UUID,
    ctx: ShopContext,
    window: Window,
    *,
    funnel: bool = False,
    rows: str | None = None,
) -> PeriodView:
    """The window's view. ``funnel`` True (the screens): Lượt xem / lượt nhấp / CTR / CTOR and the
    flow tables read the stored source funnel (P98 / ADR-122 d.2); the metrics rebuild keeps the
    raw tables (False), since it is what writes the funnel.

    ``rows`` (P99b): "require" (default for a screen, ``funnel`` True) raises
    :class:`stored.RowsNotMaterialized` at once when a data day of the window has no stored daily
    row; "soft" (a comparison window) keeps the view but marks it not comparable; "raw" (default
    otherwise) reads the raw tables as before."""
    policy = rows or ("require" if funnel else "raw")
    view = compute_view(ctx, await load_period_data(session, shop_id, window, rows=policy))
    if funnel:
        funnel_mod.apply_to_view(view, await funnel_mod.load_rows(session, shop_id, window))
    if policy == "require":
        _ = view.metrics  # raise the missing-rows state here, before any screen reads a number
    return view


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


async def anchor_for(
    session: AsyncSession, shop_id: uuid.UUID, as_of: date | None = None
) -> Anchor | None:
    """The anchor a request's window hangs on, named in the payload (D85.2): the last complete
    day every live daily dataset posted, or the day the caller asked for."""
    found = await loaders.load_anchor(session, shop_id)
    if as_of is None:
        return found
    if found is None:
        return Anchor(as_of, as_of, None, {}, (), "requested")
    return Anchor(as_of, found.newest, None, found.datasets, found.stale, "requested")
