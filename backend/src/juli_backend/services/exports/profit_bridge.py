"""The "Lợi nhuận" sheet's figures: the shop's revenue lines and its profit bridge (owner Q3,
2026-11-17). Pure: one :class:`PeriodView` in, plain numbers out.

Two blocks:

- **Doanh thu** -- GMV (the dashboard's headline: Shopee's shop totals, else the window's sale
  lines), the cancelled orders, the orders in transit, the refund orders (only when the headline
  is Shopee's total, which still holds them: the sale lines leave them out, owner 2026-11-18),
  the buyer paid of the successful orders, the shop's offers (already deducted from what the
  buyer paid, so never a cost again) and the payout Shopee transferred (orders with an
  income-export row). GMV - lost - pending - refunds (when held) = the GMV of the delivered
  orders, whose buyer paid is that GMV less the offers.
- **Lợi nhuận (gộp → đóng góp → ròng, #51)** -- over exactly the orders the dashboard profit counts
  (:func:`known_cost_profit`: every counted line of the order has its costs): revenue after
  output VAT, then each cost on its own line, then the profit and its margin over that revenue.
  The costs are the same terms :func:`line_profit` takes off each line and the ads are the
  charged ads of the bridge, so the lines add up to the dashboard's profit (to the đồng, up to the
  per-line rounding of the đồng amounts).

Each cost says where it came from: ``real_pct`` = the share of the revenue whose figure is the
shop's own data (income export / entered cost), the rest assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.shared import shop_profit_of, shop_profit_raw
from juli_backend.services.shopee_profit.ladder import affiliate_cost
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.order_profit import REFUND_STATUSES, OrderStatus

#: statuses whose GMV is lost before the profit (cancelled)
LOST_STATUSES = frozenset({OrderStatus.CANCELLED})
#: not an outcome yet: in transit
PENDING_STATUSES = frozenset({OrderStatus.IN_TRANSIT})
#: the refund statuses (refund window open, return parcel on its way, returned): no sale, so
#: outside the sale-line GMV (owner 2026-11-18); subtracted only from Shopee's own total
REFUND_BRIDGE_STATUSES = REFUND_STATUSES
#: where a line's Shopee fee came from: the shop's own figures (the rest is the fee formula)
REAL_FEE_SOURCES = frozenset({"income", "actual"})


@dataclass(frozen=True)
class ProfitBridge:
    """``None`` = no figure (the cell shows "—"), never 0."""

    # Doanh thu (all order lines of the window)
    gmv: float | None
    orders: int | None
    lost_gmv: float
    lost_orders: int
    pending_gmv: float  # in transit: no outcome yet, outside the profit
    pending_orders: int
    refund_gmv: float  # the refund orders (REFUND_STATUSES): no sale
    refund_orders: int
    #: the headline GMV still holds the refund orders (Shopee's shop total), so the bridge
    #: subtracts them; False = the headline is the sale lines, which already leave them out
    refunds_in_gmv: bool
    paid_success: float  # buyer paid (VAT included) of the delivered orders
    success_orders: int
    offers: float  # khuyến mãi + voucher + combo of the counted lines: inside the buyer paid
    payout: float | None  # Shopee's payout of the orders with an income row
    payout_orders: int
    # the profit ladder (the known-cost orders, as the dashboard profit)
    known_orders: int
    known_gmv_share_pct: float | None
    revenue: float  # buyer paid - output VAT (0 for an accepted refund)
    vat_output: float
    fees: float
    fees_real_pct: float | None
    cogs: float  # giá vốn after the input-VAT credit
    cogs_real_pct: float | None
    packaging: float
    packaging_real_pct: float | None
    commission: float
    shipping_other: float  # shipping the shop bears and the income export's other costs
    ads: float | None  # the ads charged to the profit (bridge): every day's spend counted
    ads_no_order_days: float
    other_marketing: float
    profit: float | None  # the dashboard's profit (known_cost_profit)
    margin_pct: float | None


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _pct(part: Decimal, whole: Decimal) -> float | None:
    share = safe_div(part * 100, whole)
    return None if share is None else round(float(share), 1)


def profit_bridge(view: Any) -> ProfitBridge:
    """The two blocks of the "Lợi nhuận" sheet for the view's window (see the module doc)."""
    pairs = list(view.pairs)
    kp = shop_profit_raw(view)  # R1: the sheet's lines are the raw figure
    shown = shop_profit_of(view)  # the headline profit and margin: behind the gate
    lost = [(ln, pb) for ln, pb in pairs if ln.status in LOST_STATUSES]
    pending = [(ln, pb) for ln, pb in pairs if ln.status in PENDING_STATUSES]
    refunds = [(ln, pb) for ln, pb in pairs if ln.status in REFUND_BRIDGE_STATUSES]
    success = [(ln, pb) for ln, pb in pairs if ln.status is OrderStatus.DELIVERED]
    counted = [(ln, pb) for ln, pb in pairs if pb.excluded_reason is None]
    unknown = {ln.order_id for ln, pb in counted if pb.contribution is None}
    known = [(ln, pb) for ln, pb in counted if ln.order_id not in unknown]
    with_income = [(ln, pb) for ln, pb in counted if ln.income is not None]

    revenue = sum((pb.revenue for _, pb in known), ZERO)
    real_fees = sum((pb.revenue for _, pb in known if pb.fee_source in REAL_FEE_SOURCES), ZERO)
    payouts = [ln.income.payout for ln, _ in with_income if ln.income.payout is not None]
    coverage = view.coverage
    cogs_real = None if coverage is None else _pct(coverage.real, coverage.base)
    pack_real = (
        None
        if coverage is None
        else _pct(coverage.base - coverage.packaging_assumed, coverage.base)
    )
    return ProfitBridge(
        gmv=_f(view.metrics.gmv),
        orders=view.metrics.orders,
        lost_gmv=float(sum((ln.order_value for ln, _ in lost), ZERO)),
        lost_orders=len({ln.order_id for ln, _ in lost}),
        pending_gmv=float(sum((ln.order_value for ln, _ in pending), ZERO)),
        pending_orders=len({ln.order_id for ln, _ in pending}),
        refund_gmv=float(sum((ln.order_value for ln, _ in refunds), ZERO)),
        refund_orders=len({ln.order_id for ln, _ in refunds}),
        refunds_in_gmv=bool(getattr(view, "gmv_from_totals", False)),
        paid_success=float(sum((pb.buyer_paid for _, pb in success), ZERO)),
        success_orders=len({ln.order_id for ln, _ in success}),
        offers=float(sum((pb.promo_discount + pb.voucher + pb.bundle for _, pb in counted), ZERO)),
        payout=float(sum(payouts, ZERO)) if payouts else None,
        payout_orders=len({ln.order_id for ln, _ in with_income}),
        known_orders=kp.orders,
        known_gmv_share_pct=_f(kp.gmv_share_pct),
        revenue=float(revenue),
        # an accepted refund earns 0 (no VAT is taken out of a revenue it does not have)
        vat_output=float(
            sum(
                (
                    pb.vat_output
                    for _, pb in known
                    if pb.status is not OrderStatus.REFUNDED_ACCEPTED
                ),
                ZERO,
            )
        ),
        fees=float(sum((pb.fees_total or ZERO for _, pb in known), ZERO)),
        fees_real_pct=_pct(real_fees, revenue),
        cogs=float(sum(((pb.cogs or ZERO) - pb.vat_input_credit for _, pb in known), ZERO)),
        cogs_real_pct=cogs_real,
        packaging=float(sum((pb.packaging or ZERO for _, pb in known), ZERO)),
        packaging_real_pct=pack_real,
        commission=float(affiliate_cost(known) or ZERO),
        shipping_other=float(sum((a for _, pb in known for _, a in (pb.income_costs or ())), ZERO)),
        ads=_f(kp.ads_charged) if kp.profit is not None else None,
        ads_no_order_days=float(kp.ads_no_order_days),
        other_marketing=float(kp.other_marketing_charged),
        profit=_f(shown.profit),
        margin_pct=_f(shown.margin_pct),
    )
