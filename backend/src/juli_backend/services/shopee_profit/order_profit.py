"""Order line + SKU cost -> profit waterfall.

list -> promo discount -> shop voucher -> combo (bundle) discount -> buyer pays -> platform
fees -> COGS -> packaging -> affiliate commission = CONTRIBUTION (before ads) -> line ad split
= profit (display).

Rules:
- ``buyer_paid`` = deal_price*qty - shop_voucher_share - bundle_discount.
- Fees: the line's actual fees when Shopee reported them, else the formula valid on the
  order date (``fee_source`` says which). Per-order FIXED fees are charged once per order:
  :func:`profit_lines` splits them over the order's lines by ``order_value``.
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

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)


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
    fixed_fees: Mapping[str, Decimal] | None = None,
) -> ProfitBreakdown:
    """One line's waterfall. ``fixed_fees`` = the line's share of the order's fixed fees
    (:meth:`FeeFormula.split_fixed`); omitted, the line is treated as the whole order."""
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
            result = formula.fee(line, fixed_fees)
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
    if line.affiliate:
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
        contribution = line.buyer_paid - fees_total - cogs - packaging - commission
    profit: Decimal | None = None
    margin: Decimal | None = None
    if contribution is not None and ads is not None:
        profit = contribution - ads
        margin = safe_div(profit, line.buyer_paid)

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

    Fixed per-order fees are charged once per order and split over the order's formula-fee
    lines by ``order_value``; pass whole orders (all their lines), not a subset.
    """
    pools = ads_pools or {}
    by_order: dict[str, list[int]] = defaultdict(list)
    for i, ln in enumerate(lines):
        if ln.actual_fees is None:
            by_order[ln.order_id].append(i)
    fixed: dict[int, Mapping[str, Decimal]] = {}
    if schedule is not None:
        for idxs in by_order.values():
            formula = schedule.formula_on(lines[idxs[0]].order_date)
            if formula is None:
                continue
            shares = formula.split_fixed([lines[i].order_value for i in idxs])
            fixed.update(zip(idxs, shares, strict=True))
    return [
        (
            ln,
            line_profit(
                ln,
                costs.get(ln.sku),
                schedule=schedule,
                ads_pool=pools.get(ln.sku),
                affiliate_rate=affiliate_rate,
                fixed_fees=fixed.get(i),
            ),
        )
        for i, ln in enumerate(lines)
    ]
