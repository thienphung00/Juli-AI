"""P92 B-4: the typed inputs of one version, one model per strategy.

A version is ``{"kind": ..., "label"?: ..., <the kind's fields>}``. Money is whole đồng; a percent
is 0-100 (the caps below are the limits the web form enforces too). Every model refuses unknown
keys and every number has a bound, so a typo is a 422 at the door, not a strange number later.

``items`` the builder needs are always explicit ids (``item_id`` = a Shopee item, ``variation_id``
= one of its variations as ``/variations`` lists them). Nothing here reads the database.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_MONEY = 2_000_000_000
MAX_VERSIONS = 4
MIN_VERSIONS_COMPARE = 2
MAX_COMBO_ITEMS = 6
MAX_ADDONS = 5
MAX_VOUCHER_DAYS = 90
MAX_TITLE_CHARS = 100
MAX_KEYWORDS = 30

VOUCHER_SCOPES = ("shop", "product", "follower", "livestream")
KIND_KEYS = (
    "voucher",
    "combo",
    "add_on",
    "gift",
    "product_discount",
    "price",
    "flash_sale",
    "variation_set",
    "ads",
    "title",
    "cover_image",
    "description_first_line",
    "affiliate",
    "price_display",
    "listing_hide",
    "listing_relist",
)

ItemId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[^\s:]+$")]
VariationId = Annotated[str, Field(max_length=64, pattern=r"^[^\s:]*$")]
Money = Annotated[int, Field(ge=0, le=MAX_MONEY)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=60)


class VoucherSpec(_Base):
    """Four voucher kinds, typed numbers (no sliders): shop voucher (whole shop), product voucher
    (``item_ids``), follower / new-buyer voucher, livestream / video voucher."""

    kind: Literal["voucher"]
    scope: Literal["shop", "product", "follower", "livestream"] = "shop"
    item_ids: list[ItemId] = Field(default_factory=list, max_length=20)
    discount_type: Literal["amount", "pct"]
    value: float = Field(gt=0, le=MAX_MONEY)
    min_spend: Money = 0
    max_value: Annotated[int, Field(ge=1, le=MAX_MONEY)] | None = None
    usage_limit: Annotated[int, Field(ge=1, le=10_000_000)] | None = None
    per_buyer_limit: Annotated[int, Field(ge=1, le=100)] | None = None
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _check(self) -> VoucherSpec:
        if self.discount_type == "pct" and not 0 < self.value <= 90:
            raise ValueError("a percent voucher is above 0 and at most 90")
        if self.discount_type == "amount" and self.max_value is not None:
            raise ValueError("max_value is the cap of a percent voucher")
        if self.scope == "product" and not self.item_ids:
            raise ValueError("a product voucher needs item_ids")
        if self.scope != "product" and self.item_ids:
            raise ValueError("item_ids belong to a product voucher")
        if self.start and self.end:
            if self.end < self.start:
                raise ValueError("end is before start")
            if (self.end - self.start).days + 1 > MAX_VOUCHER_DAYS:
                raise ValueError(f"a voucher runs at most {MAX_VOUCHER_DAYS} days")
        return self

    @property
    def days(self) -> int | None:
        return None if not (self.start and self.end) else (self.end - self.start).days + 1


class ComboLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: ItemId
    variation_id: VariationId = ""
    qty: Annotated[int, Field(ge=1, le=20)] = 1


class InlineVoucher(BaseModel):
    model_config = ConfigDict(extra="forbid")
    discount_type: Literal["amount", "pct"]
    value: float = Field(gt=0, le=MAX_MONEY)
    min_spend: Money = 0
    max_value: Annotated[int, Field(ge=1, le=MAX_MONEY)] | None = None

    @model_validator(mode="after")
    def _check(self) -> InlineVoucher:
        if self.discount_type == "pct" and not 0 < self.value <= 90:
            raise ValueError("a percent voucher is above 0 and at most 90")
        return self


class ComboSpec(_Base):
    """2-6 products with a quantity and a variation each; price as a fixed price, % off or đ off the
    sum. ``target``: a Shopee "Combo khuyến mãi" or a new combo listing."""

    kind: Literal["combo"]
    items: list[ComboLine] = Field(min_length=2, max_length=MAX_COMBO_ITEMS)
    pricing: Literal["pct", "amount", "fixed_price"]
    value: float = Field(gt=0, le=MAX_MONEY)
    target: Literal["bundle_deal", "new_listing"] = "bundle_deal"
    voucher: InlineVoucher | None = None
    gift_item_id: ItemId | None = None

    @model_validator(mode="after")
    def _check(self) -> ComboSpec:
        if self.pricing == "pct" and not 0 < self.value <= 90:
            raise ValueError("a percent discount is above 0 and at most 90")
        if len({line.item_id for line in self.items}) != len(self.items):
            raise ValueError("the products of a combo are different")
        return self


class AddOn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: ItemId
    variation_id: VariationId = ""
    price: Annotated[int, Field(ge=1, le=MAX_MONEY)] | None = None
    pct: Annotated[float, Field(ge=0, le=90)] | None = None
    limit_per_order: Annotated[int, Field(ge=1, le=20)] = 1

    @model_validator(mode="after")
    def _one(self) -> AddOn:
        if (self.price is None) == (self.pct is None):
            raise ValueError("exactly one of price / pct")
        return self


class AddOnSpec(_Base):
    """1 main product with 1-5 add-ons, each at an add-on price (or % off) and a per-order limit."""

    kind: Literal["add_on"]
    main_item_id: ItemId
    addons: list[AddOn] = Field(min_length=1, max_length=MAX_ADDONS)

    @model_validator(mode="after")
    def _check(self) -> AddOnSpec:
        ids = [a.item_id for a in self.addons]
        if len(set(ids)) != len(ids) or self.main_item_id in ids:
            raise ValueError("add-ons are different from each other and from the main product")
        return self


class GiftItem(BaseModel):
    """The gift: a listing, or "quà không bán" with a typed unit cost (never touches stock)."""

    model_config = ConfigDict(extra="forbid")
    item_id: ItemId | None = None
    unit_cost: Annotated[int, Field(ge=0, le=MAX_MONEY)] | None = None
    packaging: Annotated[int, Field(ge=0, le=MAX_MONEY)] | None = None
    label: str | None = Field(default=None, max_length=80)
    qty: Annotated[int, Field(ge=1, le=20)] = 1

    @model_validator(mode="after")
    def _one(self) -> GiftItem:
        if (self.item_id is None) == (self.unit_cost is None):
            raise ValueError("a gift is a listing (item_id) or a typed unit_cost, not both")
        return self


class GiftTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["buy_item", "min_spend"]
    item_id: ItemId | None = None
    amount: Money | None = None

    @model_validator(mode="after")
    def _check(self) -> GiftTrigger:
        if self.type == "buy_item" and not self.item_id:
            raise ValueError("buy_item needs item_id")
        if self.type == "min_spend" and self.amount is None:
            raise ValueError("min_spend needs amount")
        return self


class GiftSpec(_Base):
    kind: Literal["gift"]
    gift: GiftItem
    trigger: GiftTrigger


class VariationPrice(BaseModel):
    """One variation's new price: a percent off the list price, or the final price. For ``price``
    (list price change) ``change_pct`` moves today's price by a percent (negative = cheaper)."""

    model_config = ConfigDict(extra="forbid")
    variation_id: VariationId = ""
    discount_pct: Annotated[float, Field(ge=0, le=90)] | None = None
    final_price: Annotated[int, Field(ge=1, le=MAX_MONEY)] | None = None
    change_pct: Annotated[float, Field(ge=-50, le=100)] | None = None

    @model_validator(mode="after")
    def _one(self) -> VariationPrice:
        given = [v is not None for v in (self.discount_pct, self.final_price, self.change_pct)]
        if sum(given) != 1:
            raise ValueError("exactly one of discount_pct / final_price / change_pct")
        return self


