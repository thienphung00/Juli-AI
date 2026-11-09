"""What each family reads besides the version: small detached facts (no database below here).
The adapters build them from ``RecoEnv`` / the evaluators; tests build them by hand."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_builder.engine.contract import Band, Basis
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


@dataclass(frozen=True)
class ComboFacts:
    """Combo khuyến mãi on the shop's own order lines of its products."""

    aov_now: Decimal | None
    profit_per_order: Decimal | None
    per_use: Decimal  # mean discount of an order that reaches a tier
    use_share_now: Decimal  # share of ALL orders already holding a tier's units
    near_share: Decimal  # share of orders one unit under a tier
    unit_price: Decimal  # mean unit price of the listed products


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


@dataclass(frozen=True)
class PriceFacts:
    aov_now: Decimal | None
    profit_per_order: Decimal | None
    profit_per_order_after: Decimal | None  # certain, at today's volume
    price_factor: Decimal  # price after / price before (1 = unchanged)
    contribution_rate: Decimal | None
    ctor: LiftEvidence


@dataclass(frozen=True)
class SimpleFacts:
    """Listing / basket / gift: the lead driver's lift, an optional certain AOV lift."""

    lead: LiftEvidence
    aov: Band | None = None
    profit_per_order_after: Decimal | None = None


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
