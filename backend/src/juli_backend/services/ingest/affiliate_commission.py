"""Which SellerConversionReport column is the seller's commission (open question G-15).

RULE (P91 D-9, pending the owner's confirmation on real data)::

    commission of a line = ``Chi phí(₫)``  (row field ``cost``)

``Chi phí(₫)`` is what the programme charges the seller for the line, the same word as the
bill's ``Chi phí hàng tháng(₫)``. The ``Hoa hồng Xtra ...`` columns (product / order level, and
the shares of the KOLs and the MCN) are NOT added on top: they are components Shopee shows of the
Xtra programme and are paid from the "Tăng đơn cùng KOL" wallet (the bill's
``wallet_offset``), so summing them with ``cost`` would count them twice. The report has no
separate base-commission column.

Check, month by month, against ``ValidationBill``: the sum of ``cost`` of the month's valid
lines must reconcile with the bill's ``Hoa hồng hằng tháng(₫)`` (``commission``), or with its
``Chi phí hàng tháng(₫)`` (``cost``) when the bill's cost is commission plus tax.
:func:`reconcile_month` reports which candidate column matches within
:data:`TOLERANCE`; ``test_shopee_kol_commission`` runs it on SYNTHETIC fixtures that mirror the
real header set. Real figures were not available when this was written, so the result is
``confirmed = False`` until the owner checks one real month (``reconcile_month`` on a real
export is the whole check).

Commission BASE for any rate-derived commission (a line with no reported ``cost``): the line's
``buyer_paid`` = deal price x qty - shop voucher share - combo discount, i.e. the order value after
the shop's own discounts and before shipping, as stored in ``shopee_order_lines`` (the same
``OrderLine.buyer_paid`` the fee and profit waterfall use). Platform-funded discounts are not
deducted (Shopee pays them); shipping and bank promotions never enter it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.ingest.schemas import ShopeeAffiliateOrderLineRow

#: Relative gap under which a column "matches" the bill.
TOLERANCE = Decimal("0.005")
CONFIRMED_BY_OWNER = False
ZERO = Decimal(0)

RULE_COLUMN = "Chi phí(₫)"
RULE_FIELD = "cost"


def seller_commission(row: ShopeeAffiliateOrderLineRow) -> Decimal | None:
    """The seller's commission of one report row; ``None`` when the row reports none."""
    return row.cost


def xtra_total(row: ShopeeAffiliateOrderLineRow) -> Decimal | None:
    """Product-level plus order-level ``Hoa hồng Xtra`` of a row (candidate, not the rule)."""
    parts = [row.xtra_product_commission, row.xtra_order_commission]
    present = [p for p in parts if p is not None]
    return sum(present, ZERO) if present else None


@dataclass(frozen=True)
class MonthReconciliation:
    month: str
    lines: int
    sum_cost: Decimal
    sum_xtra: Decimal
    bill_commission: Decimal | None
    bill_cost: Decimal | None
    #: candidate name -> matches the bill within TOLERANCE.
    matches: dict[str, bool]
    #: The column the rule uses ("cost") when it matches, else None (nothing reconciles).
    rule_field: str | None
    confirmed: bool = CONFIRMED_BY_OWNER


def _close(a: Decimal, b: Decimal | None) -> bool:
    if b is None:
        return False
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) <= TOLERANCE


def reconcile_month(
    month: str,
    rows: Iterable[ShopeeAffiliateOrderLineRow],
    *,
    bill_commission: Decimal | None,
    bill_cost: Decimal | None,
) -> MonthReconciliation:
    """Compare one month of valid report rows with that month's bill totals."""
    kept = [r for r in rows if r.valid is not False]
    sum_cost = sum((seller_commission(r) or ZERO for r in kept), ZERO)
    sum_xtra = sum((xtra_total(r) or ZERO for r in kept), ZERO)
    matches = {
        "cost~bill.commission": _close(sum_cost, bill_commission),
        "cost~bill.cost": _close(sum_cost, bill_cost),
        "xtra~bill.commission": _close(sum_xtra, bill_commission),
    }
    use = matches["cost~bill.commission"] or matches["cost~bill.cost"]
    return MonthReconciliation(
        month=month,
        lines=len(kept),
        sum_cost=sum_cost,
        sum_xtra=sum_xtra,
        bill_commission=bill_commission,
        bill_cost=bill_cost,
        matches=matches,
        rule_field=RULE_FIELD if use else None,
    )
