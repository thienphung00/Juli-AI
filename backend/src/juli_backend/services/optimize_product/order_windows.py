"""Order windows by creation time (ADR-106 amendment 5).

Every order-derived figure of the report names a window and reads only the
orders whose ``create_time`` falls in it, in the shop's timezone (UTC+7 for
Vietnam). The earlier evidence pull filtered the order search by ``update_time``,
so its "recent" sample was in fact orders created over a much longer span; a
caller that hands in such a file must never have its out-of-window orders
counted silently. Pure: callers hand the orders in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

CANCELLED = "CANCELLED"
SHOP_UTC_OFFSET_HOURS = 7


def create_day(order: dict) -> date | None:
    """The order's creation date in the shop's timezone; ``None`` when unreadable."""
    try:
        seconds = int(str(order.get("create_time")))
    except (ValueError, AttributeError):
        return None
    zone = timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))
    return datetime.fromtimestamp(seconds, tz=zone).date()


def orders_between(orders: list[dict] | None, first: date, last: date) -> list[dict]:
    """Orders created on ``first..last`` inclusive (local dates), cancelled ones included."""
    out: list[dict] = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        day = create_day(order)
        if day is not None and first <= day <= last:
            out.append(order)
    return out


def create_range(orders: list[dict]) -> tuple[date, date] | None:
    """Earliest and latest creation date among ``orders``."""
    days = [d for d in (create_day(o) for o in orders if isinstance(o, dict)) if d is not None]
    return (min(days), max(days)) if days else None


def live_lines(order: dict) -> list[dict]:
    """The order's non-gift line items that name a product."""
    return [
        line
        for line in order.get("line_items") or []
        if isinstance(line, dict) and not line.get("is_gift") and line.get("product_id")
    ]


def kept(orders: list[dict]) -> list[dict]:
    """Orders that were not cancelled."""
    return [o for o in orders if str(o.get("status") or "") != CANCELLED]


def orders_by_product(orders: list[dict]) -> dict[str, list[dict]]:
    """Per product, each non-cancelled order that contains it (once per order)."""
    out: dict[str, list[dict]] = defaultdict(list)
    for order in kept(orders):
        for product_id in dict.fromkeys(str(line["product_id"]) for line in live_lines(order)):
            out[product_id].append(order)
    return dict(out)


@dataclass(frozen=True)
class OrderWindowSummary:
    """What the report says about the orders it used and the ones it left out."""

    present: bool
    total: int
    used: int
    excluded: int
    used_first: date | None
    used_last: date | None
    excluded_first: date | None
    excluded_last: date | None


def summarize(orders: list[dict] | None, first: date, last: date) -> OrderWindowSummary:
    if orders is None:
        return OrderWindowSummary(False, 0, 0, 0, None, None, None, None)
    inside = orders_between(orders, first, last)
    inside_ids = {id(o) for o in inside}
    outside = [o for o in orders if isinstance(o, dict) and id(o) not in inside_ids]
    used_range = create_range(inside)
    out_range = create_range(outside)
    return OrderWindowSummary(
        True,
        len(orders),
        len(inside),
        len(outside),
        used_range[0] if used_range else None,
        used_range[1] if used_range else None,
        out_range[0] if out_range else None,
        out_range[1] if out_range else None,
    )
