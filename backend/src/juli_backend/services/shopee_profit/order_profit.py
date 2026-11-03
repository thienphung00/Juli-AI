"""Order line + SKU cost -> profit waterfall.

list -> promo discount -> shop voucher -> combo (bundle) discount -> buyer pays -> platform
fees -> COGS -> packaging -> affiliate commission = CONTRIBUTION (before ads) -> line ad split
= profit (display).

Rules:
- ``buyer_paid`` = deal_price*qty - shop_voucher_share - bundle_discount.
- Fees: the line's actual fees when Shopee reported them, else the formula valid on the
  order date (``fee_source`` says which). Per-order fees (fixed amounts and the transaction
  fee on the order base) are charged once per order: :func:`profit_lines` splits them over the
  order's lines by value.
- ``contribution`` = buyer_paid - fees - COGS - packaging - commission. It is the source of
  truth for profit (product profit = sum of contribution - the product's ad spend from the ads
  report, see :mod:`.shop_profit`).
- COGS is per unit (x qty); packaging is per order line.
- Line ad split (DISPLAY AID, only for ``ad_attributed`` lines; never the source of product
  or shop profit): the SKU's ad cost x (line ad revenue /
  SKU ad revenue). Ad revenue of a line is its LIST value (``list_value``), so a voucher
  change never moves the ad cost of an order. No pool -> ``missing``, never zero.
- Commission: affiliate lines use the reported ``commission``, else ``affiliate_rate`` x
  buyer_paid; neither -> ``missing``.
- Order status (:class:`OrderStatus`): cancelled / undelivered / refund "not received" lines
  get no fee and no profit (``excluded_reason``); an accepted refund keeps the fee.
- Missing input never becomes 0: ``contribution``/``profit``/``margin`` are ``None`` and
  ``missing`` lists why.
- ``margin_rate`` = profit / buyer_paid.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from juli_backend.services.shopee_profit.fees import FeeFormula, FeeSchedule
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong


class OrderStatus(StrEnum):
    """Where a confirmed order ended up (contract 10). Every status is a "confirmed" order
    (GMV counts in confirmed views); only some carry fees and profit.

    - ``delivered``: fees and profit.
    - ``refunded_accepted``: "Hoan tien ngay" accepted -- the fee is kept, revenue is 0, goods and
      packaging are lost, no affiliate commission.
    - ``in_transit`` (not yet delivered), ``cancelled``, ``refunded_not_received`` ("Chua nhan
      duoc hang"): no fee and no profit; the order is outside the profit and coverage base.
    """

    DELIVERED = "delivered"
    REFUNDED_ACCEPTED = "refunded_accepted"
    IN_TRANSIT = "in_transit"
    CANCELLED = "cancelled"
    REFUNDED_NOT_RECEIVED = "refunded_not_received"

    @property
    def carries_profit(self) -> bool:
        return self in (OrderStatus.DELIVERED, OrderStatus.REFUNDED_ACCEPTED)


class PromoKind(StrEnum):
    NONE = "none"
    PROMOTION = "promotion"
    FLASH_SALE = "flash_sale"


@dataclass(frozen=True)
class OrderLine:
    order_id: str
    sku: str
    product_id: str
    order_date: date
    qty: int
    original_price: Decimal
    deal_price: Decimal
    shop_voucher_share: Decimal = ZERO
    bundle_discount: Decimal = ZERO
    promo_kind: PromoKind = PromoKind.NONE
    ad_attributed: bool = False
    affiliate: bool = False
    commission: Decimal | None = None
    actual_fees: Decimal | None = None
    buyer_shipping_fee: Decimal | None = None  # shipping the buyer paid (order level; NULL = 0)
    bank_promo: Decimal | None = None  # bank promotion (order level; NULL = 0)
    status: OrderStatus = OrderStatus.DELIVERED

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("qty must be positive")

    @property
    def list_value(self) -> Decimal:
        return self.original_price * self.qty

    @property
    def order_value(self) -> Decimal:
        return self.deal_price * self.qty

    @property
    def buyer_paid(self) -> Decimal:
        return self.order_value - self.shop_voucher_share - self.bundle_discount

    @property
    def item_after_seller_promo(self) -> Decimal:
        """Price before Shopee subsidy - seller-funded promotions (programme discount, shop
        voucher, combo): the per-item fee base. Equals ``buyer_paid`` (shipping excluded)."""
        return self.buyer_paid

    @property
    def shipping_net(self) -> Decimal:
        """Buyer-paid shipping - bank promotion; summed over an order's lines (order level
        values may sit on any one line)."""
        return (self.buyer_shipping_fee or ZERO) - (self.bank_promo or ZERO)


@dataclass(frozen=True)
class SkuCost:
    sku: str
    cogs: Decimal | None  # per unit
    packaging: Decimal | None  # per order line


@dataclass(frozen=True)
class AdsPool:
    """A SKU's ad cost and the ad revenue (list value) it is spread over."""

    sku_ad_cost: Decimal
    sku_ad_revenue: Decimal


