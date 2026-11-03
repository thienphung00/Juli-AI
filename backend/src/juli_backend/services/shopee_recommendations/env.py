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
from typing import TYPE_CHECKING

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.floor import FloorInputs, FloorResult, compute_floor
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.order_profit import OrderLine, SkuCost
from juli_backend.services.shopee_profit.shop_profit import ProductProfit

if TYPE_CHECKING:
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
    #: product id -> why it may not get a new card (an open plan / a mega_sale window).
    locked: dict[str, str] = field(default_factory=dict)
    #: usage rate u of the shop's comparable past vouchers (None = unknown -> default 1, flagged)
    usage_rate: Decimal | None = None
    calibration: Mapping[tuple[str, str], CalibrationState] = field(default_factory=dict)
    acceptance: AcceptanceStats | None = None
    sim: SimPriors | None = None
    _floor_cache: dict[str, dict[str, FloorResult]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ rules / targets
    @property
    def month(self) -> str:
        return f"{self.as_of.year:04d}-{self.as_of.month:02d}"

    @property
    def rules(self):  # noqa: ANN201 - ProfitRules for the card window's month (Step 4)
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
    def item_ids(self) -> list[str]:
        """Products with confirmed order lines in the window, by GMV descending."""
        gmv: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for ln, _ in self.view.pairs:
            gmv[ln.product_id] += ln.order_value
        return [i for i, _ in sorted(gmv.items(), key=lambda kv: (-kv[1], kv[0]))]

    def stock(self, item_id: str) -> int | None:
        info = self.ctx.catalog.items.get(item_id)
        return None if info is None else info.stock

    def name(self, item_id: str) -> str:
        return self.view.names.get(item_id) or self.ctx.catalog.name(item_id)

    def product(self, item_id: str) -> ProductProfit | None:
        return self.view.profit.products.get(item_id)

    def orders_of(self, item_id: str) -> int:
        return len({ln.order_id for ln, _ in self.view.pairs if ln.product_id == item_id})

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
        return self.view.fees.schedule(item_id)

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
                if ln.actual_fees is not None and self.schedule(ln.product_id).formula_on(
                    ln.order_date
                ):
                    ln = replace(ln, actual_fees=None)
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
    def shop_gmv_30d(self) -> Decimal:
        return self.view.shop_gmv or ZERO

    @property
    def shop_orders_30d(self) -> int:
        return int(self.view.shop_orders or 0)

    def shop_chi_per_day(self) -> Decimal:
        """Marketing spend per day in the window: ads + voucher + khuyen mai + combo + commission
        (the same chi as the five numbers)."""
        pairs = self.view.pairs
        promo = sum((pb.promo_discount for _, pb in pairs), ZERO)
        voucher = sum((pb.voucher for _, pb in pairs), ZERO)
        combo = sum((pb.bundle for _, pb in pairs), ZERO)
        commission = sum(
            (pb.commission or ZERO for _, pb in pairs if pb.excluded_reason is None), ZERO
        )
        total = self.view.ads.total_spend + promo + voucher + combo + commission
        return total / Decimal(self.window_days)
