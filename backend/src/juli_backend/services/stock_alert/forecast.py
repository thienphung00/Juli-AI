"""Units-per-day forecast and days of stock left for one variation (Part S). Pure, no DB.

Base rate u (units / day) from the last 90 local days before ``today`` (``today`` itself is not
complete and is left out). The days it averages (:func:`kept_days`):

1. every day of the window on or after the shop's first day of order data on which the variation
   had stock (a 0-stock day could not sell; those never count);
2. minus the sale calendar (:data:`SALE_CALENDAR`): the monthly double day (1.1 .. 12.12), the 15th
   ("Giữa tháng siêu ưu đãi") and the 25th ("Sale lương về") of every month, and the day after each
   (sale traffic and late deliveries run into the next day);
3. minus the variation's own spikes: with at least :data:`MIN_KEPT_DAYS` days kept, a day whose
   units exceed :data:`SPIKE_FACTOR` x the median of the kept days (a shop campaign or flash sale
   that is not on the calendar);
4. if fewer than :data:`MIN_KEPT_DAYS` days are left after 2-3, fall back to all the days of 1
   (no sale or spike exclusion).

At least :data:`MIN_ORDERS_FOR_WEIGHTS` orders in the last 30 days: a weighted average of the kept
days, the last 30 days weight 2, days 31-90 weight 1; fewer: their plain average.

Card effect: each approved or running card on the product adds ``units_per_day`` on the days it
covers (:class:`CardEffect`). :func:`days_left` walks day by day from ``today``: stock minus (base
+ the cards active that day); days left = the number of days until the stock is <= 0. u = 0 and
no card -> no forecast (``None``): a variation that does not sell gets no alert.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from datetime import date, timedelta

HISTORY_DAYS = 90
RECENT_DAYS = 30
RECENT_WEIGHT = 2
OLDER_WEIGHT = 1
MIN_ORDERS_FOR_WEIGHTS = 10
#: The walk with cards covers the next 30 days; past it only the base rate runs.
CARD_HORIZON_DAYS = 30
#: Longest walk; a variation lasting longer than this is "never" for an alert.
MAX_DAYS = 3650


@dataclass(frozen=True)
class SaleCalendar:
    """Recurring sale days: the double day (day == month), fixed days of every month, and how many
    following days count as part of the sale."""

    double_day: bool
    monthly_days: tuple[int, ...]
    spill_days: int

    def is_sale_day(self, day: date) -> bool:
        for back in range(self.spill_days + 1):
            d = day - timedelta(days=back)
            if (self.double_day and d.day == d.month) or d.day in self.monthly_days:
                return True
        return False


#: Shopee VN's recurring sale days (owner, 2026-11-14): 1.1 .. 12.12, the 15th ("Giữa tháng siêu
#: ưu đãi"), the 25th ("Sale lương về"), each with the day after. A stand-in until a per-shop
#: calendar exists: swap this constant (or pass another calendar to :func:`kept_days`).
SALE_CALENDAR = SaleCalendar(double_day=True, monthly_days=(15, 25), spill_days=1)
#: Fewest days the base rate may average after the exclusions; below it, rule 4's fallback.
MIN_KEPT_DAYS = 14
#: A day above this x the median of the kept days is the variation's own spike.
SPIKE_FACTOR = 3.0


def is_sale_day(day: date) -> bool:
    return SALE_CALENDAR.is_sale_day(day)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def kept_days(
    daily_units: Mapping[date, float],
    today: date,
    *,
    zero_stock_days: Set[date] = frozenset(),
    first_day: date | None = None,
    calendar: SaleCalendar = SALE_CALENDAR,
) -> list[date]:
    """The days the base rate averages (rules 1-4 of the module docstring)."""
    in_stock: list[date] = []
    for back in range(1, HISTORY_DAYS + 1):
        day = today - timedelta(days=back)
        if first_day is not None and day < first_day:
            break
        if day not in zero_stock_days:
            in_stock.append(day)
    kept = [d for d in in_stock if not calendar.is_sale_day(d)]
    if len(kept) >= MIN_KEPT_DAYS:
        median = _median([float(daily_units.get(d, 0.0)) for d in kept])
        if median > 0:
            kept = [d for d in kept if float(daily_units.get(d, 0.0)) <= SPIKE_FACTOR * median]
    return kept if len(kept) >= MIN_KEPT_DAYS else in_stock


@dataclass(frozen=True)
class CardEffect:
    """Extra units / day a card adds on the days it covers (``start``..``end``, inclusive)."""

    start: date
    end: date
    units_per_day: float

    def on(self, day: date) -> float:
        return self.units_per_day if self.start <= day <= self.end else 0.0


def base_rate(
    daily_units: Mapping[date, float],
    today: date,
    *,
    zero_stock_days: Set[date] = frozenset(),
    orders_30: int,
    first_day: date | None = None,
) -> float:
    """u over the 90 days before ``today`` (see the module docstring); 0.0 with no counted day."""
    weighted = orders_30 >= MIN_ORDERS_FOR_WEIGHTS
    total = weight = 0.0
    for day in kept_days(daily_units, today, zero_stock_days=zero_stock_days, first_day=first_day):
        back = (today - day).days
        w = (RECENT_WEIGHT if back <= RECENT_DAYS else OLDER_WEIGHT) if weighted else 1
        total += w * float(daily_units.get(day, 0.0))
        weight += w
    return total / weight if weight else 0.0


@dataclass(frozen=True)
class Forecast:
    base: float
    days_left: int | None
    runs_out_on: date | None


def days_left(
    stock: int,
    base: float,
    today: date,
    effects: Iterable[CardEffect] = (),
) -> Forecast:
    """Walk from ``today``: ``runs_out_on`` = the first day without stock (today + days left)."""
    cards = [e for e in effects if e.units_per_day > 0]
    if stock <= 0:
        return Forecast(base, 0, today)
    if base <= 0 and not cards:
        return Forecast(base, None, None)
    left = float(stock)
    horizon = today + timedelta(days=CARD_HORIZON_DAYS)
    for i in range(MAX_DAYS):
        day = today + timedelta(days=i)
        extra = sum(e.on(day) for e in cards) if day < horizon else 0.0
        left -= base + extra
        if left <= 1e-9:
            return Forecast(base, i + 1, today + timedelta(days=i + 1))
        if base <= 0 and day >= horizon:
            break
    return Forecast(base, None, None)


__all__ = [
    "CARD_HORIZON_DAYS",
    "HISTORY_DAYS",
    "MIN_KEPT_DAYS",
    "MIN_ORDERS_FOR_WEIGHTS",
    "SALE_CALENDAR",
    "SPIKE_FACTOR",
    "CardEffect",
    "Forecast",
    "base_rate",
    "days_left",
    "SaleCalendar",
    "is_sale_day",
    "kept_days",
]