@dataclass(frozen=True)
class ProfitBreakdown:
    list_value: Decimal
    promo_discount: Decimal
    voucher: Decimal
    bundle: Decimal
    buyer_paid: Decimal
    fees: tuple[tuple[str, Decimal], ...] | None
    fees_total: Decimal | None
    fee_source: str | None  # "actual" | "formula"
    cogs: Decimal | None
    packaging: Decimal | None
    ads: Decimal | None
    commission: Decimal | None
    contribution: Decimal | None  # before ads
    profit: Decimal | None  # contribution - line ad split (display aid)
    margin_rate: Decimal | None
    missing: tuple[str, ...] = field(default=())
    status: OrderStatus = OrderStatus.DELIVERED
    # "no_fee_no_profit": cancelled / in transit / not received -- outside the profit base
    excluded_reason: str | None = None

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)

    @property
    def revenue(self) -> Decimal:
        """Money actually kept from the buyer: ``buyer_paid``, 0 for an accepted refund."""
        return ZERO if self.status is OrderStatus.REFUNDED_ACCEPTED else self.buyer_paid


def allocate_ads(pool: AdsPool, line_ad_revenue: Decimal) -> Decimal | None:
    """SKU ad cost x (line ad revenue / SKU ad revenue), whole đồng; None if no revenue base."""
    if pool.sku_ad_revenue <= 0:
        return None
    return to_dong(pool.sku_ad_cost * line_ad_revenue / pool.sku_ad_revenue)


