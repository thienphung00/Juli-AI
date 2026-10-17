"""Group-verdict money metrics net of cancelled / refunded orders (D55.1, P46, Ops only).

TikTok's GMV -- the ``gmv`` / ``sku_orders`` / ``items_sold`` of the daily product
analytics rows every group verdict reads -- **includes orders that are later cancelled
or refunded** (Seller University definition; ``~/juli-sim-pilot/research/
metric_definitions.md``). The analytics rows carry no cancel / refund amount (the
mapper keeps neither A-34 ``total_performance.refunds`` nor A-33
``cancel_and_refunds``), but the shop's own orders do: ``silver.orders`` (``status``,
``tiktok_created_at``), ``order_items`` (product, quantity, ``line_total``) and
``silver.returns`` (refunds and cancellations, ``refund_amount``, ``status``) are polled
every cycle.

So the net value of one product-day is the analytics value scaled by that day's share
of the product's orders that were cancelled or refunded (order day = the order's
``tiktok_created_at`` in shop time, UTC+7; a refund counts against the day its order
was placed):

- ``sku_orders`` × (1 − removed orders ÷ orders), an order removed when it is
  cancelled or its product lines are refunded in full;
- ``items_sold`` × (1 − removed units ÷ units);
- ``gmv`` × (1 − removed value ÷ value), the removed value of a partial refund being
  the refund amount (capped at the lines' value).

Scaling (rather than summing the order lines) keeps TikTok's attribution and units and
sidesteps the order-line store's one row per (order, SKU) -- which collapses repeated
per-unit lines of one SKU, so order-line sums under-count multi-unit orders. A day with
no order lines for the product keeps its analytics values (share 0).

**Coverage.** A group is read on net values only when the shop's orders span every day
the verdict reads (the earliest order day ≤ the first pre-period day and the latest ≥
the last after-window day); otherwise the verdict stays on TikTok's GMV and Ops says so
("gồm đơn huỷ/hoàn, theo TikTok"). The seller-facing sentence never reads net values.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Order, OrderItem, Return

#: Money / order metrics TikTok's GMV inflates with cancelled and refunded orders.
NET_METRICS: frozenset[str] = frozenset({"aov", "items_per_order"})
#: Net values are derived for all-channel reads only (orders carry no channel).
NET_CHANNEL = "total"

BASIS_NET = "net"
BASIS_GROSS = "gross"
#: Ops labels (Vietnamese, D55.1). Seller copy never uses them.
BASIS_LABELS_VI: Mapping[str, str] = {
    BASIS_NET: "đã trừ huỷ/hoàn",
    BASIS_GROSS: "gồm đơn huỷ/hoàn, theo TikTok",
}
REVENUE_NET_LABEL = "Doanh thu (đã trừ huỷ/hoàn)"
GMV_GROSS_LABEL = "GMV TikTok (gồm huỷ/hoàn)"
GMV_GROSS_ONLY_LABEL = "GMV (gồm đơn huỷ/hoàn, theo TikTok)"
BASIS_TEXT_VI: Mapping[str, str] = {
    BASIS_NET: (
        "AOV và số món mỗi đơn tính trên doanh thu đã trừ đơn huỷ/hoàn (theo đơn hàng của "
        "shop); số theo GMV TikTok (gồm huỷ/hoàn) ghi bên cạnh"
    ),
    BASIS_GROSS: (
        "AOV và số món mỗi đơn theo GMV TikTok, gồm đơn huỷ/hoàn: chưa đủ dữ liệu đơn hàng để trừ"
    ),
}

_CANCELLED = frozenset({"CANCELLED", "CANCELED"})
#: ``silver.returns.status`` (TikTok return / cancellation status, as stored) of a
#: refund or cancellation that went through.
_DONE_MARKERS = ("COMPLETE", "SUCCESS")
#: ``return_type`` values that move no money back (an exchange).
_NO_REFUND_TYPES = frozenset({"item_swap"})
_CANCELLATION_TYPE = "cancellation"
_SHOP_UTC_OFFSET = timedelta(hours=7)
ZERO = Decimal(0)


def needs_net(metric: str, channel: str) -> bool:
    return metric in NET_METRICS and channel == NET_CHANNEL


def basis_label(metric_label: str, basis: str) -> str:
    """``AOV`` -> ``AOV (đã trừ huỷ/hoàn)`` / ``AOV (gồm đơn huỷ/hoàn, theo TikTok)``."""
    return f"{metric_label} ({BASIS_LABELS_VI[basis]})"


def shop_day(moment: datetime) -> date:
    """A naive-UTC (or aware) timestamp's day in shop time (UTC+7)."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return (moment + _SHOP_UTC_OFFSET).date()


