"""Order line + SKU cost -> profit waterfall.

list -> promo discount -> shop voucher -> combo (bundle) discount -> buyer pays -> platform
fees -> COGS -> packaging -> affiliate commission = CONTRIBUTION (before ads) -> line ad split
= profit (display).

Rules:
- ``buyer_paid`` = deal_price*qty - the shop voucher the SELLER bore - bundle_discount (decision
  #50): the buyer-side ``shop_voucher_share`` less ``voucher_funded``, the part the platform
  funded (a Voucher Xtra code the buyer sees as "Mã giảm giá của Shop"), known from the settlement
  (``seller_voucher_borne``). A line with no settlement yet keeps the buyer-side share.
- Income actuals (P91 D-12): a line with ``income`` (its share of the order's row in the income
  export) is charged exactly that: its fees (``fee_source`` ``income``), the affiliate commission
  Shopee took, and the costs the formula never sees - net shipping, return shipping, the coins the
  seller bore, VAT / PIT Shopee withheld, a refund of a delivered line - less any lost-parcel
  compensation. The income wins over ``actual_fees`` and over the formula.
- VAT (P91 D-12): with ``vat`` (the shop's flags and the SKU's rate) revenue is ``buyer_paid`` less
  the VAT inside it and cost is less the input VAT credited; ``vat_basis`` says whether the seller
  has said so (``after_vat``) or the figure is before VAT.
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
- Order status (:class:`OrderStatus`): cancelled / undelivered lines get no fee and no profit
  (``excluded_reason``).
- Refund statuses (owner 2026-11-18: ``refunded_accepted``, ``refunded_not_received``,
  ``returned``): revenue 0, no goods cost, no commission; the cost is the settlement deduction
  ``max(0, -payout)`` as soon as a settlement row exists (no row = no cost yet; a
  ``refunded_*`` line then stays outside the profit base), never the sum of the fee / shipping
  columns. A ``returned`` line also costs its packaging. None of the three is a sale: all are
  outside đơn / GMV / AOV (:func:`counts_in_sales`).
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
from juli_backend.services.shopee_profit.income import LineIncome
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.vat import (
    BASIS_BEFORE,
    VatTreatment,
    input_vat_credit,
    output_vat,
)


class OrderStatus(StrEnum):
    """Where a confirmed order ended up (contract 10). Every status is a "confirmed" order
    (GMV counts in confirmed views); only some carry fees and profit.

    - ``delivered``: fees and profit.
    - ``in_transit`` (not yet delivered), ``cancelled``: no fee and no profit; outside the profit
      and coverage base.
    - The refund statuses (owner, 2026-11-18; Shopee = TikTok, one code path):
      ``refunded_accepted`` (the refund window is still open), ``refunded_not_received`` (the
      return parcel is on its way back) and ``returned`` (T5, D2: goods back with the seller,
      buyer refunded). Revenue 0, goods cost 0, no commission. Their cost is what the settlement
      deducted from the seller, ``max(0, -payout)`` of the order's settlement row, counted as
      soon as a settlement row exists whatever the status says; no settlement row = no cost yet.
      The fee / shipping / return-shipping columns are never summed for them (the payout already
      nets them). A ``returned`` line also costs its packaging (it shipped); the other two do not.
      None of the three is a sale: all are outside đơn / GMV / AOV (``counts_in_sales``).
    """

    DELIVERED = "delivered"
    REFUNDED_ACCEPTED = "refunded_accepted"
    IN_TRANSIT = "in_transit"
    CANCELLED = "cancelled"
    REFUNDED_NOT_RECEIVED = "refunded_not_received"
    RETURNED = "returned"

    @property
    def carries_profit(self) -> bool:
        return self is OrderStatus.DELIVERED

    @property
    def charges_fees(self) -> bool:
        """The fee formula / reported fees are a cost of this line: a sale only. A refund status
        costs its settlement deduction instead (``settles_by_payout``)."""
        return self.carries_profit

    @property
    def settles_by_payout(self) -> bool:
        """A refund status: its cost is the settlement's deduction, ``max(0, -payout)``."""
        return self in REFUND_STATUSES

    @property
    def counts_in_sales(self) -> bool:
        """The line is in đơn / GMV / AOV. No refund status is (owner 2026-11-18: returned,
        refunded_accepted and refunded_not_received are not sales)."""
        return self not in REFUND_STATUSES


#: The statuses whose cost is the settlement deduction (owner 2026-11-18).
REFUND_STATUSES = frozenset(
    {OrderStatus.REFUNDED_ACCEPTED, OrderStatus.REFUNDED_NOT_RECEIVED, OrderStatus.RETURNED}
)
#: ``fee_source`` of a refund line: the settlement's deduction, or no settlement row yet.
FEE_SOURCE_SETTLEMENT = "settlement"
FEE_SOURCE_NO_SETTLEMENT = "no_settlement"
#: The one fee component of a refund line.
FEE_SETTLEMENT_DEDUCTION = "settlement_deduction"


