"""Analysis windows: the last 7 / 30 / 90 days, a calendar month, or a custom range, each
with its previous-period comparison (the same number of days, ending the day before).

Pure -- no clock: the caller passes ``as_of`` (the newest day the shop has data for).
Dates are the platform's calendar day (Shopee VN, GMT+7).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

PeriodKind = Literal["7d", "30d", "90d", "month", "custom"]
PERIOD_KINDS: tuple[str, ...] = ("7d", "30d", "90d", "month", "custom")
MAX_WINDOW_DAYS = 400
_LAST_N = {"7d": 7, "30d": 30, "90d": 90}


class InvalidWindow(ValueError):
    pass


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise InvalidWindow("from must not be after to")
        if self.days > MAX_WINDOW_DAYS:
            raise InvalidWindow(f"range is longer than {MAX_WINDOW_DAYS} days")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def overlap_days(self, start: date, end: date) -> int:
        lo, hi = max(self.start, start), min(self.end, end)
        return max((hi - lo).days + 1, 0)

    def previous(self) -> Window:
        """The same number of days, ending the day before this window starts."""
        return Window(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def json(self) -> dict[str, object]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat(), "days": self.days}


def resolve_window(
    kind: str,
    *,
    as_of: date,
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Window:
    """``7d`` / ``30d`` / ``90d`` end on ``as_of``; ``month`` is ``YYYY-MM`` (the current month
    is cut at ``as_of``); ``custom`` needs both bounds."""
    if kind in _LAST_N:
        return Window(as_of - timedelta(days=_LAST_N[kind] - 1), as_of)
    if kind == "month":
        if not month:
            raise InvalidWindow("month needs YYYY-MM")
        try:
            year, mon = (int(part) for part in month.split("-"))
            first = date(year, mon, 1)
        except (ValueError, TypeError):
            raise InvalidWindow("month must be YYYY-MM") from None
        last = date(year, mon, calendar.monthrange(year, mon)[1])
        return Window(first, min(last, as_of) if first <= as_of <= last else last)
    if kind == "custom":
        if start is None or end is None:
            raise InvalidWindow("custom needs from and to")
        return Window(start, end)
    raise InvalidWindow(f"unknown period {kind!r}; known: {list(PERIOD_KINDS)}")


@dataclass(frozen=True)
class PeriodChoice:
    """Which stored period rows stand in for a window (periods overlap and are never added
    blindly). ``basis``: ``exact`` (same dates), ``contained`` (non-overlapping periods inside
    the window), ``approx`` (the one period overlapping the most, at least half the window),
    ``none``."""

    periods: tuple[tuple[date, date], ...]
    basis: str
    covered_days: int

    def json(self) -> dict[str, object]:
        return {
            "basis": self.basis,
            "periods": [{"from": a.isoformat(), "to": b.isoformat()} for a, b in self.periods],
            "covered_days": self.covered_days,
        }


def choose_periods(window: Window, available: set[tuple[date, date]]) -> PeriodChoice:
    if (window.start, window.end) in available:
        return PeriodChoice(((window.start, window.end),), "exact", window.days)
    inside = sorted(
        (p for p in available if window.start <= p[0] and p[1] <= window.end),
        key=lambda p: (-((p[1] - p[0]).days), p[0]),
    )
    picked: list[tuple[date, date]] = []
    for start, end in inside:
        if all(end < a or start > b for a, b in picked):
            picked.append((start, end))
    if picked:
        picked.sort()
        return PeriodChoice(tuple(picked), "contained", sum((b - a).days + 1 for a, b in picked))
    best = max(
        available,
        key=lambda p: (window.overlap_days(*p), -abs((p[1] - window.end).days)),
        default=None,
    )
    if best is not None and window.overlap_days(*best) * 2 >= window.days:
        return PeriodChoice((best,), "approx", window.overlap_days(*best))
    return PeriodChoice((), "none", 0)
