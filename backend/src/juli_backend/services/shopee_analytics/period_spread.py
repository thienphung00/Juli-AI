"""P99: spread a Shopee period total over the days of its period, never stamp it on one day.

A one-day view of a day without order lines used to take Shopee's per-product PERIOD totals
(``product_period``: đơn, Doanh số) and the period traffic table (``item_by_source_period``:
lượt xem, lượt nhấp) unscaled onto that single day, so a 30-day total appeared on every day: a
product sold several times the shop's orders, its AOV fell to a fraction of its price, and the
period's views repeated daily. The owner chose to **spread** a period over its days by the shop's
daily shares (not to leave the days empty):

- **Đơn** of a product on day *d* = its period đơn x (shop đơn on *d* ÷ shop đơn over the
  period), whole đơn by largest remainder (:func:`metrics.allocate`), so the period's days add up
  to the period total exactly. A day never gets more đơn than the shop had that day: the excess
  is capped and re-distributed over the days with headroom (when the whole period has fewer shop
  đơn than the product total, the product gets the shop's đơn on every day and the rest is
  dropped: a product cannot out-sell its shop).
- **GMV** of a product on *d* = its period Doanh số spread like its đơn (so its AOV stays the
  period's AOV); the day's split (:func:`metrics._splits`) then fits these weights inside the
  shop's GMV of the day, never above it.
- **Lượt xem / lượt nhấp** = the period's, spread by the shop's daily lượt xem (lượt nhấp) when
  the traffic tables have them, else by the shop's đơn, else evenly.

The spread is computed over the whole period every time a day is rebuilt (deterministic), so
days rebuilt separately still add up. Days of the period that do have order lines keep them; the
spread only replaces the period stamp. ``rebuild_days`` loads the shop's daily series once per
period (:func:`load_shop_days`) and hands each day's spread to the pure ``day_rows``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import PlatformDailyMetricsRepo
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.metrics import allocate
from juli_backend.services.shopee_analytics.windows import PeriodChoice
from juli_backend.services.shopee_profit.money import ZERO

if TYPE_CHECKING:
    from juli_backend.services.shopee_analytics.compute import PeriodView

Period = tuple[date, date]
#: the product row ``source`` of a spread day (``shopee_product_metrics_daily.source`` is 16 chars)
ROW_SOURCE = "spread_period"


@dataclass(frozen=True)
class ShopDay:
    """The shop's own figures of one day (None = Shopee posted none that day)."""

    orders: int | None = None
    gmv: Decimal | None = None
    views: int | None = None
    clicks: int | None = None


@dataclass(frozen=True)
class SpreadDay:
    """One product's share of its Shopee period totals on one day."""

    #: None = the day keeps its own đơn / GMV (order lines, or no period total to spread)
    orders: int | None
    gmv: Decimal | None
    views: int | None
    clicks: int | None
    #: the period the đơn / GMV were spread from, and the traffic's
    totals_period: Period | None
    traffic_period: Period | None


def days_of(period: Period) -> list[date]:
    start, end = period
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def spread(
    total: Decimal,
    weights: Mapping[date, Decimal],
    caps: Mapping[date, Decimal] | None = None,
) -> dict[date, Decimal]:
    """Split ``total`` (whole units) over the days by ``weights``, largest remainder, with an
    optional per-day cap: a day over its cap keeps the cap and the excess goes to the days that
    still have room, until nothing is left or every day is full. Pure."""
    out = {d: ZERO for d in weights}
    left = total.quantize(Decimal(1))
    room = {d: w for d, w in weights.items() if w > 0 and (caps is None or caps.get(d, ZERO) > 0)}
    while left > 0 and room:
        part = allocate(left, {d.isoformat(): w for d, w in room.items()})
        left = ZERO
        for d in list(room):
            value = out[d] + part[d.isoformat()]
            cap = None if caps is None else caps.get(d, ZERO)
            if cap is not None and value >= cap:
                left += value - cap
                value = cap
                del room[d]
            out[d] = value
    return out


def _weights(days: list[date], series: Mapping[date, ShopDay], *attrs: str) -> dict[date, Decimal]:
    """The first of ``attrs`` the shop posted on some day of the period, else even weights."""
    for attr in attrs:
        values = {d: getattr(series.get(d, ShopDay()), attr) for d in days}
        if any(v for v in values.values()):
            return {d: Decimal(v or 0) for d, v in values.items()}
    return dict.fromkeys(days, Decimal(1))


def _order_caps(days: list[date], series: Mapping[date, ShopDay]) -> dict[date, Decimal] | None:
    if not any(series.get(d, ShopDay()).orders is not None for d in days):
        return None  # the shop posted no daily đơn: nothing to cap against
    return {d: Decimal(series.get(d, ShopDay()).orders or 0) for d in days}


def spread_totals(
    day: date,
    period: Period,
    gmv: Decimal,
    orders: int,
    series: Mapping[date, ShopDay],
) -> tuple[int, Decimal]:
    """A product's (đơn, GMV) on ``day`` from its period totals. Pure."""
    days = days_of(period)
    by_orders = spread(Decimal(orders), _weights(days, series, "orders"), _order_caps(days, series))
    if sum(by_orders.values(), ZERO) > 0:
        gmv_weights = by_orders
    else:
        gmv_weights = _weights(days, series, "gmv", "orders")
    by_gmv = allocate(gmv, {d.isoformat(): w for d, w in gmv_weights.items()})
    return int(by_orders.get(day, ZERO)), by_gmv.get(day.isoformat(), ZERO)


