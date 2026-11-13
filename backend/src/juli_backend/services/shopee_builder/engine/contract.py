"""P98 / ADR-122: the data contract between the stored funnel, the per-family option builders and
the funnel engine. Written before the parallel waves so no wave changes another wave's shapes;
change it only
with the owner of every consumer (see ``fasttrack/contracts/p98-waves.md``).

Flow::

    shopee_analytics.funnel.load_funnel_base(...) -> FunnelBase    wave 2, read model (d.2-d.3)
    shopee_builder.engine_families.<family>(...)  -> OptionInput   wave 2, drivers / cost (d.6-d.10)
    shopee_builder.engine.run(base, option, seed) -> OptionResult  wave 1, scenarios (d.1, d.4, d.5)
    OptionResult.json()                           -> the card      wave 3 (option-result.ts)

Units: money in whole VND as ``Decimal``; counts as ``Decimal`` (a scaled or simulated order count
can be fractional inside the engine; the card rounds); rates as fractions (0.0882 = 8,82 %).
Pure: no I/O, no clock, no randomness outside ``engine.run``'s seeded generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

# -- the stored funnel ---------------------------------------------------------------------------

#: Source keys (ADR-122 d.3), as ``shopee_profit.flows.Flow`` plus the residual.
Source = Literal["the_san_pham_khac", "trang_shop", "live", "video", "lien_ket", "chenh_lech_nguon"]
SOURCES: tuple[Source, ...] = (
    "the_san_pham_khac",
    "trang_shop",
    "live",
    "video",
    "lien_ket",
    "chenh_lech_nguon",
)
#: Sources a listing lever (title / keyword / cover / price display) acts on: the search and
#: recommendation cards (Thẻ sản phẩm outside Trang shop).
CARD_SOURCES: tuple[Source, ...] = ("the_san_pham_khac",)
ALL_SOURCES: tuple[Source, ...] = SOURCES
#: The residual: orders Shopee assigns to no source; never carries views or clicks.
RESIDUAL: Source = "chenh_lech_nguon"


@dataclass(frozen=True)
class AdShare:
    """The "trong đó Quảng cáo" part of a source (only ``the_san_pham_khac`` has one): ad views,
    clicks, direct orders, direct GMV and spend over the window. Never added to the source.
    A field Shopee does not post for the scope is ``None`` (product rows carry spend and GMV only:
    there are no per-product daily ad views / clicks / orders); a consumer that needs a missing
    field treats the share as "no ad data". Shop ads orders / GMV are Shopee's placed-order ads
    figures, not the confirmed basis of the source rows."""

    views: Decimal | None
    clicks: Decimal | None
    orders: Decimal | None
    gmv: Decimal | None
    spend: Decimal | None


@dataclass(frozen=True)
class SourceFunnel:
    """One source over the window: sums, never daily averages. ``views`` / ``clicks`` are ``None``
    when the traffic tables have no rows for it (then CTR / CTOR are "chưa có dữ liệu"). ``orders``
    and ``gmv`` are ShopMetrics, scaled so the sources add up to the scope's totals exactly."""

    source: Source
    views: Decimal | None
    clicks: Decimal | None
    orders: Decimal
    gmv: Decimal
    profit: Decimal | None  # None = a giá vốn is missing ("chưa tính")
    ads: AdShare | None = None
    #: P99: the đơn of the days whose profit is known (``profit`` sums those days only), so
    #: profit per order = profit ÷ profit_orders
    profit_orders: Decimal = Decimal(0)

    @property
    def ctr(self) -> Decimal | None:
        if self.views is None or self.clicks is None or self.views <= 0:
            return None
        return self.clicks / self.views

    @property
    def ctor(self) -> Decimal | None:
        if self.clicks is None or self.clicks <= 0:
            return None
        return self.orders / self.clicks

    @property
    def aov(self) -> Decimal | None:
        return self.gmv / self.orders if self.orders > 0 else None


@dataclass(frozen=True)
class FunnelBase:
    """The "before" of an option (ADR-122 d.2): one scope over the window ending at the Tổng quan
    anchor. ``contribution_rate`` is the profit of one extra đồng of GMV at today's prices (fees,
    giá vốn share, VAT), used for an AOV change; ``None`` when a giá vốn is missing."""

    shop_id: str
    scope: Literal["shop", "products"]
    item_ids: tuple[str, ...]
    window_start: date
    window_end: date
    sources: tuple[SourceFunnel, ...]
    contribution_rate: Decimal | None
    #: "all-sources" when product × source rows are missing and one all-source funnel stands in
    source_detail: Literal["per_source", "all_sources"] = "per_source"
    #: P99: days of the window with a known profit / with any row ("trên N ngày có dữ liệu chi phí")
    profit_days: int = 0
    days: int = 0

    @property
    def window_days(self) -> int:
        return (self.window_end - self.window_start).days + 1

    def total(
        self,
        field_name: Literal["orders", "gmv", "views", "clicks", "profit", "profit_orders"],
    ) -> Decimal | None:
        """The scope's sum. The residual ``chenh_lech_nguon`` carries orders but never traffic (by
        definition Shopee assigns it to no source), so for views / clicks it counts as 0; any other
        source without traffic makes the total unknown (ADR-122 d.2: CTOR = all orders ÷ clicks)."""
        values = [
            Decimal(0)
            if (s.source == RESIDUAL and field_name in ("views", "clicks"))
            else getattr(s, field_name)
            for s in self.sources
        ]
        if any(v is None for v in values):
            return None
        return sum(values, Decimal(0))