def line_profit(
    line: OrderLine,
    cost: SkuCost | None,
    *,
    schedule: FeeSchedule | None = None,
    ads_pool: AdsPool | None = None,
    affiliate_rate: Decimal | None = None,
    per_order_fees: Mapping[str, Decimal] | None = None,
) -> ProfitBreakdown:
    """One line's waterfall. ``per_order_fees`` = the line's share of the order's per-order
    fees (:meth:`FeeFormula.split_per_order`); omitted, the line is treated as the whole order.
    Orders that do not carry profit (see :class:`OrderStatus`) get no fee and no profit."""
    if not line.status.carries_profit:
        return ProfitBreakdown(
            list_value=line.list_value,
            promo_discount=line.list_value - line.order_value,
            voucher=line.shop_voucher_share,
            bundle=line.bundle_discount,
            buyer_paid=line.buyer_paid,
            fees=None,
            fees_total=None,
            fee_source="not_charged",
            cogs=None,
            packaging=None,
            ads=None,
            commission=None,
            contribution=None,
            profit=None,
            margin_rate=None,
            missing=(),
            status=line.status,
            excluded_reason="no_fee_no_profit",
        )
    refunded = line.status is OrderStatus.REFUNDED_ACCEPTED
    missing: list[str] = []

    fees: tuple[tuple[str, Decimal], ...] | None = None
    fees_total: Decimal | None = None
    fee_source: str | None = None
    if line.actual_fees is not None:
        fees, fees_total, fee_source = (("actual", line.actual_fees),), line.actual_fees, "actual"
    else:
        formula: FeeFormula | None = schedule.formula_on(line.order_date) if schedule else None
        if formula is None:
            missing.append("fee_formula")
        else:
            result = formula.fee(line, per_order_fees)
            fees, fees_total, fee_source = result.components, result.total, "formula"

    cogs = cost.cogs * line.qty if cost and cost.cogs is not None else None
    if cogs is None:
        missing.append("cogs")
    packaging = cost.packaging if cost else None
    if packaging is None:
        missing.append("packaging")

    ads: Decimal | None = ZERO
    if line.ad_attributed:
        ads = allocate_ads(ads_pool, line.list_value) if ads_pool else None
        if ads is None:
            missing.append("ads_allocation")

    commission: Decimal | None = ZERO
    if line.affiliate and not refunded:
        if line.commission is not None:
            commission = line.commission
        elif affiliate_rate is not None:
            commission = to_dong(line.buyer_paid * affiliate_rate)
        else:
            commission = None
            missing.append("commission")

    contribution: Decimal | None = None
    if not [m for m in missing if m != "ads_allocation"]:
        assert fees_total is not None and cogs is not None and packaging is not None
        assert commission is not None
        revenue = ZERO if refunded else line.buyer_paid
        contribution = revenue - fees_total - cogs - packaging - commission
    profit: Decimal | None = None
    margin: Decimal | None = None
    if contribution is not None and ads is not None:
        profit = contribution - ads
        margin = safe_div(profit, ZERO if refunded else line.buyer_paid)

    return ProfitBreakdown(
        list_value=line.list_value,
        promo_discount=line.list_value - line.order_value,
        voucher=line.shop_voucher_share,
        bundle=line.bundle_discount,
        buyer_paid=line.buyer_paid,
        fees=fees,
        fees_total=fees_total,
        fee_source=fee_source,
        cogs=cogs,
        packaging=packaging,
        ads=ads,
        commission=commission,
        contribution=contribution,
        profit=profit,
        margin_rate=margin,
        missing=tuple(missing),
        status=line.status,
    )


def profit_lines(
    lines: Sequence[OrderLine],
    costs: Mapping[str, SkuCost],
    *,
    schedule: FeeSchedule | None = None,
    ads_pools: Mapping[str, AdsPool] | None = None,
    affiliate_rate: Decimal | None = None,
) -> list[tuple[OrderLine, ProfitBreakdown]]:
    """Waterfall for every line (input order kept), looking cost and ads pool up by SKU.

    Per-order fees (fixed amounts, the transaction fee) are charged once per order and split
    over the order's formula-fee lines by value; pass whole orders (all their lines), not a subset.
    """
    pools = ads_pools or {}
    by_order: dict[str, list[int]] = defaultdict(list)
    for i, ln in enumerate(lines):
        if ln.actual_fees is None and ln.status.carries_profit:
            by_order[ln.order_id].append(i)
    shares_by_line: dict[int, Mapping[str, Decimal]] = {}
    if schedule is not None:
        for idxs in by_order.values():
            formula = schedule.formula_on(lines[idxs[0]].order_date)
            if formula is None:
                continue
            shares = formula.split_per_order([lines[i] for i in idxs])
            shares_by_line.update(zip(idxs, shares, strict=True))
    return [
        (
            ln,
            line_profit(
                ln,
                costs.get(ln.sku),
                schedule=schedule,
                ads_pool=pools.get(ln.sku),
                affiliate_rate=affiliate_rate,
                per_order_fees=shares_by_line.get(i),
            ),
        )
        for i, ln in enumerate(lines)
    ]
