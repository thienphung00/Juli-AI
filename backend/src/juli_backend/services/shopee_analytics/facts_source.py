"""Where ``metrics.query`` reads a window's rows from: the stored facts when they are ready, else
the SAME rows built from the raw tables on the fly (owner #74: no "—" during the post-deploy
backfill).

A window is *ready* when every data day of it (order lines or daily Shopee rows,
``stored.data_days_in``) has a stored shop row built by the current rule (``derivation_version``
starts with the registry version and the rows rule of ``materialize.stamp_of``). Otherwise the
window's rows come from :func:`rows_from_raw`: the rebuild's own row builder
(``materialize.day_rows`` + ``day_facts.campaign_rows``) run in memory, nothing written, and
``metrics.query`` evaluates the same registry formulas over them.

The seam with Track FACT is :func:`rows_from_raw` (one function): when FACT's in-memory entry
point lands, it replaces the body. Results are cached on the session for the request.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.metrics.query import MemoryRowSource, RowSource
from juli_backend.services.metrics.registry import DERIVATION_VERSION

#: ``session.info`` cache keys
_READY_KEY = "juli_facts_ready"
_RAW_KEY = "juli_facts_raw"


def current_prefix() -> str:
    """The part of ``materialize.stamp_of`` every current row starts with (registry version and
    rows rule; the fee digest is checked by the rebuild's own outdated-days job)."""
    from juli_backend.services.shopee_analytics.materialize import ROWS_VERSION

    return f"{DERIVATION_VERSION}/r{ROWS_VERSION}/"


_DATA_KEY = "juli_facts_data_days"


@event.listens_for(Session, "after_flush")
def _forget(session: Session, _ctx: Any) -> None:
    """A write in the session (a rebuild, an ingest) makes the cached readiness stale."""
    for key in (_READY_KEY, _RAW_KEY, _DATA_KEY):
        session.info.pop(key, None)


@event.listens_for(Session, "do_orm_execute")
def _forget_on_write(state: ORMExecuteState) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        _forget(state.session, None)


async def data_days(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date
) -> frozenset[date]:
    """The days of ``start..end`` with any raw data (``stored.data_days_in``), cached per request.
    A window day outside them is no data, not a missing day."""
    cache: dict[tuple[Any, ...], frozenset[date]] = session.info.setdefault(_DATA_KEY, {})
    key = (shop_id, start, end)
    if key not in cache:
        from juli_backend.services.shopee_analytics import stored
        from juli_backend.services.shopee_analytics.windows import Window

        cache[key] = await stored.data_days_in(session, shop_id, Window(start, end))
    return cache[key]


async def facts_ready(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date, basis: str
) -> bool:
    """Every data day of ``start..end`` has a current stored shop row."""
    cache: dict[tuple[Any, ...], bool] = session.info.setdefault(_READY_KEY, {})
    key = (shop_id, start, end, basis)
    if key in cache:
        return cache[key]
    t = ShopeeShopMetricsDaily
    prefix = current_prefix()
    stamps = (
        await session.execute(
            select(t.day, t.derivation_version).where(
                t.shop_id == shop_id, t.order_type == basis, t.day >= start, t.day <= end
            )
        )
    ).all()
    current = {d for d, v in stamps if v is not None and str(v).startswith(prefix)}
    ready = len(current) == len(stamps)
    if ready:
        ready = await data_days(session, shop_id, start, end) <= current
    cache[key] = ready
    return ready


async def rows_from_raw(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date
) -> MemoryRowSource:
    """The window's daily rows built from the raw tables in memory, as the rebuild would store
    them (shop, product, source, channel cells, shop channel cells, campaign days)."""
    from juli_backend.services.shopee_analytics import (
        day_facts,
        loaders,
        materialize,
        period_spread,
        service,
    )
    from juli_backend.services.shopee_analytics.windows import Window

    days = sorted(await data_days(session, shop_id, start, end))
    out = MemoryRowSource(
        {
            "shop_metrics_daily": [],
            "product_metrics_daily": [],
            "source_metrics_daily": [],
            "product_channel_metrics_daily": [],
            "shop_channel_metrics_daily": [],
            "campaign_metrics_daily": [],
        }
    )
    if not days:
        return out
    ctx0 = await loaders.load_context(session, shop_id)
    version = materialize.stamp_of(ctx0)
    facts = await materialize._load_day_facts(session, shop_id, days[0], days[-1])
    series: dict[Any, dict[date, Any]] = {}
    for day in days:
        ctx = replace(ctx0, rules=ctx0.rules.for_month(f"{day:%Y-%m}"))
        view = await service.load_view(session, shop_id, ctx, Window(day, day))
        shop_days: dict[date, Any] = {}
        for period in period_spread.periods_to_load(view.data.product_flows, day):
            if period not in series:
                series[period] = await period_spread.load_shop_days(session, shop_id, period)
            shop_days.update(series[period])
        rows = materialize.day_rows(
            view,
            shop_id,
            day,
            await materialize._traffic_tag(session, shop_id, day),
            await materialize._ads_day(session, shop_id, day),
            period_spread.for_view(view, day, shop_days),
            item_report=facts.item_report.get(day),
            ads_figures=day_facts.ads_figures_by_item(facts.ad_rows, day),
            version=version,
        )
        out.tables["shop_metrics_daily"].append(rows.shop)
        out.tables["product_metrics_daily"].extend(rows.products)
        out.tables["source_metrics_daily"].extend(rows.sources)
        out.tables["product_channel_metrics_daily"].extend(rows.channels)
        out.tables["shop_channel_metrics_daily"].extend(rows.shop_channels)
        out.tables["campaign_metrics_daily"].extend(
            day_facts.campaign_rows(
                facts.campaign_days.get(day, []),
                shop_id=shop_id,
                day=day,
                version=version,
                contribution_by_campaign=materialize._campaign_contribution(
                    rows.products, facts, day
                ),
            )
        )
    return out


async def source_for(
    session: AsyncSession,
    shop_id: uuid.UUID,
    start: date,
    end: date,
    basis: str,
    stored_source: RowSource,
    *,
    force_raw: bool = False,
) -> RowSource:
    """``stored_source`` when the window is ready, else the window's rows from the raw tables."""
    if not force_raw and await facts_ready(session, shop_id, start, end, basis):
        return stored_source
    cache: dict[tuple[Any, ...], MemoryRowSource] = session.info.setdefault(_RAW_KEY, {})
    key = (shop_id, start, end)
    if key not in cache:
        cache[key] = await rows_from_raw(session, shop_id, start, end)
    return cache[key]


__all__ = ["current_prefix", "data_days", "facts_ready", "rows_from_raw", "source_for"]
