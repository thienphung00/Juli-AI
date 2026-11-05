"""Stored order lines -> the ``services/shopee_profit`` waterfall, with the cost and fee rules.

- A line counts as *confirmed* when it has a payment time (contract 14): GMV, orders and AOV use
  every confirmed line, whatever became of the order; profit uses delivered / accepted-refund
  lines only (``OrderStatus.carries_profit``). A cancelled line that was paid keeps its GMV
  and is outside the profit base. A line never paid is not a confirmed order and is dropped.
- Costs (contract 13): imported SKU / product costs win; otherwise giá vốn = 1/3 of the SKU's list
  price, marked ``assumed``. Packaging falls back to 0, marked ``assumed``. The two sources are
  kept apart so every profit figure can state its assumed share.
- Pack and bill of materials (P91 D-12): a SKU's giá vốn is the cost of ONE item. A variation that
  holds N items ("Combo 3 hộp": the seller's ``pack_count``, else read from the name, else 1) costs
  N x that; a listing with a ``pack_components`` rule costs Σ component cost x quantity. Such a
  line's cost key carries the pack (``G500001×3``, ``bom:<item>:<variation>``), so the variations
  that share a SKU are costed, grouped and floored apart. Packaging is per order line, not x N.
- Fees (contract 4 / 10): the order's income-export row (P91 D-12) wins - every actual fee, the
  shipping and the other costs the formula never sees, split over the lines by value; else the
  line's actual fees (order export); else the formula of the item's category valid on the order
  date. The per-order components are computed once on the whole order and split by value
  (``FeeFormula.split_per_order``) whatever each line's category rate.
- VAT (P91 D-12): ``vat`` on a line carries the shop flags and the SKU's rate; the profit is
  labelled before VAT until the seller says whether the prices include it.
- ``ad_attributed`` is unknown in the export (NULL); a line is never marked ad-attributed here, so
  the line-level ad split is empty and product ad spend comes from the ads report only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
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
from juli_backend.services.shopee_profit.income import IncomeOrder, split_income
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    ProfitBreakdown,
    PromoKind,
    SkuCost,
    line_profit,
)
from juli_backend.services.shopee_profit.pack import (
    SOURCE_NAME,
    SOURCE_SET,
    SOURCE_SINGLE,
    Component,
    components_cost,
    pack_count_from_name,
)
from juli_backend.services.shopee_profit.vat import VatTreatment

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
    #: P91 D-9: the KOL of an affiliate-marked line (migration 118); all None otherwise.
    kol_key: str | None = None
    kol_handle: str | None = None
    affiliate_channel: str | None = None
    affiliate_campaign_type: str | None = None
    affiliate_mcn: bool | None = None
    #: Migration 119. The stored variation (``''`` = item level) and the export's variation name.
    variation_id: str = ""
    variation_name: str | None = None


@dataclass(frozen=True)
class KolTag:
    """Who sold an affiliate line, from the SellerConversionReport (public handle only)."""

    key: str
    handle: str
    channel: str | None = None
    campaign_type: str | None = None
    mcn: bool | None = None


@dataclass(frozen=True)
class ShopLine:
    line: OrderLine
    ordered_on: date
    #: The COST key (``OrderLine.sku``): the SKU text, with the pack when it is not 1.
    cost_key: str
    voucher_code: str | None = None
    kol: KolTag | None = None
    #: The SKU text without the pack, the item's scope (``item`` or ``item:variation``).
    base_key: str = ""
    scope: str = ""
    pack_count: int = 1
    pack_source: str = SOURCE_SINGLE
    components: tuple[Component, ...] = ()
    vat: VatTreatment | None = None

    @property
    def product_id(self) -> str:
        return self.line.product_id


def _variation_of(catalog: Catalog, item_id: str, r: RawLine) -> tuple[str, str | None]:
    """(variation id, variation name) of a line. The stored variation wins; a line stored before
    the catalogue knew its SKU is looked up among the item's variations by SKU and name."""
    info = catalog.items.get(item_id)
    variations = info.variations if info else ()
    if r.variation_id:
        found = next((v for v in variations if v.variation_id == r.variation_id), None)
        return r.variation_id, r.variation_name or (found.name if found else None)
    wanted = {c for c in (r.variation_sku, r.sku) if c}
    named = [
        v
        for v in variations
        if v.seller_sku in wanted
        and r.variation_name
        and (v.name or "").strip().casefold() == r.variation_name.strip().casefold()
    ]
    only = [v for v in variations if v.seller_sku in wanted]
    pick = named[0] if named else (only[0] if len(only) == 1 else None)
    if pick is None and len(variations) == 1:
        # A listing without variations still has one model; the catalogue often lacks its seller
        # SKU, so the line could not be matched by SKU. Its only model is the line's.
        pick = variations[0]
    if pick is None:
        return "", r.variation_name
    return pick.variation_id, r.variation_name or pick.name