class ProductDiscountSpec(_Base):
    """Giảm giá per variation (% or final price), dates, per-buyer limit."""

    kind: Literal["product_discount"]
    item_id: ItemId
    variations: list[VariationPrice] = Field(default_factory=list, max_length=40)
    start: date | None = None
    end: date | None = None
    per_buyer_limit: Annotated[int, Field(ge=1, le=100)] | None = None

    @model_validator(mode="after")
    def _check(self) -> ProductDiscountSpec:
        if any(v.change_pct is not None for v in self.variations):
            raise ValueError("change_pct belongs to a price change, use discount_pct / final_price")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end is before start")
        return self

    @property
    def days(self) -> int | None:
        return None if not (self.start and self.end) else (self.end - self.start).days + 1


class PriceSpec(_Base):
    """Đổi giá niêm yết per variation."""

    kind: Literal["price"]
    item_id: ItemId
    variations: list[VariationPrice] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _check(self) -> PriceSpec:
        if any(v.discount_pct is not None for v in self.variations):
            raise ValueError("a price change uses final_price or change_pct")
        return self


class FlashSaleSpec(_Base):
    """A shop flash-sale slot: price, stock and slot time."""

    kind: Literal["flash_sale"]
    item_id: ItemId
    variations: list[VariationPrice] = Field(default_factory=list, max_length=40)
    units: Annotated[int, Field(ge=1, le=1_000_000)]
    slot_start: str | None = Field(default=None, max_length=40)
    slot_hours: Annotated[int, Field(ge=1, le=72)] = 2

    @model_validator(mode="after")
    def _check(self) -> FlashSaleSpec:
        if any(v.change_pct is not None for v in self.variations):
            raise ValueError("change_pct belongs to a price change")
        return self