def settlement_deduction(line: OrderLine) -> Decimal | None:
    """What the settlement took from the seller for ``line``: ``max(0, -payout)`` of its share of
    the order's settlement row; ``None`` when there is no settlement row (or no stated payout)."""
    income = line.income
    if income is None or income.payout is None:
        return None
    return max(ZERO, -income.payout)


def counts_in_sales(line: object) -> bool:
    """``line`` counts in đơn / GMV / AOV: every status but the refund statuses
    (``REFUND_STATUSES``, owner 2026-11-18). Any line-like object: an :class:`OrderLine`, or a
    stored order-line row whose ``status`` is the canonical string. Without a status (a what-if
    or synthetic line) it counts."""
    status = getattr(line, "status", None)
    return status is None or status not in REFUND_STATUSES


def counts_in_product_sales(line: object) -> bool:
    """``line`` counts in a PRODUCT's đơn / GMV / AOV (owner #99, 26/11): a sale line that is not
    cancelled. Shopee's shop day rows leave cancelled orders out, so a product built from order
    lines must too, or the products add up to more than the shop."""
    return counts_in_sales(line) and getattr(line, "status", None) is not OrderStatus.CANCELLED


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
    income: LineIncome | None = None  # this line's share of the order's income-export row
    #: decision #50: the part of ``shop_voucher_share`` the platform funded, not the seller
    #: (settlement ``seller_voucher_borne`` below the buyer-side share); 0 without a settlement
    voucher_funded: Decimal = ZERO
    #: C9 (E151): the settlement does not show who bore the shop voucher. It is not charged, and
    #: a sale with it is not costed (missing ``seller_voucher``: a missing cost is never 0)
    voucher_unknown: bool = False

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
    def seller_voucher(self) -> Decimal:
        """The shop voucher the seller bore on this line (decision #50)."""
        return max(ZERO, self.shop_voucher_share - self.voucher_funded)

    @property
    def buyer_paid(self) -> Decimal:
        """Doanh thu thực before VAT: goods total − the seller's voucher − combo (#50)."""
        return self.order_value - self.seller_voucher - self.bundle_discount

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
    #: The shop's VAT flags and this cost key's SKU rate (P91 D-14): ``line_profit`` uses it when
    #: the caller passes none, so the card what-ifs (versions, compare, plan totals), which look
    #: costs up by key, take the same VAT out of revenue and cost as the shop profit does.
    vat: VatTreatment | None = None


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
    #: The costs only the income export states (net shipping ...), as (code, amount).
    income_costs: tuple[tuple[str, Decimal], ...] | None = None
    #: VAT inside ``buyer_paid`` taken out of revenue, and input VAT credited off the cost.
    vat_output: Decimal = ZERO
    vat_input_credit: Decimal = ZERO
    #: ``before_vat`` until the seller says whether the prices carry VAT.
    vat_basis: str = BASIS_BEFORE

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)

    @property
    def income_costs_total(self) -> Decimal | None:
        if self.income_costs is None:
            return None
        return sum((amount for _, amount in self.income_costs), ZERO)

    @property
    def revenue(self) -> Decimal:
        """Money actually kept from the buyer: ``buyer_paid`` less the VAT inside it, 0 for an
        refund status (``REFUND_STATUSES``)."""
        if self.status in REFUND_STATUSES:
            return ZERO
        return self.buyer_paid - self.vat_output

    @property
    def offer_cost(self) -> Decimal:
        """Ưu đãi (one combined cost, #46): Chương Trình Của Shop / Flash Sale price + combo +
        the shop voucher the seller bore (``voucher`` = ``OrderLine.seller_voucher``, #50). A
        platform-funded voucher and the Shopee voucher are never a seller cost."""
        return self.promo_discount + self.bundle + self.voucher

    @property
    def organic_contribution(self) -> Decimal | None:
        """Decision #44: the ladder's Lợi nhuận đóng góp -- ``contribution`` before the affiliate
        commission too (revenue − fees − giá vốn − đóng gói − vận chuyển ròng). ``None`` when the
        contribution is unknown."""
        if self.contribution is None:
            return None
        return self.contribution + (self.commission or ZERO)


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
    vat: VatTreatment | None = None,
) -> ProfitBreakdown:
    """One line's waterfall. ``per_order_fees`` = the line's share of the order's per-order
    fees (:meth:`FeeFormula.split_per_order`); omitted, the line is treated as the whole order.
    Orders that do not carry profit (see :class:`OrderStatus`) get no fee and no profit; a refund
    status costs its settlement deduction (:func:`_refund_profit`)."""
    if line.status.settles_by_payout:
        refund = _refund_profit(line, cost)
        if refund is not None:
            return refund
    if not line.status.carries_profit:
        return ProfitBreakdown(
            list_value=line.list_value,
            promo_discount=line.list_value - line.order_value,
            voucher=line.seller_voucher,
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
    missing: list[str] = []  # a sale (``delivered``) from here on
    if line.voucher_unknown:
        missing.append("seller_voucher")

    fees: tuple[tuple[str, Decimal], ...] | None = None
    fees_total: Decimal | None = None
    fee_source: str | None = None
    income = line.income
    if income is not None:
        fees, fees_total, fee_source = income.fees, income.fees_total, "income"
    elif line.actual_fees is not None:
        fees, fees_total, fee_source = (("actual", line.actual_fees),), line.actual_fees, "actual"
    else:
        formula: FeeFormula | None = schedule.formula_on(line.order_date) if schedule else None
        if formula is None:
            missing.append("fee_formula")
        else:
            result = formula.fee(line, per_order_fees)
            fees, fees_total, fee_source = result.components, result.total, "formula"

    if vat is None and cost is not None:
        vat = cost.vat
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
    if income is not None:
        commission = income.commission
    elif line.affiliate:
        if line.commission is not None:
            commission = line.commission
        elif affiliate_rate is not None:
            commission = to_dong(line.buyer_paid * affiliate_rate)
        else:
            commission = None
            missing.append("commission")

    income_costs = income.other_costs(with_refund=True) if income is not None else None
    vat_out = output_vat(line.buyer_paid, vat)
    vat_credit = input_vat_credit(cogs, vat) if cogs is not None else ZERO
    if vat_out is None or vat_credit is None:
        missing.append("vat_rate")
    vat_basis = vat.basis if vat is not None else BASIS_BEFORE

    contribution: Decimal | None = None
    if not [m for m in missing if m != "ads_allocation"]:
        assert fees_total is not None and cogs is not None and packaging is not None
        assert commission is not None and vat_out is not None and vat_credit is not None
        revenue = line.buyer_paid - vat_out
        other = sum((a for _, a in income_costs), ZERO) if income_costs is not None else ZERO
        contribution = revenue - fees_total - (cogs - vat_credit) - packaging - commission - other
    profit: Decimal | None = None
    margin: Decimal | None = None
    if contribution is not None and ads is not None:
        profit = contribution - ads
        margin = safe_div(profit, line.buyer_paid - (vat_out or ZERO))

    return ProfitBreakdown(
        list_value=line.list_value,
        promo_discount=line.list_value - line.order_value,
        voucher=line.seller_voucher,
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
        income_costs=income_costs,
        vat_output=vat_out or ZERO,
        vat_input_credit=vat_credit or ZERO,
        vat_basis=vat_basis,
    )


def _refund_profit(line: OrderLine, cost: SkuCost | None) -> ProfitBreakdown | None:
    """A refund status's waterfall (owner 2026-11-18): revenue 0, goods cost 0, no commission,
    no VAT; the cost is the settlement deduction ``max(0, -payout)`` (the fee and shipping
    columns are not added: the payout nets them), plus the packaging of a ``returned`` line.
    ``None`` = a ``refunded_*`` line with no settlement row yet: no cost, outside the profit
    base like an order in transit. A ``returned`` line without one costs its packaging only."""
    deduction = settlement_deduction(line)
    returned = line.status is OrderStatus.RETURNED
    if deduction is None and not returned:
        return None
    missing: list[str] = []
    packaging: Decimal | None = ZERO
    if returned:
        packaging = cost.packaging if cost else None
        if packaging is None:
            missing.append("packaging")
    charged = deduction if deduction is not None else ZERO
    contribution = None if packaging is None else -(charged + packaging)
    return ProfitBreakdown(
        list_value=line.list_value,
        promo_discount=line.list_value - line.order_value,
        voucher=line.seller_voucher,
        bundle=line.bundle_discount,
        buyer_paid=line.buyer_paid,
        fees=((FEE_SETTLEMENT_DEDUCTION, charged),),
        fees_total=charged,
        fee_source=FEE_SOURCE_SETTLEMENT if deduction is not None else FEE_SOURCE_NO_SETTLEMENT,
        cogs=ZERO,
        packaging=packaging,
        ads=ZERO,
        commission=ZERO,
        contribution=contribution,
        profit=contribution,
        margin_rate=None,
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
        if ln.actual_fees is None and ln.status.charges_fees:
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
