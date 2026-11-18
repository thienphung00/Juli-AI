"""The data a generator reads, as one detached object (no database below this line).

``RecoEnv`` wraps the analytics :class:`PeriodView` of the history window (the last
``HISTORY_DAYS`` days ending on ``as_of``) with the few things the analytics do not carry:
the live ads / voucher settings, the products locked by another plan, the shop's own
acceptance / calibration state and the simulation priors. Generators and evaluators are pure
functions of an ``RecoEnv`` -- the same environment always gives the same cards, and the
what-if endpoint rebuilds the same environment to recompute a card with new inputs.

Everything about money goes through ``services/shopee_profit``; helpers here only pick lines,
costs, floors and schedules out of the view.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.metrics import ShopMetrics
from juli_backend.services.shopee_profit.fees import (
    FeeBase,
    FeeComponent,
    FeeKind,
    FeeSchedule,
)
from juli_backend.services.shopee_profit.floor import FloorInputs, FloorResult, compute_floor
from juli_backend.services.shopee_profit.income import FEE_SERVICE
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    ProfitBreakdown,
    SkuCost,
    counts_in_sales,
)
from juli_backend.services.shopee_profit.shop_profit import ProductProfit
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.listing import Listing
from juli_backend.services.shopee_recommendations.model import DiscountResponse

if TYPE_CHECKING:
    from juli_backend.services.shopee_analytics.kol import KolPool
    from juli_backend.services.shopee_analytics.rules_view import ProfitRules
    from juli_backend.services.shopee_recommendations.learning import (
        AcceptanceStats,
        CalibrationState,
    )
    from juli_backend.services.shopee_recommendations.sim_priors import SimPriors


@dataclass(frozen=True)
class CampaignSetting:
    """An ads campaign's live settings (``ads_campaign_daily`` extra, latest day)."""

    key: str
    name: str
    daily_budget: Decimal | None = None
    roas_target: Decimal | None = None
    purpose: str | None = None
    campaign_id: str | None = None
    #: P97 D85.17: times the ROAS target changed in the 7 days up to the window's last day
    roas_changes_7d: int = 0
    #: P100 B.15: the campaign's days of the window, oldest first: (spend, that day's daily
    #: budget; None = không giới hạn) -- is the budget holding it back?
    days: tuple[tuple[Decimal, Decimal | None], ...] = ()


@dataclass(frozen=True)
class VoucherSetting:
    """A live voucher's settings (``voucher_settings``)."""

    voucher_id: str
    name: str
    value: Decimal | None = None  # đ off
    pct: Decimal | None = None  # percent points
    max_value: Decimal | None = None
    min_spend: Decimal | None = None
    usage_limit: int | None = None
    starts_at: str | None = None
    ends_at: str | None = None