# ------------------------------------------------------------------------------- pure


@dataclass(frozen=True)
class OrderLine:
    """One product's lines on one order (the order-line store's rows summed)."""

    order_id: str
    product_id: str
    day: date
    cancelled: bool
    units: int
    value: Decimal


@dataclass(frozen=True)
class Refund:
    """One refund / cancellation that went through, on an order (and product, if known)."""

    order_id: str
    product_id: str | None
    amount: Decimal
    cancellation: bool = False


def refund_counts(return_type: str | None, status: str | None, amount: Any) -> bool:
    """Whether a ``silver.returns`` row removes money: done, not an exchange, amount > 0
    (a cancellation counts whatever its amount)."""
    kind = (return_type or "").lower()
    if kind in _NO_REFUND_TYPES:
        return False
    done = any(marker in (status or "").upper() for marker in _DONE_MARKERS)
    if not done:
        return False
    if kind == _CANCELLATION_TYPE:
        return True
    try:
        return Decimal(str(amount)) > 0
    except (ArithmeticError, ValueError):
        return False


@dataclass(frozen=True)
class OrderDay:
    """One product-day of the shop's own orders: what was placed and what was removed."""

    orders: int = 0
    removed_orders: int = 0
    units: int = 0
    removed_units: int = 0
    value: Decimal = ZERO
    removed_value: Decimal = ZERO

    def _share(self, removed: float, total: float) -> Decimal:
        if total <= 0:
            return ZERO
        return Decimal(str(min(max(removed / total, 0.0), 1.0)))

    @property
    def order_share(self) -> Decimal:
        return self._share(self.removed_orders, self.orders)

    @property
    def unit_share(self) -> Decimal:
        return self._share(self.removed_units, self.units)

    @property
    def value_share(self) -> Decimal:
        return self._share(float(self.removed_value), float(self.value))


def order_days(
    lines: Iterable[OrderLine], refunds: Iterable[Refund]
) -> dict[str, dict[date, OrderDay]]:
    """Per product, per order day: placed vs removed orders / units / value (pure).

    An order-product is removed in full when the order is cancelled, a cancellation went
    through on it, or its refunds reach its value; a smaller refund removes only that
    value. A refund without a product spreads over the order's products by value.
    """
    by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for line in lines:
        by_order[line.order_id].append(line)
    refunded: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    cancelled: set[tuple[str, str]] = set()
    for refund in refunds:
        order_lines = by_order.get(refund.order_id) or []
        targets = (
            [line for line in order_lines if line.product_id == refund.product_id]
            if refund.product_id
            else order_lines
        )
        if not targets:
            continue
        if refund.cancellation:
            cancelled.update((refund.order_id, t.product_id) for t in targets)
            continue
        total = sum((t.value for t in targets), ZERO)
        for t in targets:
            part = refund.amount * (t.value / total) if total > 0 else ZERO
            refunded[(refund.order_id, t.product_id)] += part
    out: dict[str, dict[date, OrderDay]] = defaultdict(dict)
    for order_lines in by_order.values():
        for line in order_lines:
            key = (line.order_id, line.product_id)
            removed_value = min(refunded.get(key, ZERO), line.value)
            full = (
                line.cancelled
                or key in cancelled
                or (line.value > 0 and removed_value >= line.value)
            )
            day = out[line.product_id].get(line.day, OrderDay())
            out[line.product_id][line.day] = OrderDay(
                orders=day.orders + 1,
                removed_orders=day.removed_orders + (1 if full else 0),
                units=day.units + line.units,
                removed_units=day.removed_units + (line.units if full else 0),
                value=day.value + line.value,
                removed_value=day.removed_value + (line.value if full else removed_value),
            )
    return {product: dict(days) for product, days in out.items()}


