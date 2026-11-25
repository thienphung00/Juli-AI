"""Where ``metrics.query`` reads a window's rows from: the stored facts when they are ready, else
the SAME rows built from the raw tables on the fly (owner #74: no "—" during the post-deploy
backfill).

A window is *ready* when Track FACT's status row says so (``materialize.facts_ready``: the
shop's backfill is of this code version and complete, or current from before the window's first
day). Otherwise the window's rows come from :func:`rows_from_raw` (``materialize.compute_facts``:
the rebuild's own builder in memory, nothing written) and ``metrics.query`` evaluates the same
registry formulas over them. Results are cached on the session for the request.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from juli_backend.services.metrics.query import MemoryRowSource, RowSource

#: ``session.info`` cache keys
_READY_KEY = "juli_facts_ready"
_RAW_KEY = "juli_facts_raw"


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
    """May the window read the stored rows? Track FACT's status row (``materialize.facts_ready``,
    one indexed read), cached per request."""
    cache: dict[tuple[Any, ...], bool] = session.info.setdefault(_READY_KEY, {})
    key = (shop_id, start, end, basis)
    if key not in cache:
        from juli_backend.services.shopee_analytics import materialize

        cache[key] = await materialize.facts_ready(session, shop_id, (start, end))
    return cache[key]


async def rows_from_raw(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date
) -> MemoryRowSource:
    """The window's daily rows built from the raw tables in memory, as the rebuild would store
    them (Track FACT's ``materialize.compute_facts``; writes nothing). It has no zeroed rows of
    products that left a day (those exist only in the stored tables), so such a product reads
    "—" here where the stored rows give 0đ for that day; every metric total is the same."""
    from juli_backend.services.shopee_analytics import materialize

    rows = await materialize.compute_facts(session, shop_id, start, end)
    return MemoryRowSource(
        {
            "shop_metrics_daily": rows.shop_metrics_daily,
            "product_metrics_daily": rows.product_metrics_daily,
            "source_metrics_daily": rows.source_metrics_daily,
            "product_channel_metrics_daily": rows.product_channel_metrics_daily,
            "shop_channel_metrics_daily": rows.shop_channel_metrics_daily,
            "campaign_metrics_daily": rows.campaign_metrics_daily,
        }
    )


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


__all__ = ["data_days", "facts_ready", "rows_from_raw", "source_for"]