def spread_traffic(
    day: date,
    period: Period,
    views: int | None,
    clicks: int | None,
    series: Mapping[date, ShopDay],
) -> tuple[int | None, int | None]:
    """A product's (lượt xem, lượt nhấp) on ``day`` from its period traffic. Pure."""
    days = days_of(period)

    def one(total: int | None, attr: str) -> int | None:
        if total is None:
            return None
        got = spread(Decimal(total), _weights(days, series, attr, "orders"))
        return int(got.get(day, ZERO))

    return one(views, "views"), one(clicks, "clicks")


def _spread_period(choice: PeriodChoice | None, day: date) -> Period | None:
    """The one Shopee period a day's view stands on when it is longer than the day."""
    if choice is None or len(choice.periods) != 1:
        return None
    period = choice.periods[0]
    return None if period == (day, day) or not (period[0] <= day <= period[1]) else period


def periods_to_load(pf: loaders.ProductFlows, day: date) -> list[Period]:
    """The periods whose shop series a day's spread needs (totals and traffic)."""
    out = [_spread_period(pf.totals_basis, day)]
    if pf.source == "item_by_source_period":
        out.append(_spread_period(pf.flows_basis, day))
    return sorted({p for p in out if p is not None})


def day_spread(
    day: date,
    pf: loaders.ProductFlows,
    *,
    has_lines: bool,
    traffic: Mapping[str, tuple[int | None, int | None]],
    series: Mapping[date, ShopDay],
) -> dict[str, SpreadDay]:
    """Each product's spread on ``day`` (pure). ``traffic`` = the product's period views /
    clicks as the view summed them; ``series`` must cover the periods :func:`periods_to_load`
    names. Đơn / GMV are spread only on a day without order lines."""
    tp = None if has_lines else _spread_period(pf.totals_basis, day)
    fp = _spread_period(pf.flows_basis, day) if pf.source == "item_by_source_period" else None
    out: dict[str, SpreadDay] = {}
    for item in sorted(set(pf.totals if tp else ()) | set(traffic if fp else ())):
        orders: int | None = None
        gmv: Decimal | None = None
        if tp is not None and item in pf.totals:
            g, o = pf.totals[item]
            orders, gmv = spread_totals(day, tp, g, o, series)
        views, clicks = traffic.get(item, (None, None)) if fp else (None, None)
        if fp is not None:
            views, clicks = spread_traffic(day, fp, views, clicks, series)
        out[item] = SpreadDay(orders, gmv, views, clicks, tp, fp)
    return out


def for_view(view: PeriodView, day: date, series: Mapping[date, ShopDay]) -> dict[str, SpreadDay]:
    """:func:`day_spread` of a one-day view: its product period flows and order lines."""
    traffic: dict[str, tuple[int | None, int | None]] = {}
    for item, table in (view.flows.products if view.flows else {}).items():
        rows = [r for r in table.rows if not r.is_residual]
        v = [r.views for r in rows if r.views is not None]
        c = [r.clicks for r in rows if r.clicks is not None]
        traffic[item] = (sum(v) if v else None, sum(c) if c else None)
    return day_spread(
        day, view.data.product_flows, has_lines=bool(view.pairs), traffic=traffic, series=series
    )


async def load_shop_days(
    session: AsyncSession, shop_id: uuid.UUID, period: Period
) -> dict[date, ShopDay]:
    """The shop's daily đơn / GMV (``shop_overview``) and lượt xem / lượt nhấp (the traffic
    table's five flows) over a period: two reads."""
    repo = PlatformDailyMetricsRepo(session)
    start, end = period
    totals = await repo.window(
        shop_id,
        datasets=[loaders.SHOP_OVERVIEW_DAILY],
        start=start,
        end=end,
        streams=["total"],
        order_types=[loaders.CONFIRMED],
    )
    traffic = await repo.window(
        shop_id,
        datasets=[loaders.TRAFFIC_DAILY],
        start=start,
        end=end,
        streams=[*loaders.STREAM_TO_SOURCE],
        order_types=[loaders.CONFIRMED],
    )
    orders: dict[date, tuple[int, Decimal]] = {}
    for r in totals:
        if r.segment == "all":
            orders[r.day] = (int(r.orders or 0), Decimal(str(r.gmv or 0)))
    views: dict[date, list[int]] = {}
    for r in traffic:
        # Thẻ sản phẩm's total already includes Trang shop: the four streams' "all" rows
        if r.item_id not in ("", None) or r.segment != "all":
            continue
        cell = views.setdefault(r.day, [0, 0])
        cell[0] += int(r.impressions or 0)
        cell[1] += int(r.clicks or 0)
    out: dict[date, ShopDay] = {}
    for d in set(orders) | set(views):
        o = orders.get(d)
        v = views.get(d)
        out[d] = ShopDay(
            o[0] if o else None,
            o[1] if o else None,
            v[0] if v else None,
            v[1] if v else None,
        )
    return out


__all__ = [
    "ROW_SOURCE",
    "ShopDay",
    "SpreadDay",
    "day_spread",
    "for_view",
    "load_shop_days",
    "periods_to_load",
    "spread",
    "spread_totals",
    "spread_traffic",
]
