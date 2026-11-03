"""Stored order lines -> the ``services/shopee_profit`` waterfall, with the cost and fee rules.

- A line counts as *confirmed* when it has a payment time (contract 14): GMV, orders and AOV use
  every confirmed line, whatever became of the order; profit uses delivered / accepted-refund
  lines only (``OrderStatus.carries_profit``). A cancelled line that was paid keeps its GMV
  and is outside the profit base. A line never paid is not a confirmed order and is dropped.
- Costs (contract 13): imported SKU / product costs win; otherwise giá vốn = 1/3 of the SKU's list
  price, marked ``assumed``. Packaging falls back to 0, marked ``assumed``. The two sources are
  kept apart so every profit figure can state its assumed share.
- Fees (contract 4 / 10): the line's actual fees (order export) win; else the formula of the
  item's category valid on the order date. The per-order components are computed once on the whole
  order and split by value (``FeeFormula.split_per_order``) whatever each line's category rate.
- ``ad_attributed`` is unknown in the export (NULL); a line is never marked ad-attributed here, so
  the line-level ad split is empty and product ad spend comes from the ads report only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.shopee_analytics.fee_table import (
    DEFAULT_FIXED_FEE_RATE,
    RateChoice,
    choose_fixed_fee_rate,
    seed_schedule,
)
from juli_backend.services.shopee_analytics.rules_view import ProfitRules
from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    ProfitBreakdown,
    PromoKind,
    SkuCost,
    line_profit,
)

FALLBACK_COGS_RATIO = Decimal(1) / Decimal(3)
SRC_REAL = "real"
SRC_ASSUMED = "assumed"

_PROMO_KIND = {
    "discount": PromoKind.PROMOTION,
    "flash_sale": PromoKind.FLASH_SALE,
}
_STATUS = {s.value: s for s in OrderStatus}


@dataclass(frozen=True)
class RawLine:
    """A ``shopee_order_lines`` row, detached from the ORM (no buyer column exists)."""

    order_ref: str
    line_no: int
    ordered_at: datetime
    paid_at: datetime | None
    status: str
    item_id: str
    sku: str | None
    variation_sku: str | None
    qty: int
    original_price: Decimal
    deal_price: Decimal
    shop_voucher_share: Decimal
    bundle_discount: Decimal
    promo_kind: str
    voucher_code: str | None
    affiliate: bool
    commission: Decimal | None
    fee_fixed: Decimal | None
    fee_service: Decimal | None
    fee_payment: Decimal | None
    fee_other: Decimal | None
    buyer_shipping_fee: Decimal | None
    bank_promo: Decimal | None
    ad_attributed: bool | None


@dataclass(frozen=True)
class ShopLine:
    line: OrderLine
    ordered_on: date
    cost_key: str
    voucher_code: str | None = None

    @property
    def product_id(self) -> str:
        return self.line.product_id


def to_shop_lines(raw: Sequence[RawLine], catalog: Catalog) -> list[ShopLine]:
    """Confirmed (paid) lines, resolved to platform item ids; never-paid lines are dropped."""
    out: list[ShopLine] = []
    for r in raw:
        if r.paid_at is None or r.qty <= 0:
            continue
        item_id = catalog.resolve(r.item_id, r.sku, r.variation_sku)
        key = r.variation_sku or r.sku or item_id
        fees = [
            f for f in (r.fee_fixed, r.fee_service, r.fee_payment, r.fee_other) if f is not None
        ]
        out.append(
            ShopLine(
                line=OrderLine(
                    order_id=r.order_ref,
                    sku=key,
                    product_id=item_id,
                    order_date=r.ordered_at.date(),
                    qty=r.qty,
                    original_price=r.original_price,
                    deal_price=r.deal_price,
                    shop_voucher_share=r.shop_voucher_share,
                    bundle_discount=r.bundle_discount,
                    promo_kind=_PROMO_KIND.get(r.promo_kind, PromoKind.NONE),
                    ad_attributed=False,
                    affiliate=r.affiliate,
                    commission=r.commission if r.affiliate else None,
                    actual_fees=sum(fees, ZERO) if fees else None,
                    buyer_shipping_fee=r.buyer_shipping_fee,
                    bank_promo=r.bank_promo,
                    status=_STATUS.get(r.status, OrderStatus.DELIVERED),
                ),
                ordered_on=r.ordered_at.date(),
                cost_key=key,
                voucher_code=r.voucher_code,
            )
        )
    return out


@dataclass
class Costs:
    by_key: dict[str, SkuCost] = field(default_factory=dict)
    cogs_source: dict[str, str] = field(default_factory=dict)
    packaging_source: dict[str, str] = field(default_factory=dict)
    list_price: dict[str, Decimal] = field(default_factory=dict)

    def cogs_is_real(self, key: str) -> bool:
        return self.cogs_source.get(key) == SRC_REAL


def resolve_costs(lines: Sequence[ShopLine], rules: ProfitRules) -> Costs:
    """One cost per cost key: imported value, else 1/3 of the newest list price (assumed)."""
    newest: dict[str, ShopLine] = {}
    for sl in lines:
        prev = newest.get(sl.cost_key)
        if prev is None or sl.ordered_on >= prev.ordered_on:
            newest[sl.cost_key] = sl
    costs = Costs()
    for key, sl in newest.items():
        ln = sl.line
        costs.list_price[key] = ln.original_price
        cogs = rules.sku_cost.get(key)
        if cogs is None:
            cogs = rules.product_cost.get(ln.product_id)
        cogs_src = SRC_REAL
        if cogs is None:
            cogs, cogs_src = to_dong(ln.original_price * FALLBACK_COGS_RATIO), SRC_ASSUMED
        pack = rules.packaging_by_key.get(key)
        if pack is None:
            pack = rules.packaging_by_key.get(ln.product_id)
        pack_src = SRC_REAL
        if pack is None:
            pack, pack_src = ZERO, SRC_ASSUMED
        costs.by_key[key] = SkuCost(key, cogs, pack)
        costs.cogs_source[key] = cogs_src
        costs.packaging_source[key] = pack_src
    return costs


@dataclass
class FeeContext:
    """Per item: the fixed-fee rate and where it came from, and the schedule built from it."""

    rate_by_item: dict[str, RateChoice] = field(default_factory=dict)
    schedule_by_item: dict[str, FeeSchedule] = field(default_factory=dict)
    default_schedule: FeeSchedule = field(
        default_factory=lambda: seed_schedule(DEFAULT_FIXED_FEE_RATE)
    )

    def schedule(self, item_id: str) -> FeeSchedule:
        return self.schedule_by_item.get(item_id, self.default_schedule)

    def rate(self, item_id: str) -> RateChoice:
        return self.rate_by_item.get(item_id) or RateChoice(
            DEFAULT_FIXED_FEE_RATE, "default_assumed", None
        )


def build_fee_context(
    item_ids: Sequence[str],
    catalog: Catalog,
    db_schedules: Mapping[str, FeeSchedule] | None = None,
) -> FeeContext:
    ctx = FeeContext()
    for item_id in dict.fromkeys(item_ids):
        info = catalog.items.get(item_id)
        choice = choose_fixed_fee_rate(info.category_path if info else None, catalog.name(item_id))
        ctx.rate_by_item[item_id] = choice
        db = (db_schedules or {}).get(item_id)
        ctx.schedule_by_item[item_id] = db if db is not None else seed_schedule(choice.rate)
    return ctx


def profit_pairs(
    lines: Sequence[ShopLine], costs: Costs, fees: FeeContext
) -> list[tuple[OrderLine, ProfitBreakdown]]:
    """Waterfall of every line (input order kept). Per-order fee components are computed once
    per order from the order's own lines, whatever the category rates of its items."""
    by_order: dict[str, list[int]] = defaultdict(list)
    for i, sl in enumerate(lines):
        if sl.line.actual_fees is None and sl.line.status.carries_profit:
            by_order[sl.line.order_id].append(i)
    shares: dict[int, Mapping[str, Decimal]] = {}
    for idxs in by_order.values():
        first = lines[idxs[0]].line
        formula = fees.schedule(first.product_id).formula_on(first.order_date)
        if formula is None:
            continue
        parts = formula.split_per_order([lines[i].line for i in idxs])
        shares.update(zip(idxs, parts, strict=True))
    return [
        (
            sl.line,
            line_profit(
                sl.line,
                costs.by_key.get(sl.cost_key),
                schedule=fees.schedule(sl.line.product_id),
                per_order_fees=shares.get(i),
            ),
        )
        for i, sl in enumerate(lines)
    ]


