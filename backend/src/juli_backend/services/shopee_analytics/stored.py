"""Read side of the materialized metrics (P97 D85.2): the daily rows summed over a window.

``shopee_shop_metrics_daily`` / ``shopee_product_metrics_daily`` are rebuilt by
:mod:`.materialize` after each ingest write. A window is *usable* only when every one of its days
has a ``complete`` shop row (the day's totals are Shopee's own daily numbers); otherwise the
caller computes the window from the raw tables as before. Pure data classes plus two small
queries; no business rule here.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
)
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.shopee_analytics.windows import Window

ORDER_TYPE = "confirmed"
ZERO = Decimal(0)
#: the daily Shopee datasets a day's row is built from (``materialize.DAILY_DATASETS``)
DAILY_DATASETS = ("shop_overview", "traffic_overview", "shop_traffic")
ROWS_MISSING_CODE = "rows_not_materialized"
ROWS_MISSING_TEXT = "Chưa có số liệu theo ngày cho khoảng này — đang tính lại."


class RowsNotMaterialized(Exception):
    """P99b (owner 2026-11-10): a window some of whose data days have no stored daily row. The
    screens show this state instead of numbers -- the raw-table path for a multi-day window is
    the old unspread period split and is never shown."""

    code = ROWS_MISSING_CODE
    message = ROWS_MISSING_TEXT

    def __init__(self, window: Window, missing: list[date]) -> None:
        super().__init__(f"{ROWS_MISSING_CODE}: {window.start}..{window.end}")
        self.window = window
        self.missing = missing

    def json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "window": {"from": self.window.start.isoformat(), "to": self.window.end.isoformat()},
            "missing_days": len(self.missing),
            "first_missing": self.missing[0].isoformat() if self.missing else None,
        }


def _sum(values: list[Decimal | None]) -> Decimal | None:
    known = [v for v in values if v is not None]
    return sum(known, ZERO) if known else None


def _isum(values: list[int | None]) -> int | None:
    known = [v for v in values if v is not None]
    return sum(known) if known else None


@dataclass
class StoredProduct:
    item_id: str
    gmv: Decimal = ZERO
    orders: int = 0
    units: int = 0
    line_gmv: Decimal = ZERO
    line_orders: int = 0
    source: str = "order_lines"
    scaled: bool = False


@dataclass
class StoredWindow:
    window: Window
    days_stored: int
    days_complete: int
    gmv: Decimal | None
    orders: int | None
    units: int | None
    views: int | None
    clicks: int | None
    ads_spend: Decimal | None
    ads_gmv: Decimal | None
    profit: Decimal | None
    margin_profit: Decimal | None
    buyer_paid_known: Decimal | None
    line_gmv: Decimal | None
    line_orders: int | None
    aov_sc_net_gmv: Decimal | None
    profit_partial: bool
    products: dict[str, StoredProduct] = field(default_factory=dict)
    residual_gmv: Decimal = ZERO
    sources: dict[str, str] = field(default_factory=dict)

    #: the days of the window that have a stored row (complete or not)
    days: frozenset[date] = frozenset()
    #: P100-A (B.17): the stored days whose order data arrived (shop đơn not NULL); only these
    #: days are in the sums -- a day without order data is "chưa có dữ liệu", never 0
    data_days: frozenset[date] = frozenset()
    #: product rows over their shop's đơn / GMV that day (stale period stamps), capped on read
    capped_rows: int = 0

    @property
    def days_with_data(self) -> int:
        return len(self.data_days)

    @property
    def usable(self) -> bool:
        return self.days_complete == self.window.days and self.gmv is not None

    def missing(self, data_days: frozenset[date]) -> list[date]:
        """The window's data days (order lines or daily Shopee rows) with no stored row."""
        return sorted(d for d in data_days if d not in self.days)


