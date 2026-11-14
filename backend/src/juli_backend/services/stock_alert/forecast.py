"""Units-per-day forecast and days of stock left for one variation (Part S). Pure, no DB.

Base rate u (units / day) from the last 90 local days before ``today`` (``today`` itself is not
complete and is left out):

- a day counts unless the variation had 0 stock that day (it could not sell) or it is a mega-sale
  day (:data:`MEGA_SALE_DAYS`), or it lies before the shop's first day of order data;
- at least :data:`MIN_ORDERS_FOR_WEIGHTS` orders in the last 30 days: a weighted average, the last
  30 days weight 2, days 31-90 weight 1; fewer: the plain average of the counted days.

Card effect: each approved or running card on the product adds ``units_per_day`` on the days it
covers (:class:`CardEffect`). :func:`days_left` walks day by day from ``today``: stock minus (base
+ the cards active that day); days left = the number of days until the stock is <= 0. u = 0 and
no card -> no forecast (``None``): a variation that does not sell gets no alert.

Mega-sale days: the repo has no mega-sale calendar (``shopee_recommendations.mega`` takes a window
per card), so the double days the brief names are a constant here: 9.9, 10.10, 11.11, 12.12.
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

#: (month, day) of the mega-sale days left out of the base rate.
MEGA_SALE_DAYS: frozenset[tuple[int, int]] = frozenset({(9, 9), (10, 10), (11, 11), (12, 12)})


def is_mega_sale_day(day: date) -> bool:
    return (day.month, day.day) in MEGA_SALE_DAYS


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
    for back in range(1, HISTORY_DAYS + 1):
        day = today - timedelta(days=back)
        if first_day is not None and day < first_day:
            break
        if day in zero_stock_days or is_mega_sale_day(day):
            continue
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
    "MEGA_SALE_DAYS",
    "MIN_ORDERS_FOR_WEIGHTS",
    "CardEffect",
    "Forecast",
    "base_rate",
    "days_left",
    "is_mega_sale_day",
]
