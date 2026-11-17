"""Pure helpers of the Tổng quan export's report sheets (no DB, no workbook).

- the comparison period (the previous calendar month when the period is a whole month, else the
  same-length previous period);
- the calendar months of a period (+ the month before);
- the channel partition (Organic = GMV - Quảng cáo - Tiếp thị liên kết, no overlap);
- Cần nhập (the stock alert has no restock rule, so this one is labelled in the file).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

#: Cần nhập = bán / ngày x (LEAD_DAYS + COVER_DAYS) - tồn kho, at least 0 (owner Q2, 2026-11-17)
LEAD_DAYS = 7
COVER_DAYS = 14
DASH = "—"

PREV_MONTH = "month"
PREV_PERIOD = "period"


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def is_whole_month(start: date, end: date) -> bool:
    return start.day == 1 and end == month_end(start)


def previous_period(start: date, end: date) -> tuple[date, date, str]:
    """(start, end, kind) of the period the export compares with: the previous calendar month for
    a whole month, else the same number of days ending the day before ``start``."""
    if is_whole_month(start, end):
        last = start - timedelta(days=1)
        return last.replace(day=1), last, PREV_MONTH
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1), PREV_PERIOD


def months_of(start: date, end: date) -> list[tuple[date, date]]:
    """The calendar months before and inside the period as ``(first, last)`` spans: the month before
    ``start``'s month in full, then each month of the period clipped to it."""
    before_last = start.replace(day=1) - timedelta(days=1)
    spans = [(before_last.replace(day=1), before_last)]
    first = start.replace(day=1)
    while first <= end:
        spans.append((max(first, start), min(month_end(first), end)))
        first = month_end(first) + timedelta(days=1)
    return spans


def partition_channels(
    total: float | None, ads: float | None, aff: float | None, organic: float | None
) -> tuple[float | None, float | None, float | None]:
    """(organic, ads, aff) GMV that add up to ``total``: Organic = total - ads - aff (never
    negative); when ads + aff exceed the total, ads gives way first (the affiliate GMV is the
    order lines' own). ``total`` unknown: the three as they are."""
    if total is None:
        return organic, ads, aff
    f = None if aff is None else min(max(aff, 0.0), total)
    a = None if ads is None else min(max(ads, 0.0), max(total - (f or 0.0), 0.0))
    if a is None and f is None:
        return organic, ads, aff
    return max(total - (a or 0.0) - (f or 0.0), 0.0), a, f


def reorder_need(rate: float | None, stock: float | None) -> float | None:
    """Cần nhập (units): rate x (LEAD_DAYS + COVER_DAYS) - stock, at least 0; unknown without
    either."""
    if rate is None or stock is None:
        return None
    return max(rate * (LEAD_DAYS + COVER_DAYS) - stock, 0.0)


def change(now: float | None, before: float | None) -> float | None:
    """now / before - 1; ``None`` when either is unknown or before is 0."""
    if now is None or before is None or before == 0:
        return None
    return now / before - 1