class NewVariation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    price: Annotated[int, Field(ge=1, le=MAX_MONEY)]
    sku: str | None = Field(default=None, max_length=100)
    pack_count: Annotated[int, Field(ge=1, le=100)] | None = None
    stock: Annotated[int, Field(ge=0, le=10_000_000)] | None = None


class VariationSetSpec(_Base):
    """Add or merge variations (Set 3, Set 5 ...) with their own prices and SKUs."""

    kind: Literal["variation_set"]
    item_id: ItemId
    new_variations: list[NewVariation] = Field(min_length=1, max_length=12)
    hide_item_ids: list[ItemId] = Field(default_factory=list, max_length=10)


class AdsKeyword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(min_length=1, max_length=100)
    bid: Annotated[int, Field(ge=0, le=MAX_MONEY)]
    match: Literal["broad", "exact"] = "broad"


class AdsSpec(_Base):
    """Four levers: ``budget`` (đ/day), ``roas`` (target), ``add_product`` / ``remove_product`` and
    ``keywords`` (+ bids) for a manual keyword campaign."""

    kind: Literal["ads"]
    lever: Literal["budget", "roas", "add_product", "remove_product", "keywords"]
    campaign_key: str | None = Field(default=None, max_length=100)
    daily_budget: Annotated[int, Field(ge=0, le=MAX_MONEY)] | None = None
    roas_target: Annotated[float, Field(gt=0, le=100)] | None = None
    item_id: ItemId | None = None
    keywords: list[AdsKeyword] = Field(default_factory=list, max_length=MAX_KEYWORDS)

    @model_validator(mode="after")
    def _check(self) -> AdsSpec:
        need = {
            "budget": self.daily_budget is not None,
            "roas": self.roas_target is not None,
            "add_product": self.item_id is not None,
            "remove_product": self.item_id is not None,
            "keywords": bool(self.keywords),
        }[self.lever]
        if not need:
            raise ValueError(f"lever {self.lever} is missing its input")
        return self