def net_rows(rows: Sequence[Any], days: Mapping[date, OrderDay] | None) -> list[Any]:
    """The product's daily analytics rows with orders / items / GMV net of the day's
    cancel / refund shares (traffic unchanged). ``ChannelRow`` duck-types for
    ``window_totals``. Pure."""
    from juli_backend.services.lever_flows.measurement import ChannelRow

    days = days or {}
    out: list[Any] = []
    for row in rows:
        day = days.get(row.start_date)

        def scaled(value: Any, share: Decimal) -> Decimal | None:
            if value is None:
                return None
            return Decimal(str(value)) * (1 - share)

        out.append(
            ChannelRow(
                row.start_date,
                Decimal(str(row.impressions or 0)),
                Decimal(str(row.clicks or 0)),
                sku_orders=scaled(row.sku_orders, day.order_share if day else ZERO),
                items_sold=scaled(row.items_sold, day.unit_share if day else ZERO),
                gmv=scaled(row.gmv, day.value_share if day else ZERO),
                ctr=row.ctr,
                conversion_rate=row.conversion_rate,
                click_to_order_rate=row.click_to_order_rate,
            )
        )
    return out


# ------------------------------------------------------------------------------ storage


def _naive_bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """Shop-time days [first, last] as naive-UTC timestamps [start, end)."""
    start = datetime.combine(first, datetime.min.time()) - _SHOP_UTC_OFFSET
    end = datetime.combine(last + timedelta(days=1), datetime.min.time()) - _SHOP_UTC_OFFSET
    return start, end


async def order_coverage(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> bool:
    """Whether the shop's orders span shop days ``first`` .. ``last`` (one query)."""
    low, high = (
        await session.execute(
            select(func.min(Order.tiktok_created_at), func.max(Order.tiktok_created_at)).where(
                Order.shop_id == shop_id
            )
        )
    ).one()
    if low is None or high is None:
        return False
    return shop_day(low) <= first and shop_day(high) >= last


async def load_order_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_ids: Iterable[str],
    first: date,
    last: date,
) -> dict[str, dict[date, OrderDay]]:
    """The products' :func:`order_days` for orders placed on shop days ``first`` .. ``last``."""
    products = sorted(set(product_ids))
    if not products:
        return {}
    start, end = _naive_bounds(first, last)
    rows = (
        await session.execute(
            select(
                OrderItem.tiktok_order_id,
                OrderItem.tiktok_product_id,
                OrderItem.quantity,
                OrderItem.line_total,
                Order.status,
                Order.tiktok_created_at,
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.shop_id == shop_id,
                Order.shop_id == shop_id,
                OrderItem.tiktok_product_id.in_(products),
                Order.tiktok_created_at >= start,
                Order.tiktok_created_at < end,
            )
        )
    ).all()
    summed: dict[tuple[str, str], list[Any]] = {}
    for order_id, product, quantity, line_total, status, created in rows:
        if not product or created is None:
            continue
        key = (str(order_id), str(product))
        entry = summed.setdefault(
            key, [shop_day(created), (status or "").upper() in _CANCELLED, 0, ZERO]
        )
        entry[2] += int(quantity or 0)
        entry[3] += Decimal(str(line_total or 0))
    lines = [
        OrderLine(order, product, day, cancelled, units, value)
        for (order, product), (day, cancelled, units, value) in summed.items()
    ]
    order_ids = sorted({line.order_id for line in lines})
    refunds: list[Refund] = []
    if order_ids:
        for order_id, product, return_type, status, amount in (
            await session.execute(
                select(
                    Return.tiktok_order_id,
                    Return.tiktok_product_id,
                    Return.return_type,
                    Return.status,
                    Return.refund_amount,
                ).where(Return.shop_id == shop_id, Return.tiktok_order_id.in_(order_ids))
            )
        ).all():
            if not refund_counts(return_type, status, amount):
                continue
            refunds.append(
                Refund(
                    str(order_id),
                    str(product) if product else None,
                    Decimal(str(amount or 0)),
                    cancellation=(return_type or "").lower() == _CANCELLATION_TYPE,
                )
            )
    return order_days(lines, refunds)