def _first_present(*values: Decimal | None) -> Decimal | None:
    return next((v for v in values if v is not None), None)


def to_shop_lines(
    raw: Sequence[RawLine],
    catalog: Catalog,
    rules: ProfitRules | None = None,
    income: Mapping[str, IncomeOrder] | None = None,
) -> list[ShopLine]:
    """Confirmed (paid) lines, resolved to platform item ids; never-paid lines are dropped.

    ``rules`` carries the pack counts, bills of materials and VAT; ``income`` the income-export
    rows by ``order_ref`` (each order's actuals are split over its lines by value)."""
    rules = rules or ProfitRules()
    out: list[ShopLine] = []
    for r in raw:
        if r.paid_at is None or r.qty <= 0:
            continue
        item_id = catalog.resolve(r.item_id, r.sku, r.variation_sku)
        variation_id, variation_name = _variation_of(catalog, item_id, r)
        scope = f"{item_id}:{variation_id}" if variation_id else item_id
        base = r.variation_sku or r.sku or item_id
        components = rules.pack_components.get(scope) or rules.pack_components.get(item_id) or ()
        if scope in rules.pack_count:
            pack, source = rules.pack_count[scope], SOURCE_SET
        elif (named := pack_count_from_name(variation_name)) is not None:
            pack, source = named, SOURCE_NAME
        else:
            pack, source = 1, SOURCE_SINGLE
        if components:
            key = f"bom:{scope}"
        else:
            key = base if pack == 1 else f"{base}×{pack}"
        fees = [
            f for f in (r.fee_fixed, r.fee_service, r.fee_payment, r.fee_other) if f is not None
        ]
        rate = _first_present(rules.vat_rate.get(scope), rules.vat_rate.get(base))
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
                kol=(
                    KolTag(
                        r.kol_key,
                        r.kol_handle or "",
                        r.affiliate_channel,
                        r.affiliate_campaign_type,
                        r.affiliate_mcn,
                    )
                    if r.affiliate and r.kol_key
                    else None
                ),
                base_key=base,
                scope=scope,
                pack_count=pack,
                pack_source=source,
                components=tuple(components),
                vat=VatTreatment(rules.prices_include_vat, rules.cost_includes_vat, rate),
            )
        )
    return attach_income(out, income) if income else out


def attach_income(lines: list[ShopLine], income: Mapping[str, IncomeOrder]) -> list[ShopLine]:
    """Give each line its share of its order's income-export row, split by the lines' value."""
    by_order: dict[str, list[int]] = defaultdict(list)
    for i, sl in enumerate(lines):
        if sl.line.order_id in income:
            by_order[sl.line.order_id].append(i)
    out = list(lines)
    for order_id, idxs in by_order.items():
        shares = split_income(income[order_id], [lines[i].line.buyer_paid for i in idxs])
        for i, share in zip(idxs, shares, strict=True):
            out[i] = replace(lines[i], line=replace(lines[i].line, income=share))
    return out


@dataclass
class Costs:
    by_key: dict[str, SkuCost] = field(default_factory=dict)
    cogs_source: dict[str, str] = field(default_factory=dict)
    packaging_source: dict[str, str] = field(default_factory=dict)
    list_price: dict[str, Decimal] = field(default_factory=dict)
    #: Per cost key: single items in one sold unit, and where that count came from.
    pack_count: dict[str, int] = field(default_factory=dict)
    pack_source: dict[str, str] = field(default_factory=dict)
    #: Cost keys costed from a bill of materials.
    bom: set[str] = field(default_factory=set)

    def cogs_is_real(self, key: str) -> bool:
        return self.cogs_source.get(key) == SRC_REAL


def _unit_cost(sl: ShopLine, rules: ProfitRules) -> Decimal | None:
    """The cost of ONE item of the line's SKU: this variation's own, else the SKU's, else the
    product's."""
    ln = sl.line
    return _first_present(
        rules.sku_cost.get(sl.scope) if sl.scope else None,
        rules.sku_cost.get(sl.base_key or sl.cost_key),
        rules.product_cost.get(ln.product_id),
    )