class TitleSpec(_Base):
    kind: Literal["title"]
    item_id: ItemId
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    keywords: list[str] = Field(default_factory=list, max_length=MAX_KEYWORDS)


class CoverOverlay(BaseModel):
    """Text fields of the CoverVariant overlay; the product photo is never altered."""

    model_config = ConfigDict(extra="forbid")
    layout: Literal["banner_top", "banner_bottom", "corner_tag"]
    price_vnd: Annotated[int, Field(ge=1, le=MAX_MONEY)] | None = None
    original_price_vnd: Annotated[int, Field(ge=1, le=MAX_MONEY)] | None = None
    discount_pct: Annotated[float, Field(ge=0, le=90)] | None = None
    voucher_text: str | None = Field(default=None, max_length=60)
    pack_text: str | None = Field(default=None, max_length=60)
    badge_text: str | None = Field(default=None, max_length=30)
    hook_text: str | None = Field(default=None, max_length=60)


class CoverSpec(_Base):
    kind: Literal["cover_image"]
    item_id: ItemId
    overlay: CoverOverlay


class DescriptionSpec(_Base):
    kind: Literal["description_first_line"]
    item_id: ItemId
    first_line: str = Field(min_length=1, max_length=300)


class AffiliateSpec(_Base):
    """Commission rate per product, optional target campaign, optional sample sending."""

    kind: Literal["affiliate"]
    item_id: ItemId
    commission_pct: Annotated[float, Field(ge=0, le=50)]
    target_campaign: bool = False
    sample_qty: Annotated[int, Field(ge=0, le=50)] = 0
    sample_ship_fee: Money = 0


class PriceDisplaySpec(_Base):
    """Show the price per unit on the cover."""

    kind: Literal["price_display"]
    item_id: ItemId
    variation_id: VariationId = ""
    text: str | None = Field(default=None, max_length=60)


class HideSpec(_Base):
    kind: Literal["listing_hide"]
    item_id: ItemId


class RelistSpec(_Base):
    kind: Literal["listing_relist"]
    item_id: ItemId
    stock: Annotated[int, Field(ge=0, le=10_000_000)] | None = None


VersionSpec = Annotated[
    VoucherSpec
    | ComboSpec
    | AddOnSpec
    | GiftSpec
    | ProductDiscountSpec
    | PriceSpec
    | FlashSaleSpec
    | VariationSetSpec
    | AdsSpec
    | TitleSpec
    | CoverSpec
    | DescriptionSpec
    | AffiliateSpec
    | PriceDisplaySpec
    | HideSpec
    | RelistSpec,
    Field(discriminator="kind"),
]


def items_of(spec: BaseModel) -> list[str]:
    """Every item id a version names (to load their variations and history)."""
    out: list[str] = []
    for key in ("item_id", "main_item_id", "gift_item_id"):
        value = getattr(spec, key, None)
        if value:
            out.append(str(value))
    for key in ("item_ids", "hide_item_ids"):
        out += [str(x) for x in getattr(spec, key, None) or []]
    for line in getattr(spec, "items", None) or []:
        out.append(line.item_id)
    for add in getattr(spec, "addons", None) or []:
        out.append(add.item_id)
    gift = getattr(spec, "gift", None)
    if gift is not None and gift.item_id:
        out.append(gift.item_id)
    trigger = getattr(spec, "trigger", None)
    if trigger is not None and trigger.item_id:
        out.append(trigger.item_id)
    return list(dict.fromkeys(out))


def as_json(spec: BaseModel) -> dict[str, Any]:
    return spec.model_dump(mode="json", exclude_none=True)


__all__ = [
    "KIND_KEYS",
    "MAX_VERSIONS",
    "MIN_VERSIONS_COMPARE",
    "VOUCHER_SCOPES",
    "VersionSpec",
    "as_json",
    "items_of",
]
