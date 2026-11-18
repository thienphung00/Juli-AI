"""Which stock figure a variation has at send time (Part S). Pure, no DB.

Basis of one read: ``total_available_stock`` (Seller Centre's "Kho hàng"), else ``sellable_stock``.
``sellable_stock`` is Shopee's ``advanced_stock`` figure (the "Gói Sẵn Giao Nhanh" prepared stock):
0 for a shop that does not use it, so preferring it read ORY's whole catalogue as sold out
(Chrome check 2026-11-15).

At send time (``now``, 07:00 GMT+7):

- a read today after 06:00 GMT+7 -> that read, as it is;
- else a read less than 48 h old -> that read minus the units ordered since it (order lines placed
  after ``read_at``), never below 0, remembering "đã trừ n đơn";
- else no usable read: the shop gets the "chưa đọc được tồn kho" e-mail.

Times are naive UTC (as the stock-alert tables store them); the local day is GMT+7. The canonical
tables (``stock_history.read_at``, ``order_lines.ordered_at``, migration 134) are ``timestamptz``
and come back aware: :func:`naive_utc` turns them into naive UTC where they enter this package, so
an aware and a naive time never meet here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

LOCAL_OFFSET = timedelta(hours=7)
FRESH_AFTER = time(6, 0)
MAX_AGE = timedelta(hours=48)


def naive_utc(at: datetime) -> datetime:
    """The stock alert's time form: an aware time as naive UTC; a naive one is already UTC."""
    return at.astimezone(UTC).replace(tzinfo=None) if at.tzinfo is not None else at


def local(at: datetime) -> datetime:
    """Naive UTC (or aware) -> naive GMT+7."""
    return naive_utc(at) + LOCAL_OFFSET


def local_day(at: datetime) -> date:
    return local(at).date()


def basis(sellable: int | None, available: int | None) -> int | None:
    return available if available is not None else sellable


@dataclass(frozen=True)
class Read:
    read_at: datetime
    stock: int | None


@dataclass(frozen=True)
class StockNow:
    stock: int
    read_at: datetime
    #: units subtracted for orders placed since the read (0 for a fresh read)
    deducted_units: int
    #: orders subtracted ("đã trừ n đơn"); 0 for a fresh read
    deducted_orders: int

    @property
    def fresh(self) -> bool:
        return self.deducted_orders == 0 and self.deducted_units == 0


def is_fresh_read(read_at: datetime, now: datetime) -> bool:
    lr, ln = local(read_at), local(now)
    return lr.date() == ln.date() and lr.time() >= FRESH_AFTER and read_at <= now


def usable(read_at: datetime, now: datetime) -> bool:
    return is_fresh_read(read_at, now) or timedelta(0) <= now - read_at < MAX_AGE


def stock_now(
    last: Read | None, now: datetime, *, units_since: int = 0, orders_since: int = 0
) -> StockNow | None:
    """The stock to forecast from, or None when there is no usable read (see the docstring)."""
    if last is None or last.stock is None:
        return None
    if is_fresh_read(last.read_at, now):
        return StockNow(last.stock, last.read_at, 0, 0)
    if not usable(last.read_at, now):
        return None
    return StockNow(max(0, last.stock - units_since), last.read_at, units_since, orders_since)


def zero_days(reads: Sequence[Read], start: date, end: date) -> set[date]:
    """Local days in ``start``..``end`` on which the variation had 0 stock: a read that day at 0,
    or no read that day while the last earlier read was 0."""
    ordered = sorted((r for r in reads if r.stock is not None), key=lambda r: r.read_at)
    out: set[date] = set()
    carried: int | None = None
    i = 0
    day = start
    # the reads before the window set the carried value
    while i < len(ordered) and local_day(ordered[i].read_at) < start:
        carried = ordered[i].stock
        i += 1
    while day <= end:
        seen: list[int] = []
        while i < len(ordered) and local_day(ordered[i].read_at) == day:
            seen.append(int(ordered[i].stock or 0))
            i += 1
        if (seen and min(seen) == 0) or (not seen and carried == 0):
            out.add(day)
        if seen:
            carried = seen[-1]
        day += timedelta(days=1)
    return out


def zero_since(reads: Sequence[Read]) -> date | None:
    """The local day the current run of 0-stock reads began; None when the newest read is > 0."""
    ordered = sorted((r for r in reads if r.stock is not None), key=lambda r: r.read_at)
    if not ordered or ordered[-1].stock != 0:
        return None
    first = ordered[-1]
    for r in reversed(ordered):
        if r.stock != 0:
            break
        first = r
    return local_day(first.read_at)


__all__ = [
    "LOCAL_OFFSET",
    "Read",
    "StockNow",
    "basis",
    "is_fresh_read",
    "local",
    "local_day",
    "stock_now",
    "usable",
    "zero_days",
    "zero_since",
]