@dataclass(frozen=True)
class CostCoverage:
    """Shares of the profit base (buyer_paid of delivered / accepted-refund lines) by where the
    giá vốn came from (contract 13). ``unknown`` = a cost input is still missing."""

    base: Decimal
    real: Decimal
    assumed: Decimal
    unknown: Decimal
    packaging_assumed: Decimal

    def pct(self, part: Decimal) -> Decimal | None:
        return pct_points(safe_div(part, self.base))

    def json(self) -> dict[str, object]:
        return {
            "net_revenue": float(self.base),
            "real_pct": _f(self.pct(self.real)),
            "assumed_pct": _f(self.pct(self.assumed)),
            "unknown_pct": _f(self.pct(self.unknown)),
            "packaging_assumed_pct": _f(self.pct(self.packaging_assumed)),
            "label": "giá vốn giả định (1/3 giá niêm yết) khi chưa nhập giá vốn thật",
        }


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def cost_coverage(pairs: Sequence[tuple[OrderLine, ProfitBreakdown]], costs: Costs) -> CostCoverage:
    base = real = assumed = unknown = pack = ZERO
    for ln, pb in pairs:
        if pb.excluded_reason is not None:
            continue
        paid = pb.revenue
        base += paid
        if pb.contribution is None:
            unknown += paid
        elif costs.cogs_is_real(ln.sku):
            real += paid
        else:
            assumed += paid
        if costs.packaging_source.get(ln.sku) != SRC_REAL:
            pack += paid
    return CostCoverage(base, real, assumed, unknown, pack)
