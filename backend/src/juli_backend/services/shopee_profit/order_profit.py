"""Order line + SKU cost -> profit waterfall.

list -> promo discount -> shop voucher -> bundle discount -> buyer pays -> platform fees
-> COGS -> packaging -> ads allocation -> affiliate commission -> profit.

Rules:
- ``buyer_paid`` = deal_price*qty - shop_voucher_share - bundle_discount.
- Fees: the line's actual fees when Shopee reported them, else the formula valid on the
  order date (``fee_source`` says which).
- COGS is per unit (x qty); packaging is per order line.
- Ads allocation (only for ``ad_attributed`` lines): the SKU's ad cost x (line ad revenue /
  SKU ad revenue). Ad revenue of a line is its LIST value (``list_value``), so a voucher
  change never moves the ad cost of an order. No pool -> ``missing``, never zero.
- Commission: affiliate lines use the reported ``commission``, else ``affiliate_rate`` x
  buyer_paid; neither -> ``missing``.
- Missing input never becomes 0: ``profit``/``margin`` are ``None`` and ``missing`` lists why.
- ``margin_rate`` = profit / buyer_paid.
"""

from __future__ import annotations

from collections.abc import Mapping
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


class TrafficSource(StrEnum):
    SEARCH = "search"
    RECOMMEND = "recommend"
    SHOP_PAGE = "shop_page"
    AFFILIATE = "affiliate"
    FLASH_SALE_PAGE = "flash_sale_page"
    UNKNOWN = "unknown"


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
    traffic_source: TrafficSource = TrafficSource.UNKNOWN

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
    profit: Decimal | None
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
) -> ProfitBreakdown:
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
            result = formula.fee(line)
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

    profit: Decimal | None = None
    margin: Decimal | None = None
    if not missing:
        assert fees_total is not None and cogs is not None and packaging is not None
        assert ads is not None and commission is not None
        profit = line.buyer_paid - fees_total - cogs - packaging - ads - commission
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
        profit=profit,
        margin_rate=margin,
        missing=tuple(missing),
    )


def profit_lines(
    lines: list[OrderLine],
    costs: Mapping[str, SkuCost],
    *,
    schedule: FeeSchedule | None = None,
    ads_pools: Mapping[str, AdsPool] | None = None,
    affiliate_rate: Decimal | None = None,
) -> list[tuple[OrderLine, ProfitBreakdown]]:
    """Waterfall for every line, looking cost and ads pool up by SKU."""
    pools = ads_pools or {}
    return [
        (
            ln,
            line_profit(
                ln,
                costs.get(ln.sku),
                schedule=schedule,
                ads_pool=pools.get(ln.sku),
                affiliate_rate=affiliate_rate,
            ),
        )
        for ln in lines
    ]
