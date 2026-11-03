"""Product x source matrix from order lines (profit already computed per line).

Two dimensions, each summing EXACTLY to the totals (checked in code -> ``AdditivityError``):
- traffic: the line's ``traffic_source`` (search / recommend / shop_page / affiliate /
  flash_sale_page / unknown);
- price lever: exactly one per line by precedence bundle > promotion (incl. flash sale price)
  > voucher > none.

Ads are an OVERLAY: ``ads`` counts ad-attributed lines inside whatever traffic/lever they
belong to and is never added to either dimension.

Counting: lines of the same product within one order are merged first, so ``orders`` counts
(order, product) pairs -- an order with two products counts once under each (the product
view), and totals are over those pairs. GMV = ``order_value`` (deal price x qty, before
voucher). ``profit`` sums known line profits; ``orders_missing_profit`` counts pairs with an
unknown cost, which are excluded from profit and margin (margin = profit / buyer-paid of the
known pairs).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    ProfitBreakdown,
    PromoKind,
)


class PriceLever(StrEnum):
    BUNDLE = "bundle"
    PROMOTION = "promotion"
    VOUCHER = "voucher"
    NONE = "none"


class AdditivityError(AssertionError):
    pass


@dataclass(frozen=True)
class CellStats:
    orders: int = 0
    gmv: Decimal = ZERO
    buyer_paid_known: Decimal = ZERO
    profit: Decimal = ZERO
    orders_missing_profit: int = 0

    @property
    def aov(self) -> Decimal | None:
        return safe_div(self.gmv, Decimal(self.orders))

    @property
    def margin_rate(self) -> Decimal | None:
        return safe_div(self.profit, self.buyer_paid_known)

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)

    def plus(self, other: CellStats) -> CellStats:
        return CellStats(
            self.orders + other.orders,
            self.gmv + other.gmv,
            self.buyer_paid_known + other.buyer_paid_known,
            self.profit + other.profit,
            self.orders_missing_profit + other.orders_missing_profit,
        )


@dataclass(frozen=True)
class SourceMatrix:
    traffic: dict[tuple[str, str], CellStats]  # (product_id, traffic source)
    lever: dict[tuple[str, str], CellStats]  # (product_id, price lever)
    ads: dict[str, CellStats]  # product_id -> ad-attributed overlay
    totals: dict[str, CellStats]  # product_id -> everything


def price_lever(promo_kinds: Iterable[PromoKind], voucher: Decimal, bundle: Decimal) -> PriceLever:
    if bundle > 0:
        return PriceLever.BUNDLE
    if any(k is not PromoKind.NONE for k in promo_kinds):
        return PriceLever.PROMOTION
    return PriceLever.VOUCHER if voucher > 0 else PriceLever.NONE


def _cell(pairs: list[tuple[OrderLine, ProfitBreakdown]]) -> CellStats:
    known = all(pb.profit is not None for _, pb in pairs)
    return CellStats(
        orders=1,
        gmv=sum((ln.order_value for ln, _ in pairs), ZERO),
        buyer_paid_known=sum((pb.buyer_paid for _, pb in pairs), ZERO) if known else ZERO,
        profit=sum((pb.profit or ZERO for _, pb in pairs), ZERO) if known else ZERO,
        orders_missing_profit=0 if known else 1,
    )


def build_source_matrix(pairs: Iterable[tuple[OrderLine, ProfitBreakdown]]) -> SourceMatrix:
    groups: dict[tuple[str, str], list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        groups[(ln.order_id, ln.product_id)].append((ln, pb))

    traffic: dict[tuple[str, str], CellStats] = {}
    lever: dict[tuple[str, str], CellStats] = {}
    ads: dict[str, CellStats] = {}
    totals: dict[str, CellStats] = {}
    empty = CellStats()
    for (_, product), grp in groups.items():
        cell = _cell(grp)
        src = grp[0][0].traffic_source.value
        lev = price_lever(
            (ln.promo_kind for ln, _ in grp),
            sum((ln.shop_voucher_share for ln, _ in grp), ZERO),
            sum((ln.bundle_discount for ln, _ in grp), ZERO),
        ).value
        traffic[(product, src)] = traffic.get((product, src), empty).plus(cell)
        lever[(product, lev)] = lever.get((product, lev), empty).plus(cell)
        totals[product] = totals.get(product, empty).plus(cell)
        if any(ln.ad_attributed for ln, _ in grp):
            ads[product] = ads.get(product, empty).plus(cell)

    matrix = SourceMatrix(traffic, lever, ads, totals)
    assert_additive(matrix)
    return matrix


def _sum(cells: Iterable[CellStats]) -> CellStats:
    out = CellStats()
    for c in cells:
        out = out.plus(c)
    return out


def assert_additive(matrix: SourceMatrix) -> None:
    """Both dimensions must equal the totals per product and overall (raises, never strips)."""
    for name, dim in (("traffic", matrix.traffic), ("lever", matrix.lever)):
        per_product: dict[str, CellStats] = {}
        for (product, _), cell in dim.items():
            per_product[product] = per_product.get(product, CellStats()).plus(cell)
        if per_product != matrix.totals:
            raise AdditivityError(f"{name} dimension does not sum to the totals")
    if _sum(matrix.traffic.values()) != _sum(matrix.totals.values()):
        raise AdditivityError("traffic dimension does not sum to the grand total")
    for product, cell in matrix.ads.items():
        total = matrix.totals.get(product, CellStats())
        if cell.orders > total.orders:
            raise AdditivityError("ads overlay exceeds the product total")
