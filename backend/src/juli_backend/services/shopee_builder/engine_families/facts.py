"""What each family reads besides the version: small detached facts (no database below here).
The adapters build them from ``RecoEnv`` / the evaluators; tests build them by hand."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_builder.engine.contract import Band, Basis, OfferCost
from juli_backend.services.shopee_builder.engine_families.measure import (
    AdCampaignHist,
    AdDay,
    KolBeforeAfter,
    KolRates,
)


@dataclass(frozen=True)
class LiftEvidence:
    """A relative lift band with where it comes from (product_history > shop > prior)."""

    band: Band
    basis: Basis


@dataclass(frozen=True)
class VoucherFacts:
    """The scope's orders against the voucher (existing qualifying orders included)."""

    aov_now: Decimal | None
    profit_per_order: Decimal | None
    per_use: Decimal  # the discount one order using the voucher gets
    qualifying_share: Decimal  # share of ALL orders already at / over the minimum
    raise_gap_per_order: Decimal  # mean over ALL orders of max(0, minimum - order value)
    below_share: Decimal  # share of orders under the minimum
    usage_rate: Decimal = Decimal(1)  # share of qualifying orders that use the voucher
    baseline_per_use: Decimal | None = None  # "giảm mức": today's discount per use
    #: ADR-122 d.13 E2: the share of ALL orders that reach the minimum, measured from the order
    #: lines (orders within 20 % below it today); None = too few orders -> the tagged prior
    reach: Band | None = None
    reach_gap: Decimal = Decimal(0)  # mean (minimum - order value) of those orders
    near_share: Decimal = Decimal(0)  # share of ALL orders within 20 % below the minimum


@dataclass(frozen=True)
class ComboFacts:
    """Combo khuyến mãi on the shop's own order lines of its products."""

    aov_now: Decimal | None
    profit_per_order: Decimal | None
    per_use: Decimal  # mean discount of an order that reaches a tier
    use_share_now: Decimal  # share of ALL orders already holding a tier's units
    near_share: Decimal  # share of orders within 20 % (at least one unit) under the lowest tier
    unit_price: Decimal  # mean unit price of the listed products
    #: ADR-122 d.13 E2: the share of ALL orders that reach the tier, measured (the near orders);
    #: None = too few orders, or the shop has never run a combo (P100 B.10) -> not estimable
    reach: Band | None = None
    #: why ``reach`` is None, shown on the not-estimable AOV driver (P100 B.10)
    reach_note: str | None = None
    reach_units: Decimal = Decimal(1)  # mean units those orders are short of the tier
    #: P100-C (J): Shopee's % fees are on the item total AFTER the combo, so one đồng of combo
    #: discount costs the seller (1 − fee_rate) đồng; 0 = no fee formula (the gross discount)
    fee_rate: Decimal = Decimal(0)


@dataclass(frozen=True)
class PackEvidence:
    """The same pack size of the same product, measured (ADR-122 d.7)."""

    views: Decimal  # the product's current views over its window
    window_days: int
    ctr: Decimal
    ctor: Decimal
    aov: Decimal
    profit_per_order: Decimal | None


@dataclass(frozen=True)
class ListingComboFacts:
    aov_now: Decimal | None
    profit_per_order: Decimal | None
    switch_share: Decimal  # share of orders already holding those quantities
    value_now: Decimal  # mean value of those orders today
    new_price: Decimal
    profit_per_order_after: Decimal | None  # blended for the base orders after switching
    pack: PackEvidence | None = None
    #: ADR-122 d.13 E3: the shop already sells this pack size: switching only (Δ Đơn 0)
    pack_sold_today: bool = False


@dataclass(frozen=True)
class NewComboListing:
    """One row of the combo builder as an option (ADR-122 d.7 / d.13 E3): a new listing selling
    ``quantities`` of existing variations at ``price``. ``pack_sold_today`` = the product already
    has a variation of this pack size (then buyers only switch). ``sku_keys`` = the order-line SKU
    of each member (item, sku key, quantity) to count the orders that already hold them."""

    key: str
    label: str
    item_ids: tuple[str, ...]
    members: tuple[tuple[str, str, int], ...]  # (item id, sku key, quantity)
    price: Decimal
    profit_per_order: Decimal | None
    pack_sold_today: bool = False


@dataclass(frozen=True)
class PriceFacts:
    aov_now: Decimal | None
    profit_per_order: Decimal | None
    profit_per_order_after: Decimal | None  # certain, at today's volume
    price_factor: Decimal  # price after / price before (1 = unchanged)
    contribution_rate: Decimal | None
    ctor: LiftEvidence
    #: P100 wave 2 (B.14): what the programme price takes off the profit of one order -- the cost
    #: of Chương Trình Của Shop, given on every order (the ones that would have happened anyway
    #: and the new ones); None when it cannot be stated
    discount_per_order: Decimal | None = None
    #: P100 wave 2 (owner 2026-11-12): "Số lượng sản phẩm khuyến mãi" caps the discounted units,
    #: so the estimate needs the products' units per order and orders per day today
    units_per_order: Decimal | None = None
    orders_per_day: Decimal | None = None


@dataclass(frozen=True)
class SimpleFacts:
    """Listing / basket / gift: the lead driver's lift, an optional certain AOV lift."""

    lead: LiftEvidence
    aov: Band | None = None
    profit_per_order_after: Decimal | None = None
    #: P100-C (A.9): the option's own per-use costs (Mua kèm discount, Quà tặng giá vốn)
    offers: tuple[OfferCost, ...] = ()


@dataclass(frozen=True)
class AdsNewCampaign:
    """The setup of a new Hiển thị Sản phẩm campaign (chiến dịch nhóm / đơn)."""

    item_ids: tuple[str, ...]
    daily_budget: Decimal
    start: date
    end: date
    roas_target: Decimal | None = None  # None = Shopee-optimised
    ad_type: str = "product_search"
    label: str | None = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class AdsFacts:
    campaigns: tuple[AdCampaignHist, ...] = ()
    days: tuple[AdDay, ...] = ()
    profit_per_order: Decimal | None = None


@dataclass(frozen=True)
class KolChoice:
    kol_key: str
    handle: str
    item_ids: tuple[str, ...]
    commission_pct: Decimal | None = None
    fixed_fee: Decimal = Decimal(0)
    sample_qty: int = 0
    sample_ship_fee: Decimal = Decimal(0)
    sample_item_id: str | None = None  # the product sent (None = the mean over ``item_ids``)


@dataclass(frozen=True)
class AffiliatePlan:
    kols: tuple[KolChoice, ...]
    duration_days: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class KolFacts:
    rates: dict[str, KolRates] = field(default_factory=dict)  # by kol_key
    before_after: dict[str, KolBeforeAfter] = field(default_factory=dict)
    sample_unit_cost: dict[str, Decimal] = field(default_factory=dict)  # item -> giá vốn + đóng gói
    profit_per_order: Decimal | None = None
    extra_cashback_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class AffiliateRateFacts:
    """P99: a product's commission rate (the builder's Liên kết tab, no KOL picked): the product's
    Liên kết GMV of the window (its affiliate order lines) and the samples' exact cost."""

    item_id: str
    affiliate_gmv: Decimal  # the window's affiliate-line GMV of the product
    window_days: int
    sample_cost: Decimal | None = None  # qty × (giá vốn + đóng gói) + ship; None = chưa tính
    sample_qty: int = 0
