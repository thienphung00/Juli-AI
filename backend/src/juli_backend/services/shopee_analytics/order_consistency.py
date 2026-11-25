"""C9: do the counted order lines of a day add up to the shop's own confirmed GMV?

Pure (no screen reads it yet). Counted = the confirmed (paid) lines' ``deal_price x qty`` less the
shop voucher the SELLER bore; a combo's ``deal_price`` is already its share of the combo price, so
its ``bundle_discount`` is not taken off again. A day where the two differ holds a line set that
is not the shop's (a combo counted twice, an order not read yet); a day with no confirmed GMV or
no lines is not compared. An unknown voucher (``voucher_unknown``) is counted on the day's row.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import OrderLine

#: VND per compared day the two may differ by (line shares round to cents).
TOLERANCE = Decimal(1)


@dataclass(frozen=True)
class DayConsistency:
    day: date
    lines_gmv: Decimal
    confirmed_gmv: Decimal
    unknown_vouchers: int

    @property
    def difference(self) -> Decimal:
        return self.lines_gmv - self.confirmed_gmv

    @property
    def matches(self) -> bool:
        return abs(self.difference) <= TOLERANCE


def day_consistency(
    lines: Iterable[OrderLine], confirmed_gmv: Mapping[date, Decimal]
) -> list[DayConsistency]:
    """One row per day that has both lines and a confirmed GMV, oldest first."""
    totals: dict[date, Decimal] = defaultdict(lambda: ZERO)
    unknown: dict[date, set[str]] = defaultdict(set)
    for ln in lines:
        totals[ln.order_date] += ln.order_value - ln.seller_voucher
        if ln.voucher_unknown:
            unknown[ln.order_date].add(ln.order_id)
    return [
        DayConsistency(day, totals[day], confirmed_gmv[day], len(unknown[day]))
        for day in sorted(totals.keys() & confirmed_gmv.keys())
    ]
