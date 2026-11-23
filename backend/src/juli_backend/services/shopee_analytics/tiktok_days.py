"""TikTok's day in layer 4 (P101 W3 t1): the day's analytics over its order-line rows.

:func:`materialize.rebuild_days` builds every day the same way for both platforms: the one-day
view of the canonical order lines and settlements gives the profit components (delivered-only,
the refund cost rule, no tax). For a shop whose daily analytics rows
(``analytics_performance_intervals``) cover the day, :func:`overlay` then writes TikTok's own
numbers on those rows:

- headline GMV / đơn / units = the day's shop-grain analytics row (an order with two products is
  one đơn); views / clicks = the products' A-34 totals; ``complete`` True, sources ``analytics``;
- product rows = each product's A-34 total, with the order lines' line figures; the residual row
  holds the gap to the shop total;
- source rows (decision #7) from the A-34 channel blocks the poll keeps (``A34_BLOCKS``), read
  through ``shop_diagnosis.channels``: Thẻ sản phẩm, Video, LIVE and Tiếp thị liên kết are split
  over the shop / product total with :func:`materialize.split_sources`, the gap in
  ``chenh_lech_nguon``; Tab cửa hàng (``trang_shop``) is stored beside them with its own views /
  clicks / GMV and is in no sum. Its orders column holds 0 only because the column is NOT NULL;
  the shop row records ``detail.trang_shop_orders_known`` False and :mod:`funnel_check` leaves the
  row out of its sum check. Ads columns stay NULL.

Profit (:func:`settled_profit_only`, :func:`without_ads_profit`): a delivered order without a
settlement leaves the day's profit NULL; with no ads spend source the stored profit / margin are
NULL with ``detail.profit_reason`` and the before-ads figures in ``detail``.

A day without a shop-grain row, or whose analytics are all zero beside order lines, keeps the
order-line rows and records the newest covered day in ``detail.analytics_through``. A shop
without analytics rows (every Shopee shop) is never touched: :func:`load_days` returns nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.models.shopee_metrics import RESIDUAL_ITEM
from juli_backend.services.shop_diagnosis.channels import Channel, Counts, read_counts
from juli_backend.services.shopee_profit.flows import FLOW_LABELS, FlowMetrics, FlowTable

#: = ``integrations.tiktok.mapping.A34_BLOCKS_KEY`` (restated, as ``optimize_product_cards``
#: restates ``A34_TOTAL``; a test pins the two together).
A34_BLOCKS_KEY = "A34_BLOCKS"
#: = ``integrations.tiktok.mapping._A34_TOTAL_KEY``: the list row's own funnel totals.
A34_TOTAL_KEY = "A34_TOTAL"
PRODUCT_GRAIN = "product"
SHOP_GRAIN = "shop"
#: shop ``detail`` key: the ``trang_shop`` source rows' 0 orders are not a count (decision #7)
SHOP_TAB_ORDERS_KNOWN_KEY = "trang_shop_orders_known"
#: the column tag of a figure that came from TikTok's analytics
ROW_SOURCE = "analytics"
#: ``detail`` key of a day the analytics do not cover yet: the newest day they do
THROUGH_KEY = "analytics_through"
#: decision #7: the sources that partition the total, by source key
SUM_SOURCES: Mapping[str, Channel] = {
    "the_san_pham_khac": Channel.PRODUCT_CARD,
    "video": Channel.SELLER_VIDEO,
    "live": Channel.SELLER_LIVE,
    "lien_ket": Channel.AFFILIATE,
}
#: decision #7: shown beside the others, in no sum
SHOP_TAB_SOURCE = "trang_shop"
ZERO = Decimal(0)


def _money(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def _whole(value: float) -> int:
    return int(round(value))


@dataclass(frozen=True)
class ProductDay:
    """One product's analytics on one day."""

    product_id: str
    gmv: Decimal
    orders: int
    units: int
    views: int | None
    clicks: int | None
    #: source key -> counts (the four summed sources and ``trang_shop``); None = no blocks
    channels: dict[str, Counts] | None = None

    @property
    def active(self) -> bool:
        return bool(self.gmv or self.orders or self.views or self.clicks)


@dataclass(frozen=True)
class ShopTotal:
    """The day's shop-grain analytics row: the headline (one đơn per order)."""

    gmv: Decimal
    orders: int
    units: int | None