# -- what an option declares ---------------------------------------------------------------------

Driver = Literal["views", "ctr", "ctor", "aov"]
Basis = Literal["measured", "product_history", "shop", "prior", "not_estimable"]


@dataclass(frozen=True)
class Band:
    """A relative lift (0.05 = +5 %) or an absolute amount at P10 / P50 / P90. The engine fits a
    distribution through the three and draws from it; P10 <= P50 <= P90."""

    p10: Decimal
    p50: Decimal
    p90: Decimal


@dataclass(frozen=True)
class AddedTraffic:
    """Views an option ADDS with their own funnel (ads impressions, a KOL's views, a new pack
    option): ``views`` absolute over the option's duration; ``ctr`` / ``ctor`` / ``aov`` of that
    traffic (measured: the product's past campaigns, the KOL's own row, the matching pack
    variation); ``extra_share`` = the share of its orders that are extra (ADR-122 d.8: measured
    on / off days; cashback affiliates 0). Orders = views × ctr × ctor × extra_share."""

    views: Band
    ctr: Decimal
    ctor: Decimal
    aov: Decimal
    extra_share: Band
    profit_per_order: Decimal | None


@dataclass(frozen=True)
class DriverEffect:
    """One driver (ADR-122 d.1). Either ``lift`` (relative change of the base metric on
    ``sources``) or ``added`` (new traffic on ``sources[0]``) is set — never both. ``basis`` says
    where the evidence comes from; ``not_estimable`` (with ``note``) makes the result cost and
    break-even only."""

    metric: Driver
    sources: tuple[Source, ...]
    basis: Basis
    lift: Band | None = None
    added: AddedTraffic | None = None
    note: str | None = None  # Vietnamese, shown on the card when set


@dataclass(frozen=True)
class OfferCost:
    """A per-use cost (voucher, combo tier discount, commission): ``per_use`` đ on each order that
    uses it; ``use_share`` = the share of ALL orders after the change that use it (existing buyers
    who already qualified included, ADR-122 d.7); ``use_cap`` = a usage limit over the duration."""

    per_use: Decimal
    use_share: Band
    use_cap: Decimal | None = None
    label: str = ""  # "voucher", "giảm giá combo", "hoa hồng" ...


@dataclass(frozen=True)
class AdsEvaluation:
    """P100 B.15: an edit of a running Dịch vụ hiển thị campaign, judged on its own measured
    history over the option's days. ``*_now`` = the campaign as it runs today, ``*_after`` = with
    the edit (``None`` = chưa ước tính được). Orders are the campaign's direct ad orders adjusted
    for the shop's cancel rate; GMV is Shopee's placed-order ad GMV (ROAS Shopee, reference only).
    ``break_even_cpa`` = profit per order before ads of the campaign's products. The engine's Δ
    total profit / ROI come from the INCREMENTAL orders only (``incremental_share``)."""

    lever: str
    campaign: str
    days: int
    spend_basis: str  # not_capped | budget_capped | roas_history | product_rows | not_estimable
    spend_text: str
    spend_now: Decimal
    spend_after: Decimal | None
    orders_now: Decimal
    orders_after: Decimal | None
    gmv_now: Decimal
    gmv_after: Decimal | None
    break_even_cpa: Decimal | None
    incremental_share: Band | None = None
    cancel_rate: Decimal | None = None

    @staticmethod
    def _cpa(spend: Decimal | None, orders: Decimal | None) -> Decimal | None:
        if spend is None or orders is None or orders <= 0:
            return None
        return spend / orders

    @property
    def cpa_now(self) -> Decimal | None:
        return self._cpa(self.spend_now, self.orders_now)

    @property
    def cpa_after(self) -> Decimal | None:
        return self._cpa(self.spend_after, self.orders_after)

    def profit_after_ads(self, spend: Decimal | None, orders: Decimal | None) -> Decimal | None:
        """ad orders × (break-even CPA − CPA) = ad orders × break-even CPA − spend."""
        if spend is None or orders is None or self.break_even_cpa is None:
            return None
        return orders * self.break_even_cpa - spend