@dataclass
class RecoEnv:
    ctx: ShopContext
    view: PeriodView
    as_of: date
    campaigns: dict[str, CampaignSetting] = field(default_factory=dict)
    vouchers: list[VoucherSetting] = field(default_factory=list)
    #: P100 B.15: share of the window's placed orders never confirmed (Tổng quan placed vs
    #: confirmed, ``loaders.load_cancel_rate``); None = unknown (ads orders stay placed orders)
    cancel_rate: Decimal | None = None
    #: product id -> why it may not get a new card (an open plan / a mega_sale window).
    locked: dict[str, str] = field(default_factory=dict)
    #: usage rate u of the shop's comparable past vouchers (None = unknown -> default 1, flagged)
    usage_rate: Decimal | None = None
    calibration: Mapping[tuple[str, str], CalibrationState] = field(default_factory=dict)
    #: F2: the stored funnel rows of the last 60 days (the adaptive window's widest), and today
    #: (None = no staleness check); the builder's base reads them
    funnel_history: Any = None
    today: date | None = None
    #: F6: the calibration pooled across the real Shopee shops (rung 3 of the uplift ladder)
    pooled_calibration: Mapping[tuple[str, str], CalibrationState] = field(default_factory=dict)
    acceptance: AcceptanceStats | None = None
    sim: SimPriors | None = None
    #: product id -> the listing as stored (newest snapshot + keyword key list + market numbers)
    listings: dict[str, Listing] = field(default_factory=dict)
    #: the seller's "Từ không được dùng" (Quy tắc); the listing proposals never contain one
    banned_terms: tuple[str, ...] = ()
    #: P91 D-9: the KOL facts the KOL cards forecast from (``kol_cards``); None = not loaded
    kol: KolPool | None = None
    #: P92 B-3: how this product's (and the shop's other products') orders answered a price cut in
    #: the shop's own history; empty until the builder loads it (``shopee_builder.response``).
    response_by_item: dict[str, DiscountResponse] = field(default_factory=dict)
    response_shop: DiscountResponse | None = None
    #: P100 Part S: products whose every variation a member stopped ("Ngừng theo dõi"): no new card
    stock_stopped: frozenset[str] = frozenset()
    _floor_cache: dict[str, dict[str, FloorResult]] = field(default_factory=dict, repr=False)
    _schedule_cache: dict[str, FeeSchedule] = field(default_factory=dict, repr=False)
    _service_rate: Decimal | None = field(default=None, repr=False)
    #: not an init field, so ``dataclasses.replace`` (a copy with other pairs) starts it afresh
    _sales_pairs: list[tuple[OrderLine, ProfitBreakdown]] | None = field(
        default=None, init=False, repr=False
    )

    # ------------------------------------------------------------------ rules / targets
    @property
    def month(self) -> str:
        return f"{self.as_of.year:04d}-{self.as_of.month:02d}"

    @property
    def rules(self) -> ProfitRules:  # the card window's month (Step 4)
        return self.ctx.rules.for_month(self.month)

    @property
    def window_days(self) -> int:
        return self.view.window.days

    @property
    def margin_target_rate(self) -> Decimal | None:
        t = self.rules.target("margin_pct")
        return None if t is None else t / 100

    @property
    def daily_cap(self) -> Decimal | None:
        return self.rules.target("daily_marketing_cap")

    # ----------------------------------------------------------------------- products
    @property
    def sales_pairs(self) -> list[tuple[OrderLine, ProfitBreakdown]]:
        """The window's pairs that count in đơn / GMV / AOV (``counts_in_sales``: a returned
        order is no sale, owner D2). Every sales signal reads these; the profit baseline
        (``lines_for``, floors, fee rates) keeps every line, so a return's fees stay a cost."""
        if self._sales_pairs is None:
            self._sales_pairs = [(ln, pb) for ln, pb in self.view.pairs if counts_in_sales(ln)]
        return self._sales_pairs

    @property
    def excluded(self) -> dict[str, str]:
        """P92 B-1: item id -> reason, listings that get no card and no builder entry."""
        return self.view.excluded

    def item_ids(self) -> list[str]:
        """Products with confirmed order lines in the window, by GMV descending (excluded
        listings left out)."""
        gmv: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for ln, _ in self.sales_pairs:
            if ln.product_id not in self.excluded:
                gmv[ln.product_id] += ln.order_value
        return [i for i, _ in sorted(gmv.items(), key=lambda kv: (-kv[1], kv[0]))]

    def listing_item_ids(self) -> list[str]:
        """Products the listing audit may look at: every product with confirmed GMV in the
        window, from the order lines or from Shopee's own product totals (a product with views
        but few order lines is exactly the one a better title helps), by GMV descending."""
        gmv: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for ln, _ in self.sales_pairs:
            if ln.product_id not in self.excluded:
                gmv[ln.product_id] += ln.order_value
        for item, (total, _orders) in self.view.data.product_flows.totals.items():
            if item not in self.excluded:
                gmv[item] = max(gmv[item], total)
        return [i for i, _ in sorted(gmv.items(), key=lambda kv: (-kv[1], kv[0]))]

    def stock(self, item_id: str) -> int | None:
        info = self.ctx.catalog.items.get(item_id)
        return None if info is None else info.stock

    def name(self, item_id: str) -> str:
        return self.view.names.get(item_id) or self.ctx.catalog.name(item_id)

    def product(self, item_id: str) -> ProductProfit | None:
        return self.view.profit.products.get(item_id)

    def orders_of(self, item_id: str) -> int:
        return len({ln.order_id for ln, _ in self.sales_pairs if ln.product_id == item_id})

    def skus_of(self, item_id: str) -> list[str]:
        return sorted({ln.sku for ln, _ in self.view.pairs if ln.product_id == item_id})

    def list_price(self, sku: str) -> Decimal | None:
        return self.view.costs.list_price.get(sku)

    def current_price(self, sku: str) -> Decimal | None:
        """Newest deal price of the SKU in the window (what buyers paid per unit)."""
        newest: OrderLine | None = None
        for ln, _ in self.view.pairs:
            if ln.sku == sku and (newest is None or ln.order_date >= newest.order_date):
                newest = ln
        return None if newest is None else newest.deal_price

    def setting_for(self, campaign_key: str | None) -> CampaignSetting | None:
        """Live settings of a report campaign: by its key, else by its title."""
        if not campaign_key:
            return None
        hit = self.campaigns.get(campaign_key)
        if hit is not None:
            return hit
        alloc = next((c for c in self.view.ads.campaigns if c.key == campaign_key), None)
        return None if alloc is None else self.campaigns.get(alloc.name)

    # ---------------------------------------------------------------------- order lines
    def schedule(self, item_id: str) -> FeeSchedule:
        """The item's fee formula versions, with the shop's phí dịch vụ (Voucher / Freeship Xtra)
        added when the shop pays it. ``shopee_vn_non_mall`` leaves it out (it applies only to an
        enrolled shop), so a re-priced line whose reported fees ``lines_for`` dropped was charged
        no service fee and every Δ fee of a price change came out too small. The rate is the
        one the shop's own income rows show (``service_fee_rate``); a formula that already
        carries the component (a ``platform_fee_formulas`` row) is kept as it is."""
        cached = self._schedule_cache.get(item_id)
        if cached is not None:
            return cached
        base = self.view.fees.schedule(item_id)
        rate = self.service_fee_rate
        if rate is not None and rate > 0:
            component = FeeComponent(
                FEE_SERVICE, FeeKind.PCT, FeeBase.ITEM_AFTER_SELLER_PROMO, rate=rate
            )
            base = FeeSchedule(
                tuple(
                    v
                    if any(c.code == FEE_SERVICE for c in v.components)
                    else replace(v, components=(*v.components, component))
                    for v in base.versions
                )
            )
        self._schedule_cache[item_id] = base
        return base

    @property
    def service_fee_rate(self) -> Decimal | None:
        """Phí dịch vụ ÷ the item value after seller promotions (its fee base) over the window's
        lines that carry the income export; ``None`` when no line does or none was charged it
        (the shop is not enrolled)."""
        if self._service_rate is not None:
            return self._service_rate if self._service_rate > 0 else None
        fee = base = ZERO
        for ln, _ in self.view.pairs:
            if ln.income is None:
                continue
            fee += sum((a for code, a in ln.income.fees if code == FEE_SERVICE), ZERO)
            base += max(ln.item_after_seller_promo, ZERO)
        rate = (fee / base).quantize(Decimal("0.0001")) if fee > 0 and base > 0 else ZERO
        self._service_rate = rate
        return rate if rate > 0 else None

    @property
    def costs(self) -> Mapping[str, SkuCost]:
        return self.view.costs.by_key

    def lines_for(self, item_ids: Sequence[str] | None) -> list[OrderLine]:
        """Whole orders (every line) that contain any of ``item_ids`` (None = every order).

        Reported fees are dropped where a fee formula exists, so the baseline and every
        scenario are recomputed by the same formula (like for like); a line whose item has no
        formula keeps its reported fee.
        """
        wanted = None if item_ids is None else set(item_ids)
        orders: dict[str, list[OrderLine]] = defaultdict(list)
        hit: set[str] = set()
        for ln, _ in self.view.pairs:
            orders[ln.order_id].append(ln)
            if wanted is None or ln.product_id in wanted:
                hit.add(ln.order_id)
        out: list[OrderLine] = []
        for oid, lines in orders.items():
            if oid not in hit:
                continue
            for ln in lines:
                if (ln.actual_fees is not None or ln.income is not None) and self.schedule(
                    ln.product_id
                ).formula_on(ln.order_date):
                    # The formula replaces the reported fees, but the affiliate commission the
                    # income row stated stays: dropping it left an affiliate line with no
                    # commission and the whole line's profit unknown.
                    commission = ln.commission
                    if commission is None and ln.income is not None and ln.affiliate:
                        commission = ln.income.commission
                    ln = replace(ln, actual_fees=None, income=None, commission=commission)
                out.append(ln)
        return out

    # ------------------------------------------------------------------------- floors
    def floors(self, item_id: str) -> dict[str, FloorResult]:
        """Per SKU of the item: absolute / operating floor (contract 6), same inputs as the
        product page (``shopee_analytics.product.sku_waterfall``)."""
        cached = self._floor_cache.get(item_id)
        if cached is not None:
            return cached
        view, rules = self.view, self.rules
        pp = self.product(item_id)
        spend = view.ads.product_spend.get(item_id, ZERO)
        paid_total = pp.buyer_paid if pp else ZERO
        formula = view.fees.schedule(item_id).formula_on(self.as_of)
        out: dict[str, FloorResult] = {}
        if formula is None:
            self._floor_cache[item_id] = out
            return out
        default_cap = rules.default_max_discount_pct
        for sku in self.skus_of(item_id):
            items = [
                (ln, pb)
                for ln, pb in view.pairs
                if ln.product_id == item_id and ln.sku == sku and pb.excluded_reason is None
            ]
            paid = sum((pb.revenue for _, pb in items), ZERO)
            commission = sum((pb.commission or ZERO for _, pb in items), ZERO)
            cost = view.costs.by_key.get(sku)
            ad_rate = (
                safe_div(spend * paid / paid_total, paid) if paid > 0 and paid_total > 0 else ZERO
            )
            cap = rules.max_discount_pct.get(sku)
            if cap is None:
                cap = rules.max_discount_pct.get(item_id, default_cap)
            margin = rules.target("margin_pct")
            out[sku] = compute_floor(
                FloorInputs(
                    list_price=view.costs.list_price.get(sku),
                    cogs=cost.cogs if cost else None,
                    packaging=cost.packaging if cost else None,
                    fixed_fee_per_order=formula.fixed_per_order,
                    platform_fee_rate=formula.pct_rate_on_buyer_paid,
                    ads_rate=ad_rate if ad_rate is not None else ZERO,
                    affiliate_rate=safe_div(commission, paid) if paid > 0 else ZERO,
                    target_margin_rate=None if margin is None else margin / 100,
                    seller_max_discount_rate=None if cap is None else cap / 100,
                )
            )
        self._floor_cache[item_id] = out
        return out

    def floor_price(self, item_id: str, sku: str) -> Decimal | None:
        """The floor a price must not go under: operating when known, else absolute."""
        f = self.floors(item_id).get(sku)
        if f is None:
            return None
        return f.operating_floor if f.operating_floor is not None else f.absolute_floor

    # ---------------------------------------------------------------- shop-level figures
    @property
    def metrics(self) -> ShopMetrics:
        """The window's core numbers (D85.2): the same read model as every analytics screen."""
        return self.view.metrics

    @property
    def shop_gmv_30d(self) -> Decimal:
        return self.metrics.gmv or ZERO

    @property
    def shop_orders_30d(self) -> int:
        return int(self.metrics.orders or 0)

    def shop_chi_per_day(self) -> Decimal:
        """Marketing spend per day in the window: ads + voucher + khuyen mai + combo + commission
        (the same chi as the five numbers: a returned order's discounts are no spend)."""
        pairs = self.sales_pairs
        promo = sum((pb.promo_discount for _, pb in pairs), ZERO)
        voucher = sum((pb.voucher for _, pb in pairs), ZERO)
        combo = sum((pb.bundle for _, pb in pairs), ZERO)
        commission = sum(
            (pb.commission or ZERO for _, pb in pairs if pb.excluded_reason is None), ZERO
        )
        total = self.view.ads.total_spend + promo + voucher + combo + commission
        return total / Decimal(self.window_days)


def voucher_takeup(
    lines: Sequence[OrderLine], min_spend: Decimal, known: Decimal | None
) -> Decimal | None:
    """Share of qualifying orders (basket >= ``min_spend``) that use a shop voucher.

    ``known`` = the usage rate of the shop's own past vouchers (when it has one it wins). Else
    it is measured from the shop's own order lines: qualifying orders carrying a shop voucher
    share / qualifying orders, once there are enough qualifying orders and the shop has used a
    voucher at all. None = unknown (the caller keeps the flagged default of 1).
    """
    if known is not None:
        return known
    values: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    used: dict[str, bool] = {}
    for ln in lines:
        if not counts_in_sales(ln):
            continue  # a returned order is no sale (owner D2)
        values[ln.order_id] += ln.order_value
        used[ln.order_id] = used.get(ln.order_id, False) or ln.shop_voucher_share > 0
    qualifying = [oid for oid, v in values.items() if v >= min_spend]
    if len(qualifying) < config.VOUCHER_TAKEUP_MIN_ORDERS or not any(used.values()):
        return None
    return Decimal(sum(1 for oid in qualifying if used[oid])) / len(qualifying)
