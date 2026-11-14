"""Which variations get a stock alert, and in which order (Part S). Pure, no DB.

Eligible (all of):

- the listing was active at the last read (not unlisted / deleted / hidden / banned);
- at least one order in the last 30 days;
- at least 3 orders, or at least 30 days of history;
- not at 0 stock for more than 7 days.

Triggers (any of): days left <= N (the shop's ``stock_alert_days``, default 7); the stock runs out
before the end of an approved / running card on the product; stock 0 now and it reached 0 within
the last 7 days ("Đã hết hàng"). Sort: "Đã hết hàng" first, then days left ascending, then units /
day descending.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from juli_backend.services.stock_alert.forecast import CardEffect, Forecast, days_left

MIN_ORDERS = 3
MIN_HISTORY_DAYS = 30
MAX_ZERO_DAYS = 7
DEFAULT_ALERT_DAYS = 7

INACTIVE_STATUSES = frozenset({"unlisted", "deleted", "hidden", "banned"})

REASON_DAYS = "days_left"
REASON_CARD = "card_end"
REASON_OUT = "out_of_stock"


@dataclass(frozen=True)
class SkuFacts:
    item_id: str
    model_id: str
    product_name: str
    variation_name: str | None
    listing_status: str | None
    orders_30: int
    orders_total: int
    history_days: int
    stock: int
    base: float
    zero_since: date | None = None
    effects: tuple[CardEffect, ...] = ()
    #: last day of each approved / running card on the product
    card_ends: tuple[date, ...] = ()
    #: the seller's own Shopee SKU code (model / item SKU of the product list), when known
    sku_code: str | None = None

    @property
    def key(self) -> str:
        return f"{self.item_id}:{self.model_id}" if self.model_id else self.item_id


@dataclass(frozen=True)
class AlertRow:
    facts: SkuFacts
    forecast: Forecast
    reason: str
    out_since: date | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def out_of_stock(self) -> bool:
        return self.reason == REASON_OUT


def listing_active(status: str | None) -> bool:
    return (status or "").strip().lower() not in INACTIVE_STATUSES


def is_eligible(f: SkuFacts, today: date) -> bool:
    if not listing_active(f.listing_status):
        return False
    if f.orders_30 < 1:
        return False
    if f.orders_total < MIN_ORDERS and f.history_days < MIN_HISTORY_DAYS:
        return False
    if f.stock <= 0 and f.zero_since is not None and (today - f.zero_since).days > MAX_ZERO_DAYS:
        return False
    return True


def evaluate(f: SkuFacts, today: date, *, alert_days: int = DEFAULT_ALERT_DAYS) -> AlertRow | None:
    """The alert row of an eligible variation, or None when no trigger fires."""
    if f.stock <= 0:
        since = f.zero_since or today
        if (today - since).days <= MAX_ZERO_DAYS:
            return AlertRow(f, Forecast(f.base, 0, since), REASON_OUT, out_since=since)
        return None
    fc = days_left(f.stock, f.base, today, f.effects)
    if fc.days_left is None or fc.runs_out_on is None:
        return None
    if fc.days_left <= alert_days:
        return AlertRow(f, fc, REASON_DAYS)
    if any(fc.runs_out_on <= end for end in f.card_ends):
        return AlertRow(f, fc, REASON_CARD)
    return None


def sort_rows(rows: Iterable[AlertRow]) -> list[AlertRow]:
    def key(r: AlertRow) -> tuple[int, int, float, str]:
        left = r.forecast.days_left if r.forecast.days_left is not None else 10**6
        return (0 if r.out_of_stock else 1, left, -r.facts.base, r.facts.key)

    return sorted(rows, key=key)


def split_new(
    rows: Sequence[AlertRow], previous: set[str] | None
) -> tuple[list[AlertRow], list[AlertRow]]:
    """``(new today, still running out)``: a row whose variation was not in yesterday's e-mail is
    new; with no previous e-mail (``previous`` None) every row is new. Each group keeps the order of
    ``rows``."""
    if previous is None:
        return list(rows), []
    new = [r for r in rows if r.facts.key not in previous]
    return new, [r for r in rows if r.facts.key in previous]


def alerts(
    facts: Sequence[SkuFacts],
    today: date,
    *,
    alert_days: int = DEFAULT_ALERT_DAYS,
    tracked: set[str] | None = None,
) -> list[AlertRow]:
    """Every eligible, tracked variation that triggers, sorted. ``tracked`` = the keys whose
    "Theo dõi" switch is on (None: all)."""
    out = []
    for f in facts:
        if tracked is not None and f.key not in tracked:
            continue
        if not is_eligible(f, today):
            continue
        row = evaluate(f, today, alert_days=alert_days)
        if row is not None:
            out.append(row)
    return sort_rows(out)


__all__ = [
    "DEFAULT_ALERT_DAYS",
    "AlertRow",
    "SkuFacts",
    "alerts",
    "evaluate",
    "is_eligible",
    "listing_active",
    "sort_rows",
    "split_new",
]
