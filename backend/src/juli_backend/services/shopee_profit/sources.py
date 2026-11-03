"""Product x price-lever matrix from order lines (profit already computed per line).

Traffic flows are NOT here: they come from aggregates (:mod:`.flows`), because order lines
carry no traffic source. This module keeps the one dimension that order lines do define,
the price lever (contract section 3), each line exactly one, summing EXACTLY to the totals
(checked in code -> ``AdditivityError``):

``combo`` (Combo khuyen mai / Mua kem deal soc) > ``khuyen_mai`` (discount programme incl.
Flash Sale price) > ``voucher`` (shop voucher) > ``khong_uu_dai``. Shopee-funded vouchers are
not a seller cost and not a lever.

Ads are an OVERLAY: ``ads`` counts ad-attributed lines inside whatever lever they belong to
and is never added to the dimension.

Counting: lines of the same product within one order are merged first, so ``orders`` counts
(order, product) pairs -- an order with two products counts once under each (the product
view), and totals are over those pairs. GMV = ``order_value`` (deal price x qty, before
voucher). ``contribution`` sums known contributions (before ads); ``profit`` is contribution
less the DISPLAY line-level ad split. Pairs with an unknown cost are excluded from both and
from ``buyer_paid_known`` and counted in ``orders_missing_profit``; margin = profit /
buyer_paid of the known pairs (never extrapolated).
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
    COMBO = "combo"
    KHUYEN_MAI = "khuyen_mai"
    VOUCHER = "voucher"
    KHONG_UU_DAI = "khong_uu_dai"


class AdditivityError(AssertionError):
    pass


@dataclass(frozen=True)
class CellStats:
    orders: int = 0
    gmv: Decimal = ZERO
    buyer_paid_known: Decimal = ZERO
    profit: Decimal = ZERO
    contribution: Decimal = ZERO
    buyer_paid: Decimal = ZERO
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
            orders=self.orders + other.orders,
            gmv=self.gmv + other.gmv,
            buyer_paid_known=self.buyer_paid_known + other.buyer_paid_known,
            profit=self.profit + other.profit,
            contribution=self.contribution + other.contribution,
            buyer_paid=self.buyer_paid + other.buyer_paid,
            orders_missing_profit=self.orders_missing_profit + other.orders_missing_profit,
        )


@dataclass(frozen=True)
class SourceMatrix:
    lever: dict[tuple[str, str], CellStats]  # (product_id, price lever)
    ads: dict[str, CellStats]  # product_id -> ad-attributed overlay
    totals: dict[str, CellStats]  # product_id -> everything


def price_lever(promo_kinds: Iterable[PromoKind], voucher: Decimal, bundle: Decimal) -> PriceLever:
    if bundle > 0:
        return PriceLever.COMBO
    if any(k is not PromoKind.NONE for k in promo_kinds):
        return PriceLever.KHUYEN_MAI
    return PriceLever.VOUCHER if voucher > 0 else PriceLever.KHONG_UU_DAI


def _cell(pairs: list[tuple[OrderLine, ProfitBreakdown]]) -> CellStats:
    known = all(pb.profit is not None for _, pb in pairs)
    return CellStats(
        orders=1,
        gmv=sum((ln.order_value for ln, _ in pairs), ZERO),
        buyer_paid=sum((pb.buyer_paid for _, pb in pairs), ZERO),
        buyer_paid_known=sum((pb.buyer_paid for _, pb in pairs), ZERO) if known else ZERO,
        profit=sum((pb.profit or ZERO for _, pb in pairs), ZERO) if known else ZERO,
        contribution=sum((pb.contribution or ZERO for _, pb in pairs), ZERO) if known else ZERO,
        orders_missing_profit=0 if known else 1,
    )


def build_source_matrix(pairs: Iterable[tuple[OrderLine, ProfitBreakdown]]) -> SourceMatrix:
    groups: dict[tuple[str, str], list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        groups[(ln.order_id, ln.product_id)].append((ln, pb))

    lever: dict[tuple[str, str], CellStats] = {}
    ads: dict[str, CellStats] = {}
    totals: dict[str, CellStats] = {}
    empty = CellStats()
    for (_, product), grp in groups.items():
        cell = _cell(grp)
        lev = price_lever(
            (ln.promo_kind for ln, _ in grp),
            sum((ln.shop_voucher_share for ln, _ in grp), ZERO),
            sum((ln.bundle_discount for ln, _ in grp), ZERO),
        ).value
        lever[(product, lev)] = lever.get((product, lev), empty).plus(cell)
        totals[product] = totals.get(product, empty).plus(cell)
        if any(ln.ad_attributed for ln, _ in grp):
            ads[product] = ads.get(product, empty).plus(cell)

    matrix = SourceMatrix(lever, ads, totals)
    assert_additive(matrix)
    return matrix


def _sum(cells: Iterable[CellStats]) -> CellStats:
    out = CellStats()
    for c in cells:
        out = out.plus(c)
    return out


def assert_additive(matrix: SourceMatrix) -> None:
    """Both dimensions must equal the totals per product and overall (raises, never strips)."""
    for name, dim in (("lever", matrix.lever),):
        per_product: dict[str, CellStats] = {}
        for (product, _), cell in dim.items():
            per_product[product] = per_product.get(product, CellStats()).plus(cell)
        if per_product != matrix.totals:
            raise AdditivityError(f"{name} dimension does not sum to the totals")
    if _sum(matrix.lever.values()) != _sum(matrix.totals.values()):
        raise AdditivityError("lever dimension does not sum to the grand total")
    for product, cell in matrix.ads.items():
        total = matrix.totals.get(product, CellStats())
        if cell.orders > total.orders:
            raise AdditivityError("ads overlay exceeds the product total")