@dataclass(frozen=True)
class OptionInput:
    """One option ready for the engine: 1-2 drivers, its costs, its duration."""

    kind: str  # the change_kind (shopee_recommendations.kinds)
    label: str
    drivers: tuple[DriverEffect, ...]  # 1 or 2 (ADR-122 d.1)
    duration_days: int | None  # None = no end date -> the 30-day horizon "30 ngày đầu"
    fixed_cost: Decimal = Decimal(0)  # ad spend, samples, ... over the duration
    offers: tuple[OfferCost, ...] = ()
    #: profit per order after the change for the base's orders (a price change); None = unchanged
    profit_per_order_after: Decimal | None = None
    note: str | None = None
    #: P100 B.15: an Ads edit's CPA / break-even CPA facts, carried to the result unchanged
    ads: AdsEvaluation | None = None


# -- what the engine returns ---------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """One whole simulated outcome over the duration (ADR-122 d.4): the funnel holds exactly."""

    views: Decimal | None
    clicks: Decimal | None
    orders: Decimal
    gmv: Decimal
    profit: Decimal | None
    offer_cost: Decimal
    by_source: dict[str, dict[str, Decimal | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class BuildUpPart:
    """One part of the Δ Lợi nhuận line (at most three): "+1 đơn × 44.900đ", "AOV cao hơn
    43.500đ", "− voucher 12 lượt × 5.000đ"."""

    key: Literal["extra_orders", "aov", "offer", "fixed", "price"]
    amount: Decimal
    text: str


@dataclass(frozen=True)
class OptionResult:
    """Everything the card and the comparison table show (ADR-122 d.5). ``before`` is the base
    scaled to the duration (no range); ``low`` / ``likely`` / ``high`` are the P10 / P50 / P90
    outcomes ranked by Δ Lợi nhuận. ``estimable`` False = cost and break-even only."""

    kind: str
    label: str
    days: int
    horizon: Literal["duration", "first_30_days"]
    drivers: tuple[Driver, ...]
    estimable: bool
    basis: Basis
    before: Scenario
    low: Scenario | None
    likely: Scenario | None
    high: Scenario | None
    build_up: tuple[BuildUpPart, ...]
    cost_total: Decimal
    break_even_orders: Decimal | None
    break_even_aov: Decimal | None
    notes: tuple[str, ...] = ()
    ads: AdsEvaluation | None = None  # P100 B.15 (Ads edits only)

    def json(self) -> dict[str, object]:
        """The wire shape, mirrored exactly by ``apps/demo/.../option-result.ts``. Implemented in
        ``engine.wire.result_json`` (wave 1); ``WIRE_KEYS`` below is the contract."""
        from juli_backend.services.shopee_builder.engine.wire import result_json

        return result_json(self)


#: The keys of ``OptionResult.json()`` (wave 1 implements, wave 3 renders). Money / counts are
#: numbers (VND / count), pct are percent numbers (3.5 = +3,5 %), None when unknown.
WIRE_KEYS = {
    "kind": "str",
    "label": "str",
    "days": "int",
    "horizon": "'duration' | 'first_30_days'",
    "drivers": "list['views'|'ctr'|'ctor'|'aov']",
    "estimable": "bool",
    "basis": "'measured'|'product_history'|'shop'|'prior'|'not_estimable'",
    "basis_weak": "bool  # tag 'ước tính chung' (prior) shown",
    "delta": {
        "profit": "{value, pct, low, high} | None (None = chưa tính / chưa ước tính được)",
        "gmv": "{value, pct}",
        "orders": "{value, pct, note}  # note e.g. 'voucher tăng giá trị đơn, không tăng số đơn'",
    },
    "build_up": "list[{key, amount, text}]  # <= 3",
    "drivers_pct": "list[{metric, label, pct}]  # 'AOV +1,7%'",
    "cost": "{total, break_even_orders, break_even_aov, text}",
    "after": "{days, label: 'Sau 14 ngày' | '30 ngày đầu', gmv_before, gmv_after, "
    "profit_before, profit_after}",
    "per_30d": "{profit, gmv, orders, secondary: True, label}  # P99b: secondary, labelled "
    "'Quy đổi 30 ngày (tham khảo)'; the comparison's sort key (profit)",
    "roi": "{value, text}  # P100-C: ΔGMV ÷ cost ('ROI 3,2'); None = no cost / not estimable",
    "margin": "{before_pct, after_pct, shift_pts}  # P100-C: profit ÷ GMV; shift in points",
    "detail": "{before, low, likely, high: "
    "{views, ctr, ctor, orders, aov, gmv, profit, by_source}}",
    "notes": "list[str]",
    "ads": "{lever, campaign, days, spend_basis, spend_text, spend: {now, after}, orders: {now, "
    "after}, cpa: {now, after}, break_even_cpa, verdict: {now, after}  # 'co_lai' | 'lo' | None, "
    "verdict_text: {now, after}, profit_after_ads: {now, after}, roas_shopee: {now, after}, "
    "incremental: {share, orders_all, orders_extra}, cancel_rate_pct} | None  # P100 B.15: "
    "Ads edits of a running campaign only",
}
