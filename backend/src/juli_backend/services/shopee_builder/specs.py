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
MAX_ADDONS = 5
MAX_VOUCHER_DAYS = 90
MAX_TITLE_CHARS = 100
MAX_KEYWORDS = 30
MAX_TARGETS = 100

VOUCHER_SCOPES = ("shop", "product", "follower", "livestream")
KIND_KEYS = (
    "voucher",
    "combo",
    "listing_combo",
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
    item_ids: list[ItemId] = Field(default_factory=list, max_length=MAX_TARGETS)
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


#: P100 wave 2: Shopee's programme forms (Chương Trình Của Shop, Deal Sốc) take a name, a start and
#: an end with hour precision; the limits below are the ones Seller Centre showed (brief C)
MAX_PROGRAMME_NAME = 150
MAX_DISCOUNT_DAYS = 180
MIN_PROGRAMME_HOURS = 1
MAX_ADDON_LIMIT = 100
MAX_GIFT_QTY = 49
TIME_WINDOW_BACKWARDS = "Thời gian kết thúc phải sau thời gian bắt đầu."
TIME_WINDOW_TOO_SHORT = "Thời gian chạy tối thiểu 1 giờ."
TIME_WINDOW_NEEDS_DATE = "Chọn ngày cho giờ bắt đầu / kết thúc."


def window_hours(
    start: date | None, start_hour: int | None, end: date | None, end_hour: int | None
) -> int | None:
    """The running time in hours when both ends carry an hour (Shopee's precision)."""
    if not (start and end) or start_hour is None or end_hour is None:
        return None
    return (end - start).days * 24 + end_hour - start_hour


def window_days(
    start: date | None, start_hour: int | None, end: date | None, end_hour: int | None
) -> int | None:
    if not (start and end):
        return None
    hours = window_hours(start, start_hour, end, end_hour)
    if hours is not None:
        return max(1, -(-hours // 24))
    return (end - start).days + 1


def check_window(
    start: date | None,
    start_hour: int | None,
    end: date | None,
    end_hour: int | None,
    *,
    max_days: int | None = None,
) -> None:
    """Dates and hours of one programme: an hour needs its date, the end is after the start by at
    least one hour (when both carry an hour), and at most ``max_days`` days long."""
    if (start_hour is not None and start is None) or (end_hour is not None and end is None):
        raise ValueError(TIME_WINDOW_NEEDS_DATE)
    if start and end:
        if end < start:
            raise ValueError(TIME_WINDOW_BACKWARDS)
        hours = window_hours(start, start_hour, end, end_hour)
        if hours is not None and hours <= 0:
            raise ValueError(TIME_WINDOW_BACKWARDS)
        if hours is not None and hours < MIN_PROGRAMME_HOURS:
            raise ValueError(TIME_WINDOW_TOO_SHORT)
        days = window_days(start, start_hour, end, end_hour)
        if max_days is not None and days is not None and days > max_days:
            raise ValueError(f"Chương trình chạy tối đa {max_days} ngày.")


COMBO_TYPES = ("pct", "amount", "special_price")
MAX_COMBO_TIERS = 5
MAX_COMBO_NAME = 25
MAX_COMBO_PRODUCTS = 100
MAX_PURCHASE_LIMIT = 999_999_999


class ComboTier(BaseModel):
    """One row "Mua [N] sản phẩm → x": a percent off, an amount off, or a special price for N."""

    model_config = ConfigDict(extra="forbid")
    qty: Annotated[int, Field(ge=2, le=9999)]
    value: float = Field(gt=0, le=MAX_MONEY)


class ComboSpec(_Base):
    """Combo Khuyến Mãi in Shopee's shape (P97 D85.15): a product list (no quantity or variation per
    item), a type (giảm %, giảm số tiền, giá đặc biệt), tiers "Mua N sản phẩm → x", the order
    limit per buyer (giới hạn đặt hàng), a name of at most 25 characters and the dates. It is the
    model of the ``bundle_deal`` cards Juli generates. The inline voucher and the gift are their
    own kinds."""

    kind: Literal["combo"]
    name: str | None = Field(default=None, max_length=MAX_COMBO_NAME)
    item_ids: list[ItemId] = Field(min_length=1, max_length=MAX_COMBO_PRODUCTS)
    discount_type: Literal["pct", "amount", "special_price"]
    tiers: list[ComboTier] = Field(min_length=1, max_length=MAX_COMBO_TIERS)
    purchase_limit: Annotated[int, Field(ge=1, le=MAX_PURCHASE_LIMIT)] | None = None
    start: date | None = None
    end: date | None = None
    #: P100-C: "Thời gian chạy Combo" has hour precision in Seller Centre (0-23, the hour the
    #: combo starts / ends on ``start`` / ``end``); None = the whole day
    start_hour: Annotated[int, Field(ge=0, le=23)] | None = None
    end_hour: Annotated[int, Field(ge=0, le=23)] | None = None

    @model_validator(mode="after")
    def _check(self) -> ComboSpec:
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("the products of a combo are different")
        if len({t.qty for t in self.tiers}) != len(self.tiers):
            raise ValueError("each tier has its own quantity")
        if self.discount_type == "pct" and any(not 0 < t.value <= 90 for t in self.tiers):
            raise ValueError("a percent discount is above 0 and at most 90")
        if not _tiers_increase(self.discount_type, self.tiers):
            raise ValueError(COMBO_TIERS_NOT_INCREASING)
        if (self.start_hour is not None and self.start is None) or (
            self.end_hour is not None and self.end is None
        ):
            raise ValueError("an hour needs its date")
        if self.start and self.end:
            if self.end < self.start:
                raise ValueError("end is before start")
            if self.hours is not None and self.hours <= 0:
                raise ValueError("end is before start")
        return self

    @property
    def hours(self) -> int | None:
        """The running time in hours when both ends carry an hour (Shopee's precision)."""
        if not (self.start and self.end) or self.start_hour is None or self.end_hour is None:
            return None
        return (self.end - self.start).days * 24 + self.end_hour - self.start_hour

    @property
    def days(self) -> int | None:
        if not (self.start and self.end):
            return None
        hours = self.hours
        if hours is not None:
            return max(1, -(-hours // 24))
        return (self.end - self.start).days + 1


#: P100-C (B.9): a tier that buys more units gives a strictly bigger effective percent
COMBO_TIERS_NOT_INCREASING = (
    "Mỗi mức ưu đãi sau (mua nhiều sản phẩm hơn) cần giảm nhiều hơn mức trước."
)


def _tiers_increase(dtype: str, tiers: list[ComboTier]) -> bool:
    """The effective percent per tier rises with N, checked without the unit price: % itself;
    số tiền ÷ N rises (amount ÷ (N × đơn giá)); giá đặc biệt ÷ N falls (1 − giá ÷ (N × đơn giá))."""
    rows = sorted(tiers, key=lambda t: t.qty)
    per = [t.value if dtype == "pct" else t.value / t.qty for t in rows]
    pairs = list(zip(per, per[1:], strict=False))
    if dtype == "special_price":
        return all(b < a for a, b in pairs)
    return all(b > a for a, b in pairs)


MAX_LISTING_MEMBERS = 20
MAX_LISTING_IMAGES = 9


class ListingComboSpec(_Base):
    """A new listing that sells existing products together (P97 D85.16): title, image references
    (file names or ids -- never bytes), price, stock, SKU and the member products. Its estimate
    starts with no history or ranking and takes demand from the singles it contains."""

    kind: Literal["listing_combo"]
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    image_refs: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=MAX_LISTING_IMAGES
    )
    price: Annotated[int, Field(ge=1_000, le=MAX_MONEY)]
    stock: Annotated[int, Field(ge=0, le=10_000_000)]
    sku: str | None = Field(default=None, max_length=100)
    member_ids: list[ItemId] = Field(min_length=2, max_length=MAX_LISTING_MEMBERS)

    @model_validator(mode="after")
    def _check(self) -> ListingComboSpec:
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("the products of a listing combo are different")
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
    """Mua Kèm Deal Sốc (one of the two Loại Deal Sốc, P100 wave 2): Tên chương trình, Thời gian
    bắt đầu / kết thúc, Giới hạn sản phẩm mua kèm (at most 100 add-ons per main product), Sản Phẩm
    Chính and Sản Phẩm Mua Kèm with a price (or % off) per add-on. The older P92 card (a main
    product, 1-5 add-ons, no name or dates) still loads: every new field is optional."""

    kind: Literal["add_on"]
    name: str | None = Field(default=None, max_length=MAX_PROGRAMME_NAME)
    main_item_id: ItemId
    addons: list[AddOn] = Field(min_length=1, max_length=MAX_ADDONS)
    #: "Giới hạn sản phẩm mua kèm": the most add-ons a buyer can take with the main product
    addon_limit: Annotated[int, Field(ge=1, le=MAX_ADDON_LIMIT)] | None = None
    start: date | None = None
    end: date | None = None
    start_hour: Annotated[int, Field(ge=0, le=23)] | None = None
    end_hour: Annotated[int, Field(ge=0, le=23)] | None = None

    @model_validator(mode="after")
    def _check(self) -> AddOnSpec:
        ids = [a.item_id for a in self.addons]
        if len(set(ids)) != len(ids) or self.main_item_id in ids:
            raise ValueError("add-ons are different from each other and from the main product")
        check_window(self.start, self.start_hour, self.end, self.end_hour)
        return self

    @property
    def days(self) -> int | None:
        return window_days(self.start, self.start_hour, self.end, self.end_hour)


class GiftItem(BaseModel):
    """The gift: a listing, or "quà không bán" with a typed unit cost (never touches stock)."""

    model_config = ConfigDict(extra="forbid")
    item_id: ItemId | None = None
    unit_cost: Annotated[int, Field(ge=0, le=MAX_MONEY)] | None = None
    packaging: Annotated[int, Field(ge=0, le=MAX_MONEY)] | None = None
    label: str | None = Field(default=None, max_length=80)
    qty: Annotated[int, Field(ge=1, le=MAX_GIFT_QTY)] = 1

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
    """Mua Để Nhận Quà (the other Loại Deal Sốc): Tên chương trình, Thời gian bắt đầu / kết thúc,
    Điều kiện nhận quà "Mua ₫[X] để nhận [N] quà tặng" (N below 50 = ``gift.qty``), the gift
    products. Older cards (no name or dates) still load."""

    kind: Literal["gift"]
    name: str | None = Field(default=None, max_length=MAX_PROGRAMME_NAME)
    gift: GiftItem
    trigger: GiftTrigger
    start: date | None = None
    end: date | None = None
    start_hour: Annotated[int, Field(ge=0, le=23)] | None = None
    end_hour: Annotated[int, Field(ge=0, le=23)] | None = None

    @model_validator(mode="after")
    def _check(self) -> GiftSpec:
        check_window(self.start, self.start_hour, self.end, self.end_hour)
        return self

    @property
    def days(self) -> int | None:
        return window_days(self.start, self.start_hour, self.end, self.end_hour)


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
    """Chương Trình Của Shop (Shopee's discount programme, P100 wave 2): Tên chương trình khuyến
    mãi, Thời gian khuyến mãi with hour precision (at most 180 days), per variation Giá sau giảm or
    % GIẢM, Số lượng sản phẩm khuyến mãi and Giới hạn đặt hàng. The key stays ``product_discount``.

    P97 D85.13: ``targets`` + ``discount_pct`` apply one % to every variation of each product in
    the list (Shopee's bulk discount): one card, a total and a row per target."""

    kind: Literal["product_discount"]
    name: str | None = Field(default=None, max_length=MAX_PROGRAMME_NAME)
    item_id: ItemId | None = None
    targets: list[ItemId] = Field(default_factory=list, max_length=MAX_TARGETS)
    discount_pct: Annotated[float, Field(gt=0, le=90)] | None = None
    variations: list[VariationPrice] = Field(default_factory=list, max_length=40)
    start: date | None = None
    end: date | None = None
    start_hour: Annotated[int, Field(ge=0, le=23)] | None = None
    end_hour: Annotated[int, Field(ge=0, le=23)] | None = None
    #: "Số lượng sản phẩm khuyến mãi" (None = "Không giới hạn"): caps the discounted units in the
    #: estimate (families._promo_reach) and is shown on the checklist
    promo_qty: Annotated[int, Field(ge=1, le=10_000_000)] | None = None
    per_buyer_limit: Annotated[int, Field(ge=1, le=100)] | None = None

    @model_validator(mode="after")
    def _check(self) -> ProductDiscountSpec:
        if self.targets:
            if self.item_id is not None or self.variations:
                raise ValueError("a many-target discount names targets and discount_pct only")
            if self.discount_pct is None:
                raise ValueError("a many-target discount needs discount_pct")
            if len(set(self.targets)) != len(self.targets):
                raise ValueError("targets are different from each other")
        else:
            if self.item_id is None:
                raise ValueError("item_id or targets")
            if self.discount_pct is not None:
                raise ValueError("discount_pct belongs to a many-target discount")
        if any(v.change_pct is not None for v in self.variations):
            raise ValueError("change_pct belongs to a price change, use discount_pct / final_price")
        # the 180-day limit is Shopee's; cards saved before it (no name, no hours) stay loadable
        shopee_form = bool(self.name) or self.start_hour is not None or self.end_hour is not None
        check_window(
            self.start,
            self.start_hour,
            self.end,
            self.end_hour,
            max_days=MAX_DISCOUNT_DAYS if shopee_form else None,
        )
        return self

    @property
    def days(self) -> int | None:
        return window_days(self.start, self.start_hour, self.end, self.end_hour)


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


ADS_MIN_BUDGET = 100_000
MAX_ADS_NEW_ITEMS = 50
MAX_ADS_NEW_DAYS = 365
#: Shopee's own hint for a custom ROAS target ("Vui lòng đặt ≤ 3.5"); higher is allowed with a
#: warning
ADS_ROAS_HINT = 3.5
ADS_ROAS_PRESETS = (2.5, 3.5, 4.5)
MAX_CAMPAIGNS = 30


class AdsSpec(_Base):
    """Shopee's edit form of a product-ads campaign (P97 D85.17): ``budget`` (≥ ₫100.000 per day, or
    ``unlimited``), ``roas`` (``system`` = optimised by Shopee, or ``custom`` with a target; presets
    2.5 / 3.5 / 4.5), ``add_product`` / ``remove_product``, and the run dates. ``campaign_keys``
    applies one budget / ROAS to several campaigns (P97 D85.13). Keyword bids are not a field of
    Shopee's form, so they are not a lever any more (old keyword cards stay readable)."""

    kind: Literal["ads"]
    lever: Literal["budget", "roas", "add_product", "remove_product"]
    campaign_key: str | None = Field(default=None, max_length=100)
    campaign_keys: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=MAX_CAMPAIGNS
    )
    daily_budget: Annotated[int, Field(ge=0, le=MAX_MONEY)] | None = None
    unlimited: bool = False
    roas_mode: Literal["system", "custom"] = "custom"
    roas_target: Annotated[float, Field(gt=0, le=100)] | None = None
    item_id: ItemId | None = None
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _check(self) -> AdsSpec:
        if self.lever == "budget":
            if self.unlimited == (self.daily_budget is not None):
                raise ValueError("budget: either daily_budget or unlimited")
        elif self.unlimited or self.daily_budget is not None:
            raise ValueError("daily_budget / unlimited belong to the budget lever")
        if self.lever == "roas":
            if (self.roas_mode == "custom") != (self.roas_target is not None):
                raise ValueError("roas: a custom target needs roas_target, the system mode none")
        elif self.roas_target is not None:
            raise ValueError("roas_target belongs to the roas lever")
        if self.lever in ("add_product", "remove_product") and self.item_id is None:
            raise ValueError(f"lever {self.lever} is missing its input")
        if self.campaign_keys:
            if self.lever not in ("budget", "roas"):
                raise ValueError("many campaigns only for budget / roas")
            if self.campaign_key is not None:
                raise ValueError("campaign_key or campaign_keys, not both")
            if len(set(self.campaign_keys)) != len(self.campaign_keys):
                raise ValueError("campaign_keys are different from each other")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end is before start")
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
    """Commission rate per product, optional target campaign, optional sample sending.

    P97 D85.13: ``targets`` applies one rate to many products (Shopee's "Chỉnh sửa hàng loạt")."""

    kind: Literal["affiliate"]
    item_id: ItemId | None = None
    targets: list[ItemId] = Field(default_factory=list, max_length=MAX_TARGETS)
    commission_pct: Annotated[float, Field(ge=0, le=50)]
    target_campaign: bool = False
    sample_qty: Annotated[int, Field(ge=0, le=50)] = 0
    sample_ship_fee: Money = 0

    @model_validator(mode="after")
    def _check(self) -> AffiliateSpec:
        if self.targets and self.item_id is not None:
            raise ValueError("item_id or targets, not both")
        if not self.targets and self.item_id is None:
            raise ValueError("item_id or targets")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("targets are different from each other")
        return self


class AdsNewSpec(_Base):
    """P99: a NEW Dịch vụ Hiển thị Sản phẩm campaign from the Ads tab (``/builder/ads/setup``) as a
    version, so it can be saved and added to Kế hoạch: ``group`` (chiến dịch nhóm) or ``single``
    (chiến dịch đơn, one product), daily budget, ROAS target (``None`` = Shopee-optimised), dates
    (no end date = the "30 ngày đầu" horizon). Not an edit of a running campaign (``ads``)."""

    kind: Literal["ads_new"]
    campaign: Literal["group", "single"] = "group"
    item_ids: list[ItemId] = Field(min_length=1, max_length=MAX_ADS_NEW_ITEMS)
    daily_budget: Annotated[int, Field(ge=ADS_MIN_BUDGET, le=MAX_MONEY)]
    roas_target: Annotated[float, Field(gt=0, le=100)] | None = None
    start: date
    end: date | None = None
    name: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _check(self) -> AdsNewSpec:
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("item_ids are different from each other")
        if self.campaign == "single" and len(self.item_ids) != 1:
            raise ValueError("a single campaign holds one product")
        if self.end is not None:
            days = (self.end - self.start).days + 1
            if days < 1:
                raise ValueError("end is on or after start")
            if days > MAX_ADS_NEW_DAYS:
                raise ValueError(f"at most {MAX_ADS_NEW_DAYS} days")
        return self

    @property
    def days(self) -> int | None:
        return None if self.end is None else (self.end - self.start).days + 1


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
    | ListingComboSpec
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
    | AdsNewSpec
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
    for key in ("item_ids", "hide_item_ids", "targets", "member_ids"):
        out += [str(x) for x in getattr(spec, key, None) or []]
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