async def load_stored(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> StoredWindow | None:
    """The window's stored rows summed; None when no day of it is stored."""
    rows = (
        (
            await session.execute(
                select(ShopeeShopMetricsDaily).where(
                    ShopeeShopMetricsDaily.shop_id == shop_id,
                    ShopeeShopMetricsDaily.order_type == ORDER_TYPE,
                    ShopeeShopMetricsDaily.day >= window.start,
                    ShopeeShopMetricsDaily.day <= window.end,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    all_rows = rows
    rows = [r for r in rows if r.orders is not None]  # P100-A: the days with order data only
    shop_day = {r.day: r for r in rows}
    prows = (
        (
            await session.execute(
                select(ShopeeProductMetricsDaily).where(
                    ShopeeProductMetricsDaily.shop_id == shop_id,
                    ShopeeProductMetricsDaily.order_type == ORDER_TYPE,
                    ShopeeProductMetricsDaily.day >= window.start,
                    ShopeeProductMetricsDaily.day <= window.end,
                )
            )
        )
        .scalars()
        .all()
    )
    products: dict[str, StoredProduct] = {}
    residual = ZERO
    capped = 0
    for p in prows:
        day = shop_day.get(p.day)
        if day is None:  # no order data that day: a stale stamp, never part of a window
            continue
        if p.item_id == RESIDUAL_ITEM:
            residual += p.gmv
            continue
        orders, gmv = _capped(p.orders, p.gmv, day)
        capped += (orders, gmv) != (p.orders, p.gmv)
        acc = products.setdefault(p.item_id, StoredProduct(p.item_id))
        acc.gmv += gmv
        acc.orders += orders
        acc.units += p.units
        acc.line_gmv += p.line_gmv
        acc.line_orders += p.line_orders
        acc.source = p.source
        acc.scaled = acc.scaled or p.scaled_to_totals
    by_col: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        for col, tag in (r.sources or {}).items():
            by_col[col].add(str(tag))
    sources = {c: "+".join(sorted(tags)) for c, tags in by_col.items()}
    net = [
        None
        if (r.detail or {}).get("aov_sc_net_gmv") is None
        else Decimal(str(r.detail["aov_sc_net_gmv"]))
        for r in rows
    ]
    return StoredWindow(
        window=window,
        days_stored=len(all_rows),
        days_complete=sum(1 for r in rows if r.complete),
        gmv=_sum([r.gmv for r in rows]),
        orders=_isum([r.orders for r in rows]),
        units=_isum([r.units for r in rows]),
        views=_isum([r.views for r in rows]),
        clicks=_isum([r.product_clicks for r in rows]),
        ads_spend=_sum([r.ads_spend for r in rows]),
        ads_gmv=_sum([r.ads_gmv for r in rows]),
        profit=_sum([r.profit for r in rows]),
        margin_profit=_sum([r.margin_profit for r in rows]),
        buyer_paid_known=_sum([r.buyer_paid_known for r in rows]),
        line_gmv=_sum([r.line_gmv for r in rows]),
        line_orders=_isum([r.line_orders for r in rows]),
        aov_sc_net_gmv=_sum(net),
        profit_partial=any((r.detail or {}).get("profit_partial") for r in rows),
        products=products,
        residual_gmv=residual,
        sources=sources,
        days=frozenset(r.day for r in all_rows),
        data_days=frozenset(shop_day),
        capped_rows=capped,
    )


def _capped(orders: int, gmv: Decimal, shop: ShopeeShopMetricsDaily) -> tuple[int, Decimal]:
    """P100-A (A.3): a product never out-sells its shop on a day. Rows built before the P99
    spread (period totals stamped on one day) are held to the shop's đơn / GMV of that day."""
    if shop.orders is not None and orders > shop.orders:
        orders = shop.orders
    if shop.gmv is not None and gmv > shop.gmv:
        gmv = shop.gmv
    return orders, gmv


async def data_days_in(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> frozenset[date]:
    """The days of ``window`` the shop has order lines or daily Shopee rows for -- the days the
    metrics rebuild writes a stored row for (``materialize.data_days``)."""
    start = datetime.combine(window.start, time.min)
    end = datetime.combine(window.end + timedelta(days=1), time.min)
    lines = await session.execute(
        select(ShopeeOrderLine.ordered_at).where(
            ShopeeOrderLine.shop_id == shop_id,
            ShopeeOrderLine.ordered_at >= start,
            ShopeeOrderLine.ordered_at < end,
        )
    )
    out = {v.date() for v in lines.scalars().all() if v is not None}
    daily = await session.execute(
        select(PlatformDailyMetric.day)
        .where(
            PlatformDailyMetric.shop_id == shop_id,
            PlatformDailyMetric.platform == "shopee",
            PlatformDailyMetric.dataset.in_(DAILY_DATASETS),
            PlatformDailyMetric.day >= window.start,
            PlatformDailyMetric.day <= window.end,
        )
        .distinct()
    )
    out.update(daily.scalars().all())
    return frozenset(out)


async def last_complete_day(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    """The newest day whose shop row is complete (None when nothing is materialized)."""
    return await session.scalar(
        select(func.max(ShopeeShopMetricsDaily.day)).where(
            ShopeeShopMetricsDaily.shop_id == shop_id,
            ShopeeShopMetricsDaily.order_type == ORDER_TYPE,
            ShopeeShopMetricsDaily.complete.is_(True),
        )
    )