def resolve_costs(lines: Sequence[ShopLine], rules: ProfitRules) -> Costs:
    """One cost per cost key: imported value (x pack, or Σ bill of materials), else 1/3 of the
    newest list price (assumed)."""
    newest: dict[str, ShopLine] = {}
    for sl in lines:
        prev = newest.get(sl.cost_key)
        if prev is None or sl.ordered_on >= prev.ordered_on:
            newest[sl.cost_key] = sl
    costs = Costs()
    for key, sl in newest.items():
        ln = sl.line
        costs.list_price[key] = ln.original_price
        cogs: Decimal | None
        if sl.components:
            cogs = components_cost(
                sl.components,
                {c.sku: v for c in sl.components if (v := rules.sku_cost.get(c.sku)) is not None},
            )
            costs.bom.add(key)
        else:
            unit = _unit_cost(sl, rules)
            cogs = None if unit is None else unit * sl.pack_count
        cogs_src = SRC_REAL
        if cogs is None:
            cogs, cogs_src = to_dong(ln.original_price * FALLBACK_COGS_RATIO), SRC_ASSUMED
        pack = _first_present(
            rules.packaging_by_key.get(sl.scope) if sl.scope else None,
            rules.packaging_by_key.get(sl.base_key or key),
            rules.packaging_by_key.get(ln.product_id),
        )
        pack_src = SRC_REAL
        if pack is None:
            pack, pack_src = ZERO, SRC_ASSUMED
        costs.by_key[key] = SkuCost(key, cogs, pack, vat=sl.vat)
        costs.cogs_source[key] = cogs_src
        costs.packaging_source[key] = pack_src
        costs.pack_count[key] = sl.pack_count
        costs.pack_source[key] = sl.pack_source
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
        if sl.line.actual_fees is None and sl.line.income is None and sl.line.status.carries_profit:
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
                vat=sl.vat,
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
    #: Revenue of pack lines (pack > 1) whose count was read from the variation name, not set.
    pack_from_name: Decimal = ZERO

    def pct(self, part: Decimal) -> Decimal | None:
        return pct_points(safe_div(part, self.base))

    def json(self) -> dict[str, object]:
        return {
            "net_revenue": float(self.base),
            "real_pct": _f(self.pct(self.real)),
            "assumed_pct": _f(self.pct(self.assumed)),
            "unknown_pct": _f(self.pct(self.unknown)),
            "packaging_assumed_pct": _f(self.pct(self.packaging_assumed)),
            "pack_from_name_pct": _f(self.pct(self.pack_from_name)),
            "label": "giá vốn giả định (1/3 giá niêm yết) khi chưa nhập giá vốn thật",
        }


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def cost_coverage(pairs: Sequence[tuple[OrderLine, ProfitBreakdown]], costs: Costs) -> CostCoverage:
    base = real = assumed = unknown = pack = named = ZERO
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
        if costs.pack_source.get(ln.sku) == SOURCE_NAME and costs.pack_count.get(ln.sku, 1) > 1:
            named += paid
    return CostCoverage(base, real, assumed, unknown, pack, named)


@dataclass(frozen=True)
class IncomeCoverage:
    """How much of the profit base is costed from the income export's actuals: the orders
    (delivered / accepted-refund) that have an income row, by count and by revenue."""

    orders: int
    with_income: int
    revenue: Decimal
    revenue_with_income: Decimal

    @property
    def orders_pct(self) -> Decimal | None:
        return pct_points(safe_div(Decimal(self.with_income), Decimal(self.orders)))

    @property
    def revenue_pct(self) -> Decimal | None:
        return pct_points(safe_div(self.revenue_with_income, self.revenue))

    def json(self) -> dict[str, object]:
        return {
            "orders": self.orders,
            "with_income": self.with_income,
            "orders_pct": _f(self.orders_pct),
            "revenue_pct": _f(self.revenue_pct),
            "label": "đơn có file Doanh thu (phí thực) so với đơn tính phí theo công thức",
        }


def income_coverage(pairs: Sequence[tuple[OrderLine, ProfitBreakdown]]) -> IncomeCoverage:
    orders: set[str] = set()
    covered: set[str] = set()
    revenue = with_income = ZERO
    for ln, pb in pairs:
        if pb.excluded_reason is not None:
            continue
        orders.add(ln.order_id)
        revenue += pb.revenue
        if ln.income is not None:
            covered.add(ln.order_id)
            with_income += pb.revenue
    return IncomeCoverage(len(orders), len(covered), revenue, with_income)