@dataclass
class AnalyticsDay:
    day: date
    products: dict[str, ProductDay] = field(default_factory=dict)
    shop: ShopTotal | None = None

    @property
    def gmv(self) -> Decimal:
        return self.shop.gmv if self.shop else ZERO

    @property
    def orders(self) -> int:
        return self.shop.orders if self.shop else 0

    @property
    def units(self) -> int | None:
        return self.shop.units if self.shop else None

    @property
    def views(self) -> int | None:
        known = [p.views for p in self.products.values() if p.views is not None]
        return sum(known) if known else None

    @property
    def clicks(self) -> int | None:
        known = [p.clicks for p in self.products.values() if p.clicks is not None]
        return sum(known) if known else None

    @property
    def active(self) -> bool:
        if self.shop is not None and (self.shop.gmv or self.shop.orders):
            return True
        return any(p.active for p in self.products.values())

    def channel_sum(self, source: str) -> Counts | None:
        rows = [p.channels[source] for p in self.products.values() if p.channels]
        if not rows:
            return None
        total = rows[0]
        for c in rows[1:]:
            total = total + c
        return total


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


def product_day(row: Any) -> ProductDay | None:
    """One stored product-day row -> its analytics (pure). The channel blocks when the poll kept
    them, else the row's own totals (the A-34 list row's, or A-33's for days stored before)."""
    product_id = row.tiktok_product_id
    if not product_id:
        return None
    breakdown = row.traffic_breakdown if isinstance(row.traffic_breakdown, dict) else {}
    blocks = breakdown.get(A34_BLOCKS_KEY)
    if isinstance(blocks, dict) and isinstance(blocks.get("total_performance"), dict):
        total = read_counts(blocks, Channel.TOTAL)
        channels = {key: read_counts(blocks, ch) for key, ch in SUM_SOURCES.items()}
        channels[SHOP_TAB_SOURCE] = read_counts(blocks, Channel.SHOP_TAB)
        return ProductDay(
            str(product_id),
            _money(total.gmv),
            _whole(total.orders),
            _whole(total.items_sold),
            _whole(total.impressions),
            _whole(total.clicks),
            channels,
        )
    funnel = breakdown.get(A34_TOTAL_KEY) if isinstance(breakdown.get(A34_TOTAL_KEY), dict) else {}
    orders = row.orders_count if row.orders_count is not None else row.sku_orders
    return ProductDay(
        str(product_id),
        Decimal(row.gmv) if row.gmv is not None else ZERO,
        int(orders or 0),
        int(row.items_sold or 0),
        _int(funnel.get("impressions")) if funnel else row.impressions,
        _int(funnel.get("clicks")) if funnel else row.clicks,
    )


def _is_daily(row: Any) -> bool:
    return row.end_date is None or row.end_date == row.start_date + timedelta(days=1)


async def load_days(
    session: AsyncSession, shop_id: uuid.UUID, days: Iterable[date]
) -> dict[date, AnalyticsDay]:
    """The days of ``days`` the shop's daily product analytics cover (one read)."""
    wanted = sorted(set(days))
    if not wanted:
        return {}
    t = AnalyticsPerformanceInterval
    rows = (
        await session.execute(
            select(t).where(
                t.shop_id == shop_id,
                t.grain.in_((PRODUCT_GRAIN, SHOP_GRAIN)),
                t.hour_index.is_(None),
                t.start_date >= wanted[0],
                t.start_date <= wanted[-1],
            )
        )
    ).scalars()
    keep = set(wanted)
    out: dict[date, AnalyticsDay] = {}
    for row in rows:
        if row.start_date not in keep or not _is_daily(row):
            continue
        if row.grain == SHOP_GRAIN:
            day = out.setdefault(row.start_date, AnalyticsDay(row.start_date))
            orders = row.orders_count if row.orders_count is not None else row.sku_orders
            day.shop = ShopTotal(
                Decimal(row.gmv) if row.gmv is not None else ZERO,
                int(orders or 0),
                _int(row.items_sold),
            )
            continue
        pd = product_day(row)
        if pd is None:
            continue
        out.setdefault(row.start_date, AnalyticsDay(row.start_date)).products[pd.product_id] = pd
    return out


async def analytics_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    grains: tuple[str, ...] = (PRODUCT_GRAIN, SHOP_GRAIN),
) -> list[date]:
    """Every day the shop has daily shop / product analytics for (none for a Shopee shop)."""
    t = AnalyticsPerformanceInterval
    found = await session.execute(
        select(t.start_date)
        .where(t.shop_id == shop_id, t.grain.in_(grains), t.hour_index.is_(None))
        .distinct()
    )
    return sorted(found.scalars().all())


