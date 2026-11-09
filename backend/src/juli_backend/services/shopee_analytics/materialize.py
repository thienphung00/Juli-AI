"""Build the materialized metrics (P97 D85.2): the shop's day and its product rows.

``rebuild_days`` recomputes whole days from the raw tables (order lines, daily totals, traffic,
ads) through the same ``compute_view`` the screens used to run per request, then upserts
``shopee_shop_metrics_daily`` and ``shopee_product_metrics_daily``. Idempotent: the same raw data
gives the same rows (rows are upserted on their natural key; a product that left a day is
zeroed, not deleted). The product rows of a day plus the ``__residual__`` row add up to the shop
row. ``after_ingest`` is the one hook the ingest gateway calls after a write; ``backfill_shop``
walks every day a shop has data (``scripts/backfill_shopee_metrics.py``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.repositories import PlatformDailyMetricsRepo
from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.metrics import (
    SPLIT_PRODUCT_PERIOD,
    shop_metrics,
)
from juli_backend.services.shopee_analytics.stored import ORDER_TYPE
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.money import ZERO

logger = logging.getLogger(__name__)

#: ingest datasets that cannot change a day's shop or product numbers
IGNORED_DATASETS = frozenset({"market_search", "shop_health", "ads_change_log", "item_snapshot"})
#: the hook rebuilds at most this many of the newest days inline; the backfill covers older ones
HOOK_MAX_DAYS = 45
DAILY_DATASETS = ("shop_overview", "traffic_overview", "shop_traffic")


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


@dataclass
class DayRows:
    shop: dict[str, Any]
    products: list[dict[str, Any]]


def _funnel(rows: Any) -> tuple[int | None, int | None]:
    views = [r.views for r in rows if not r.is_residual and r.views is not None]
    clicks = [r.clicks for r in rows if not r.is_residual and r.clicks is not None]
    return (sum(views) if views else None, sum(clicks) if clicks else None)


def day_rows(view: PeriodView, shop_id: uuid.UUID, day: date, traffic_tag: str) -> DayRows:
    """The rows of one day from its (one-day) view. Pure."""
    m = shop_metrics(view)
    p = view.profit
    complete = view.data.totals.basis == "daily" and view.data.traffic.basis == "daily"
    sources = {
        "gmv": "shop_totals" if view.data.totals.basis == "daily" else "order_lines",
        "orders": "shop_totals" if view.data.totals.basis == "daily" else "order_lines",
        "views": traffic_tag,
        "product_clicks": traffic_tag,
        "ads_spend": traffic_tag,
        "profit": "order_lines",
    }
    covered = p.buyer_paid_covered
    net_gmv = sum((ln.order_value - ln.shop_voucher_share for ln, _ in view.pairs), ZERO)
    shop = {
        "shop_id": shop_id,
        "day": day,
        "order_type": ORDER_TYPE,
        "gmv": _money(m.gmv),
        "orders": m.orders,
        "aov": _money(m.aov),
        "units": m.units or None,
        "views": m.views,
        "visitors": None,
        "product_clicks": m.clicks,
        "ads_spend": _money(m.ad_spend),
        "ads_gmv": _money(view.data.ads_daily.gmv),
        "profit": _money(m.profit),
        "margin_profit": _money(p.covered_margin_profit),
        "buyer_paid_known": _money(covered),
        "cogs_coverage": None
        if not p.buyer_paid
        else (covered / p.buyer_paid).quantize(Decimal("0.0001")),
        "line_gmv": _money(m.line_gmv),
        "line_orders": m.line_orders,
        "sources": sources,
        "detail": {
            "aov_sc_net_gmv": None if not m.line_orders else str(net_gmv),
            "profit_partial": bool(m.profit_is_partial),
        },
        "complete": complete,
    }
    products: list[dict[str, Any]] = []
    spent = ZERO
    for item_id, s in sorted(m.splits.items()):
        flow = view.flows.products.get(item_id) if view.flows else None
        views, clicks = _funnel(flow.rows) if flow else (None, None)
        pp = p.products.get(item_id)
        profit = pp.profit if pp is not None else None
        if profit is not None and m.gmv_scale is not None and view.line_gmv > 0:
            profit = profit * m.gmv_scale
        spent += s.gmv
        products.append(
            {
                "shop_id": shop_id,
                "day": day,
                "order_type": ORDER_TYPE,
                "item_id": item_id,
                "variation_id": None,
                "gmv": _money(s.gmv),
                "orders": s.orders,
                "units": s.units,
                "views": views,
                "clicks": clicks,
                "ads_spend": _money(view.ads.product_spend.get(item_id)),
                "profit": _money(profit),
                "line_gmv": _money(s.line_gmv),
                "line_orders": s.line_orders,
                "source": "order_lines" if s.basis != SPLIT_PRODUCT_PERIOD else "file",
                "scaled_to_totals": s.basis in ("scaled_order_lines", SPLIT_PRODUCT_PERIOD),
            }
        )
    residual = (m.gmv - spent) if m.gmv is not None else ZERO
    products.append(
        {
            "shop_id": shop_id,
            "day": day,
            "order_type": ORDER_TYPE,
            "item_id": RESIDUAL_ITEM,
            "variation_id": None,
            "gmv": _money(residual),
            "orders": 0,
            "units": 0,
            "views": None,
            "clicks": None,
            "ads_spend": None,
            "profit": None,
            "line_gmv": ZERO,
            "line_orders": 0,
            "source": "shop_totals",
            "scaled_to_totals": False,
        }
    )
    return DayRows(shop, products)


async def _traffic_tag(session: AsyncSession, shop_id: uuid.UUID, day: date) -> str:
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=[loaders.TRAFFIC_DAILY],
        start=day,
        end=day,
        streams=["product_card"],
        order_types=[loaders.CONFIRMED],
    )
    tags = {str(getattr(r, "source", "")) for r in rows}
    return "connector" if "connector" in tags else "file"


async def _upsert(
    session: AsyncSession, model: Any, values: list[dict[str, Any]], keys: tuple[str, ...]
) -> None:
    if not values:
        return
    insert = _insert(session)
    now = datetime.now(UTC).replace(tzinfo=None)
    stmt = insert(model).values([{**v, "id": uuid.uuid4(), "built_at": now} for v in values])
    update = {
        c.name: stmt.excluded[c.name]
        for c in model.__table__.columns
        if c.name not in ("id", "shop_id", *keys)
    }
    await session.execute(stmt.on_conflict_do_update(index_elements=list(keys), set_=update))


async def rebuild_days(session: AsyncSession, shop_id: uuid.UUID, days: Iterable[date]) -> int:
    """Recompute and upsert these days. Returns the number of days written."""
    wanted = sorted(set(days))
    if not wanted:
        return 0
    ctx0 = await loaders.load_context(session, shop_id)
    for day in wanted:
        ctx = replace(ctx0, rules=ctx0.rules.for_month(f"{day:%Y-%m}"))
        view = await service.load_view(session, shop_id, ctx, Window(day, day))
        rows = day_rows(view, shop_id, day, await _traffic_tag(session, shop_id, day))
        have = set(
            (
                await session.execute(
                    select(ShopeeProductMetricsDaily.item_id).where(
                        ShopeeProductMetricsDaily.shop_id == shop_id,
                        ShopeeProductMetricsDaily.day == day,
                        ShopeeProductMetricsDaily.order_type == ORDER_TYPE,
                    )
                )
            )
            .scalars()
            .all()
        )
        now_items = {r["item_id"] for r in rows.products}
        for gone in sorted(have - now_items):  # left the day: zeroed, not deleted
            rows.products.append(
                {
                    "shop_id": shop_id, "day": day, "order_type": ORDER_TYPE, "item_id": gone,
                    "variation_id": None, "gmv": ZERO, "orders": 0, "units": 0, "views": None,
                    "clicks": None, "ads_spend": None, "profit": None, "line_gmv": ZERO,
                    "line_orders": 0, "source": "order_lines", "scaled_to_totals": False,
                }
            )  # fmt: skip
        await _upsert(
            session, ShopeeShopMetricsDaily, [rows.shop], ("shop_id", "day", "order_type")
        )
        await _upsert(
            session,
            ShopeeProductMetricsDaily,
            rows.products,
            ("shop_id", "day", "order_type", "item_id"),
        )
    await session.flush()
    return len(wanted)


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def after_ingest(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    platform: str,
    dataset: str,
    start: date,
    end: date,
) -> None:
    """The hook the ingest gateway calls after a (non-duplicate) write: rebuild the affected
    days. Never raises into the ingest: a failed rebuild is logged and the backfill repairs it."""
    if platform != "shopee" or dataset in IGNORED_DATASETS or dataset.endswith("_period"):
        return
    days = days_between(start, end)[-HOOK_MAX_DAYS:]
    try:
        async with session.begin_nested():
            await rebuild_days(session, shop_id, days)
    except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
        # the ingest must not fail because a derived table did
        logger.warning(
            "shopee_metrics_rebuild_failed",
            extra={"shop_id": str(shop_id), "dataset": dataset, "days": len(days)},
            exc_info=True,
        )


async def data_days(session: AsyncSession, shop_id: uuid.UUID) -> list[date]:
    """Every day the shop has order lines or daily Shopee rows for."""
    out: set[date] = set()
    lines = await session.execute(
        select(ShopeeOrderLine.ordered_at).where(ShopeeOrderLine.shop_id == shop_id)
    )
    out.update(v.date() for v in lines.scalars().all())
    daily = await session.execute(
        select(PlatformDailyMetric.day)
        .where(
            PlatformDailyMetric.shop_id == shop_id,
            PlatformDailyMetric.platform == "shopee",
            PlatformDailyMetric.dataset.in_(DAILY_DATASETS),
        )
        .distinct()
    )
    out.update(daily.scalars().all())
    return sorted(out)


@dataclass
class BackfillReport:
    days_found: int
    days_written: int
    first: date | None
    last: date | None


async def backfill_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
) -> BackfillReport:
    """Rebuild every day the shop has data for (optionally clipped to ``start``..``end``)."""
    days = [
        d
        for d in await data_days(session, shop_id)
        if (not start or d >= start) and (not end or d <= end)
    ]
    written = await rebuild_days(session, shop_id, days)
    return BackfillReport(len(days), written, days[0] if days else None, days[-1] if days else None)


__all__ = ["after_ingest", "backfill_shop", "day_rows", "rebuild_days"]