async def headline_days(session: AsyncSession, shop_id: uuid.UUID) -> list[date]:
    """The days with a shop-grain analytics row: the days a headline exists for."""
    return await analytics_days(session, shop_id, (SHOP_GRAIN,))


async def newest_day(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    t = AnalyticsPerformanceInterval
    return await session.scalar(
        select(func.max(t.start_date)).where(
            t.shop_id == shop_id, t.grain == PRODUCT_GRAIN, t.hour_index.is_(None)
        )
    )


def covers(day: AnalyticsDay | None, line_orders: int | None) -> bool:
    """The analytics stand for the day: a shop-grain row with any count at all, or a day with no
    order line either (a real zero day). All zeros beside order lines is a day TikTok has not
    counted (sandbox); no shop-grain row is a day TikTok has not published."""
    if day is None or day.shop is None:
        return False
    return day.active or not line_orders


def flow_table(channels: Mapping[str, Counts | None], gmv: Decimal, orders: int) -> FlowTable:
    """The four summed sources as a flow table (weights for ``split_sources``); Tab cửa hàng is
    left out so it takes no share of the totals."""
    rows = []
    for key in SUM_SOURCES:
        c = channels.get(key)
        if c is None:
            continue
        rows.append(
            FlowMetrics(
                key,
                FLOW_LABELS.get(key, key),
                _whole(c.impressions),
                _whole(c.clicks),
                _whole(c.sku_orders or 0),
                _money(c.gmv),
            )
        )
    return FlowTable(tuple(rows), gmv, orders)


def _shop_tab(row: dict[str, Any], tab: Counts | None) -> dict[str, Any]:
    return {
        **row,
        "views": _whole(tab.impressions) if tab else None,
        "clicks": _whole(tab.clicks) if tab else None,
        "orders": 0,
        "gmv": _money(tab.gmv) if tab else ZERO,
        "profit": None,
        "scaled_to_totals": False,
    }


def _scope_sources(
    channels: Mapping[str, Counts | None] | None,
    *,
    gmv: Decimal,
    orders: int,
    profit: Decimal | None,
    shop_id: uuid.UUID,
    day: date,
    item_id: str | None,
) -> list[dict[str, Any]]:
    from juli_backend.services.shopee_analytics import materialize  # the one split rule

    table = flow_table(channels, gmv, orders) if channels else None
    rows = materialize.source_rows(
        materialize.split_sources(table, orders, gmv, profit),
        shop_id=shop_id,
        day=day,
        item_id=item_id,
        ads=None,
    )
    tab = channels.get(SHOP_TAB_SOURCE) if channels else None
    return [_shop_tab(r, tab) if r["source"] == SHOP_TAB_SOURCE else r for r in rows]


def overlay(rows: Any, analytics: AnalyticsDay, *, shop_id: uuid.UUID, day: date) -> Any:
    """Put the day's analytics on its order-line ``DayRows`` (pure; see the module docstring)."""
    from juli_backend.services.shopee_analytics.materialize import DayRows

    gmv, orders = analytics.gmv, analytics.orders
    shop = dict(rows.shop)
    shop.update(
        gmv=gmv,
        orders=orders,
        aov=(gmv / orders).quantize(Decimal("0.01")) if orders else None,
        units=analytics.units,
        views=analytics.views,
        product_clicks=analytics.clicks,
        complete=True,
    )
    shop["detail"] = {**shop["detail"], SHOP_TAB_ORDERS_KNOWN_KEY: False}
    shop["sources"] = {
        **shop["sources"],
        "gmv": ROW_SOURCE,
        "orders": ROW_SOURCE,
        "views": ROW_SOURCE,
        "product_clicks": ROW_SOURCE,
    }
    by_item = {p["item_id"]: p for p in rows.products if p["item_id"] != RESIDUAL_ITEM}
    products: list[dict[str, Any]] = []
    for item_id in sorted(set(by_item) | {k for k, p in analytics.products.items() if p.active}):
        base = by_item.get(item_id) or {
            "shop_id": shop_id,
            "day": day,
            "order_type": shop["order_type"],
            "item_id": item_id,
            "variation_id": None,
            "ads_spend": None,
            "profit": None,
            "line_gmv": ZERO,
            "line_orders": 0,
        }
        pd = analytics.products.get(item_id)
        products.append(
            {
                **base,
                "gmv": pd.gmv if pd else ZERO,
                "orders": pd.orders if pd else 0,
                "units": pd.units if pd else 0,
                "views": pd.views if pd else None,
                "clicks": pd.clicks if pd else None,
                "source": ROW_SOURCE,
                "scaled_to_totals": False,
            }
        )
    residual = next(p for p in rows.products if p["item_id"] == RESIDUAL_ITEM)
    products.append(
        {**residual, "gmv": gmv - sum((p["gmv"] for p in products), ZERO), "source": ROW_SOURCE}
    )
    shop_profit = None if shop["detail"].get("profit_partial") else shop["profit"]
    channels = {key: analytics.channel_sum(key) for key in (*SUM_SOURCES, SHOP_TAB_SOURCE)}
    has_blocks = any(v is not None for v in channels.values())
    sources = _scope_sources(
        channels if has_blocks else None,
        gmv=gmv,
        orders=orders,
        profit=shop_profit,
        shop_id=shop_id,
        day=day,
        item_id=None,
    )
    for p in products:
        pd = analytics.products.get(p["item_id"])
        if pd is None or not pd.channels:
            continue
        sources += _scope_sources(
            pd.channels,
            gmv=p["gmv"],
            orders=p["orders"],
            profit=p["profit"],
            shop_id=shop_id,
            day=day,
            item_id=p["item_id"],
        )
    return DayRows(shop, products, sources)


#: Platforms whose profit stands on the order's settlement alone (coordinator, M-5): their
#: shops never read the Shopee fee formula table, and a delivered order with no settlement row
#: has no profit yet (None), never a formula estimate. Data, not a platform check.
SETTLEMENT_ONLY_PLATFORMS = frozenset({"tiktok"})


def unsettled_items(view: Any) -> set[str]:
    """The products of the view's delivered lines that have no settlement (income) share."""
    return {ln.product_id for ln, _ in view.pairs if ln.status.carries_profit and ln.income is None}


def settled_profit_only(rows: Any, unsettled: set[str]) -> Any:
    """Clear every profit an unsettled delivered order would have needed a fee estimate for:
    the day (shop row, its margin terms and its source rows) and the unsettled products."""
    if not unsettled:
        return rows
    rows.shop.update(profit=None, margin_profit=None, buyer_paid_known=None)
    for p in rows.products:
        if p["item_id"] in unsettled:
            p["profit"] = None
    for s in rows.sources:
        if s["item_id"] is None or s["item_id"] in unsettled:
            s["profit"] = None
    return rows


#: owner W3-Q5 = a: why a settlement-only shop's profit is None while it has no ads spend source
ADS_SCOPE_MISSING = "ads_scope_missing"
PROFIT_REASON_KEY = "profit_reason"
#: ``detail`` keys keeping the before-ads figures, so profit completes once ads spend exists
BEFORE_ADS_KEYS = {"profit": "profit_before_ads", "margin_profit": "margin_profit_before_ads"}


def without_ads_profit(rows: Any) -> Any:
    """Owner W3-Q5 = a: a shop with no ads spend source (TikTok until the Business API scope)
    stores no profit and no margin numerator -- never a before-ads number as profit. The
    settlement-based components stay (``buyer_paid_known``, ``cogs_coverage``, ``line_gmv``)
    and the before-ads figures go to ``detail`` beside the reason code."""
    if rows.shop.get("ads_spend") is not None:
        return rows
    detail = dict(rows.shop["detail"])
    for column, key in BEFORE_ADS_KEYS.items():
        value = rows.shop.get(column)
        detail[key] = None if value is None else str(value)
        rows.shop[column] = None
    detail[PROFIT_REASON_KEY] = ADS_SCOPE_MISSING
    rows.shop["detail"] = detail
    for p in rows.products:
        p["profit"] = None
    for src in rows.sources:
        src["profit"] = None
    return rows


def mark_through(rows: Any, through: date | None) -> Any:
    """A day the analytics do not cover: say up to which day they do."""
    if through is not None:
        rows.shop["detail"] = {**rows.shop["detail"], THROUGH_KEY: through.isoformat()}
    return rows


__all__ = [
    "A34_BLOCKS_KEY",
    "ADS_SCOPE_MISSING",
    "BEFORE_ADS_KEYS",
    "PROFIT_REASON_KEY",
    "ROW_SOURCE",
    "SETTLEMENT_ONLY_PLATFORMS",
    "SHOP_TAB_SOURCE",
    "SUM_SOURCES",
    "THROUGH_KEY",
    "AnalyticsDay",
    "ProductDay",
    "analytics_days",
    "covers",
    "flow_table",
    "headline_days",
    "load_days",
    "mark_through",
    "newest_day",
    "overlay",
    "product_day",
    "settled_profit_only",
    "unsettled_items",
    "without_ads_profit",
]
