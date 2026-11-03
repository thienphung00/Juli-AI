"""The ingest contract (D31.3): request body and one strict row model per dataset.

Rows carry the PLATFORM's own field names (Shopee Seller Centre's, from the
2026-10-12 recon: ``~/shopee-corpus/seller-centre-internal/01..02``) so the
mapping to Juli's streams and KPIs happens once, here on the server
(``mapping.py``), whatever the source -- extension, file upload, vendor or,
later, the official API. Anything a source sees that the contract does not name
goes in the row's ``extra`` object; its numbers, booleans and nulls are kept in
the normalized row. A STRING value there is accepted (a source is not refused for
sending one) and dropped on the server: free text could carry a buyer's name or
message, and the raw copy's allowlist keeps the same three types (owner decision
D16; ``services/privacy/payload_allowlist._filter_open_numeric``).

Units, as Seller Centre's API returns them (rates unverified on non-zero data;
the D31.6 recon confirms them):

- money (``sales``, ``sales_per_order``, ``ads_expense``) in VND, a number;
- counts may be FRACTIONAL (``orders``, ``units``: a multi-item order is
  apportioned across its items);
- rates (``ctr``, ``*_rate``, ``conversion``) are FRACTIONS in [0, 1]; a
  percentage (e.g. 3.2 for 3.2 %) is refused, so a unit change at Shopee
  surfaces as a 422 / drift instead of being stored 100× wrong;
- ``date`` is the Seller Centre calendar day (GMT+7), ``YYYY-MM-DD``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

#: Hard limits (the route also caps the body at ``MAX_BODY_BYTES``).
#: Below nginx's default 1 MiB `client_max_body_size` on api.app-juli.com.
MAX_BODY_BYTES = 1_000_000
MAX_ROWS = 2_000
MAX_PERIOD_DAYS = 31
#: Seller Centre's ad reports cover a three-month window; only ``ads_campaign_period``
#: may exceed ``MAX_PERIOD_DAYS`` (its ``DatasetSpec.max_period_days``), up to this ceiling.
MAX_ADS_PERIOD_DAYS = 100
MAX_EXTRA_KEYS = 60
MAX_EXTRA_STRING = 200

_BIG = Decimal("1e15")

Count = Annotated[Decimal, Field(ge=0, le=_BIG, allow_inf_nan=False)]
SignedCount = Annotated[Decimal, Field(ge=-_BIG, le=_BIG, allow_inf_nan=False)]
Money = Annotated[Decimal, Field(ge=0, le=_BIG, allow_inf_nan=False)]
Rate = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
Ratio = Annotated[Decimal, Field(ge=0, le=Decimal(100_000), allow_inf_nan=False)]
ItemId = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")]
ExtraKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")]
ExtraValue = (
    Annotated[str, StringConstraints(max_length=MAX_EXTRA_STRING)] | int | float | bool | None
)

SHOPEE_L1_SOURCES: tuple[str, ...] = (
    "psd_label_product_card",
    "psd_label_seller_live",
    "psd_label_seller_video",
    "psd_label_affiliate",
    "psd_label_shopee_ads",
)
ShopeeL1Source = Literal[
    "psd_label_product_card",
    "psd_label_seller_live",
    "psd_label_seller_video",
    "psd_label_affiliate",
    "psd_label_shopee_ads",
]

_CARD_LIKE: dict[str, str] = {
    "Tìm kiếm": "search",
    "Đề xuất": "recommend",
    "Cửa hàng": "shop_page",
    "Giỏ hàng": "cart",
    "Đơn mua của tôi": "my_orders",
    "Khác": "other",
}
#: Seller Centre's level-2 source labels (``… › Theo nguồn lưu lượng``, every Ory export
#: 11/2025-10/2026) → Juli's ``segment`` code, per L1 source (ADR-117 §1). An L2 row is a
#: breakdown of its L1 total (segment ``all``) and is never added to it. A label not
#: listed is refused (422), never filed under ``other``.
SHOPEE_L2_SOURCES: dict[str, dict[str, str]] = {
    "psd_label_product_card": {**_CARD_LIKE, "Khuyến mãi": "promo", "Chat": "chat"},
    "psd_label_seller_live": {
        **_CARD_LIKE,
        "Thẻ Live": "live_tab",
        "Trang chủ Shopee Live": "live_home",
        "Video": "video",
    },
    "psd_label_seller_video": {
        **_CARD_LIKE,
        "Thẻ Video": "video_tab",
        "Trang chủ Shopee Video": "video_home",
    },
    "psd_label_affiliate": {"Affiliate Live": "aff_live", "Affiliate Video": "aff_video"},
    "psd_label_shopee_ads": {
        "Quảng cáo GMV tối đa ROAS tùy chỉnh cho sản phẩm": "ads_roas_custom",
        "Quảng cáo GMV tối đa tự động đấu thầu cho sản phẩm": "ads_auto_bid",
        "Quảng cáo cửa hàng": "ads_shop",
        "Product Ads (GMV Max-Shop)": "ads_gmvmax_shop",
        "Khác": "other",
    },
}
#: Seller Centre's promotion types (``discount`` › ``Biểu đồ`` / ``Danh sách hiệu suất``)
#: → Juli's code. ``all`` is Shopee's own total row.
SHOPEE_PROMO_TYPES: dict[str, str] = {
    "Tất cả": "all",
    "Khuyến Mãi": "discount",
    "Chương Trình Khuyến Mãi": "discount",
    "Combo Khuyến Mãi": "bundle",
    "Mua Kèm Deal Sốc": "add_on_deal",
    "Flash Sale": "flash_sale",
    "Voucher": "voucher",
}


class DatasetRow(BaseModel):
    """Every dataset row: an open ``extra`` object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    extra: dict[ExtraKey, ExtraValue] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _extra_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_EXTRA_KEYS:
            raise ValueError(f"extra has more than {MAX_EXTRA_KEYS} keys")
        # D16: numbers, booleans and nulls only -- a string is dropped, never stored.
        return {key: item for key, item in value.items() if not isinstance(item, str)}

    def key(self) -> tuple[Any, ...]:
        return ()


class RowBase(DatasetRow):
    """A daily row: its platform calendar day."""

    date: date

    def key(self) -> tuple[Any, ...]:
        return (self.date,)


class PeriodRowBase(DatasetRow):
    """A row that totals the body's whole period (``granularity: "period"``, ADR-117 §2)."""


class _SourceMetricFields(BaseModel):
    """The per-source metric set of ``/api/mydata/v1/product/traffic/overview/``."""

    source: ShopeeL1Source
    #: The L2 label (``SHOPEE_L2_SOURCES``); None on the L1 total row.
    sub_source: Annotated[str, StringConstraints(max_length=120)] | None = None
    sales: Money | None = None
    orders: Count | None = None
    units: Count | None = None
    buyers: Count | None = None
    product_impressions: Count | None = None
    unique_product_impressions: Count | None = None
    product_clicks: Count | None = None
    unique_product_clicks: Count | None = None
    ctr: Rate | None = None
    product_clicks_to_orders_rate: Rate | None = None
    conversion: Rate | None = None
    sales_per_order: Money | None = None
    live_views: Count | None = None
    live_viewers: Count | None = None
    video_views: Count | None = None
    video_viewers: Count | None = None
    content_views: Count | None = None
    content_viewers: Count | None = None
    ads_impressions: Count | None = None
    ads_expense: Money | None = None
    ads_roas: Ratio | None = None

    @model_validator(mode="after")
    def _known_sub_source(self) -> _SourceMetricFields:
        if self.sub_source is not None and self.sub_source not in SHOPEE_L2_SOURCES[self.source]:
            raise ValueError(f"unknown sub_source for {self.source}")
        return self


class ShopeeSourceMetrics(RowBase, _SourceMetricFields):
    """One day of the per-source metric set."""

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.source, self.sub_source)


class ShopeeTrafficOverviewRow(ShopeeSourceMetrics):
    """``shopee.traffic_overview``: one day × one L1 source, shop totals."""


class ShopeeItemBySourceRow(ShopeeSourceMetrics):
    """``shopee.item_by_source``: one day × one item × one L1 source.

    PROVISIONAL: ``/api/mydata/v1/product/traffic/item-list/`` returned no
    items in the first recon; the item row's own field names are pinned by the
    D31.6 second recon. Until then the extension maps whatever it can onto the
    source metric names above and puts the rest in ``extra``.
    """

    item_id: ItemId
    item_name: Annotated[str, StringConstraints(max_length=255)] | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.item_id, self.source, self.sub_source)


class ShopeeItemPerformanceRow(RowBase):
    """``shopee.item_performance``: one day × one item, all sources.

    PROVISIONAL like ``item_by_source`` (``/api/mydata/v4/product/performance/``
    items were empty): the names follow the shop-level overview (``uv``,
    ``atc_uv``, ``atc_rate``) with the order-type prefix stripped by the source.
    """

    item_id: ItemId
    item_name: Annotated[str, StringConstraints(max_length=255)] | None = None
    sales: Money | None = None
    orders: Count | None = None
    units: Count | None = None
    buyers: Count | None = None
    product_impressions: Count | None = None
    product_clicks: Count | None = None
    ctr: Rate | None = None
    uv: Count | None = None
    pv: Count | None = None
    atc_uv: Count | None = None
    atc_units: Count | None = None
    atc_rate: Rate | None = None
    conversion_rate: Rate | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.item_id)


class ShopeeShopTrafficRow(RowBase):
    """``shopee.shop_traffic``: ``/api/mydata/traffic/dashboard/*`` per day × device."""

    device: Literal["all", "pc", "app"]
    visitors: Count | None = None
    page_views: Count | None = None
    avg_page_views: Count | None = None
    avg_stay_time: Count | None = None  # seconds
    bounce_rate: Rate | None = None
    new_visitors: Count | None = None
    existing_visitors: Count | None = None
    #: Net: Seller Centre shows a negative day when more buyers unfollowed.
    new_followers: SignedCount | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.device)


class _ShopOverviewFields(BaseModel):
    """The shop-level metric set of Phân tích bán hàng › Tổng quan (one order type per post)."""

    sales: Money | None = None
    sales_excl_shopee_subsidy: Money | None = None
    orders: Count | None = None
    sales_per_order: Money | None = None
    product_clicks: Count | None = None
    visitors: Count | None = None
    #: Not posted by the file loader: orders / visitors can exceed 1 on a tiny day (G-01),
    #: and readers recompute it from the counts. Kept for senders that do state it.
    conversion_rate: Rate | None = None
    cancelled_orders: Count | None = None
    cancelled_sales: Money | None = None
    returned_orders: Count | None = None
    returned_sales: Money | None = None
    buyers: Count | None = None
    new_buyers: Count | None = None
    existing_buyers: Count | None = None
    #: Net, like ``new_followers``: Seller Centre shows a small negative on some days.
    potential_buyers: SignedCount | None = None
    repeat_purchase_rate: Rate | None = None


class ShopeeShopOverviewRow(RowBase, _ShopOverviewFields):
    """``shopee.shop_overview``: one day, whole shop (Phân tích bán hàng › Tổng quan).

    One post per order type: the export has a sheet each for placed / confirmed / paid.
    """


class ShopeeShopOverviewPeriodRow(PeriodRowBase, _ShopOverviewFields):
    """``shopee.shop_overview_period``: the shop's totals over the body's period.

    A shop-stats workbook exported with the monthly granularity has one row per month
    (dated the 1st): each month is one post whose period is that month, never a day row.
    """


class ShopeeProductOverviewRow(RowBase):
    """``shopee.product_overview``: one day, the shop's product funnel (Sản phẩm › Tổng quan).

    The export holds placed and confirmed values in one row; the source posts each order
    type separately, repeating the order-independent fields.
    """

    product_visitors: Count | None = None
    product_page_views: Count | None = None
    products_visited: Count | None = None
    bounced_visitors: Count | None = None
    bounce_rate: Rate | None = None
    search_clicks: Count | None = None
    likes: Count | None = None
    atc_visitors: Count | None = None
    atc_units: Count | None = None
    atc_rate: Rate | None = None
    buyers: Count | None = None
    units: Count | None = None
    products_sold: Count | None = None
    sales: Money | None = None
    conversion_rate: Rate | None = None


class ShopeePromotionDailyRow(RowBase):
    """``shopee.promotion_daily``: one day x one promotion type (Khuyến mãi › Biểu đồ)."""

    promo_type: Annotated[str, StringConstraints(max_length=64)]
    sales: Money | None = None
    orders: Count | None = None
    units: Count | None = None
    buyers: Count | None = None
    sales_per_buyer: Money | None = None

    @field_validator("promo_type")
    @classmethod
    def _known_promo_type(cls, value: str) -> str:
        if value not in SHOPEE_PROMO_TYPES:
            raise ValueError("unknown promo_type")
        return value

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.promo_type)


# -- period rows (``period.granularity == "period"``, ADR-117 §2) ----------------------


class ShopeeTrafficOverviewPeriodRow(PeriodRowBase, _SourceMetricFields):
    """``shopee.traffic_overview_period``: the period's total per L1 / L2 source."""

    def key(self) -> tuple[Any, ...]:
        return (self.source, self.sub_source)


class ShopeeItemBySourcePeriodRow(PeriodRowBase, _SourceMetricFields):
    """``shopee.item_by_source_period``: the period's total per item x L1 source
    (Tổng quan › ``Theo sản phẩm``)."""

    item_id: ItemId
    item_name: Annotated[str, StringConstraints(max_length=500)] | None = None
    item_status: Annotated[str, StringConstraints(max_length=64)] | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.item_id, self.source, self.sub_source)


class ShopeeProductPeriodRow(PeriodRowBase):
    """``shopee.product_period``: the period's total per item or variation
    (``parentskudetail`` › ``Sản Phẩm Hiệu Quả Tốt``; ``variation_id`` empty = the item).

    The export holds placed and confirmed values in one row; the source posts each order
    type separately, repeating the order-independent fields.
    """

    item_id: ItemId
    variation_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{0,32}$")] = ""
    item_name: Annotated[str, StringConstraints(max_length=500)] | None = None
    variation_name: Annotated[str, StringConstraints(max_length=255)] | None = None
    item_status: Annotated[str, StringConstraints(max_length=64)] | None = None
    variation_status: Annotated[str, StringConstraints(max_length=64)] | None = None
    seller_sku: Annotated[str, StringConstraints(max_length=100)] | None = None
    sales: Money | None = None
    orders: Count | None = None
    units: Count | None = None
    buyers: Count | None = None
    product_impressions: Count | None = None
    product_clicks: Count | None = None
    ctr: Rate | None = None
    unique_product_impressions: Count | None = None
    unique_product_clicks: Count | None = None
    product_clicks_to_orders_rate: Rate | None = None
    conversion_rate: Rate | None = None
    sales_per_order: Money | None = None
    product_visitors: Count | None = None
    product_page_views: Count | None = None
    bounced_visitors: Count | None = None
    bounce_rate: Rate | None = None
    search_clicks: Count | None = None
    likes: Count | None = None
    atc_visitors: Count | None = None
    atc_units: Count | None = None
    atc_rate: Rate | None = None
    repeat_purchase_rate: Rate | None = None
    repeat_purchase_days: Annotated[Decimal, Field(ge=0, le=10_000)] | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.item_id, self.variation_id)


class ShopeeProductFlagRow(PeriodRowBase):
    """``shopee.product_flags``: an item Seller Centre listed in one of its flag sheets for
    the period (``parentskudetail``: Sản Phẩm Mới, Giá (không) cạnh tranh, … DVHT)."""

    item_id: ItemId
    flag: Literal[
        "new_product",
        "price_competitive",
        "price_uncompetitive",
        "ads_grow",
        "ads_optimize",
        "ads_track",
    ]

    def key(self) -> tuple[Any, ...]:
        return (self.item_id, self.flag)


class ShopeePromotionRow(PeriodRowBase):
    """``shopee.promotions``: one program's results over the period
    (Khuyến mãi › ``Danh sách hiệu suất``). Run times are Seller Centre's wall clock."""

    program_name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    promo_type: Annotated[str, StringConstraints(max_length=64)]
    starts_at: datetime
    ends_at: datetime | None = None
    #: Place among the export's programs sharing type, name and start (no program id).
    ordinal: Annotated[int, Field(ge=0, le=999)] = 0
    status: Annotated[str, StringConstraints(max_length=64)] | None = None
    sales: Money | None = None
    orders: Count | None = None
    units: Count | None = None
    buyers: Count | None = None
    sales_per_buyer: Money | None = None

    @field_validator("promo_type")
    @classmethod
    def _known_promo_type(cls, value: str) -> str:
        if value not in SHOPEE_PROMO_TYPES:
            raise ValueError("unknown promo_type")
        return value

    def key(self) -> tuple[Any, ...]:
        return (self.promo_type, self.program_name, self.starts_at, self.ordinal)


class ShopeeAdsCampaignPeriodRow(PeriodRowBase):
    """``shopee.ads_campaign_period``: one ad campaign x product over the report's window
    (``Báo cáo Dịch vụ Hiển thị trả theo CPC``, ``Chiến dịch nhóm``).

    The export totals a window (about three months), not days, so it is a period row and is
    never spread over days. ``item_id`` is None for a shop-level campaign (no product). The
    campaign name is the seller's own listing text. Rates are fractions; ``acos`` and the
    ROAS fields are ratios that may exceed 1. Counts and money are the ad's own attribution
    (the report counts placed orders); ``direct_*`` is the same measure for the clicked
    product only.
    """

    campaign_name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    item_id: ItemId | None = None
    #: Place among rows sharing campaign and product in one export.
    ordinal: Annotated[int, Field(ge=0, le=999)] = 0
    running: bool | None = None
    ads_impressions: Count | None = None
    ad_clicks: Count | None = None
    ctr: Ratio | None = None
    add_to_cart: Count | None = None
    add_to_cart_rate: Ratio | None = None
    conversions: Count | None = None
    direct_conversions: Count | None = None
    conversion_rate: Ratio | None = None
    direct_conversion_rate: Ratio | None = None
    cost_per_conversion: Money | None = None
    direct_cost_per_conversion: Money | None = None
    units_sold: Count | None = None
    direct_units_sold: Count | None = None
    sales: Money | None = None
    direct_sales: Money | None = None
    ads_expense: Money | None = None
    ads_roas: Ratio | None = None
    direct_roas: Ratio | None = None
    acos: Ratio | None = None
    direct_acos: Ratio | None = None
    product_views: Count | None = None
    product_clicks: Count | None = None
    product_ctr: Ratio | None = None
    voucher_amount: Money | None = None
    voucher_sales: Money | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.campaign_name, self.item_id, self.ordinal)


# -- affiliate, ad keyword and promotion-total period rows (reco loader wave) ------------


class _AffiliateMetrics(PeriodRowBase):
    """What the affiliate dashboard exports share: ``Est.Commission(₫)`` and ``ROI`` are the
    program's own estimate (a ratio that may exceed 1), not an invoice."""

    sales: Money | None = None
    units: Count | None = None
    orders: Count | None = None
    clicks: Count | None = None
    buyers: Count | None = None
    new_buyers: Count | None = None
    est_commission: Money | None = None
    roi: Ratio | None = None


class ShopeeAffiliateProductPeriodRow(_AffiliateMetrics):
    """``shopee.affiliate_product_period``: one product's affiliate results over the period
    (``affiliate_product_YYYYMM.csv``, ``ProductPerformance_<ts>.csv``)."""

    item_id: ItemId
    price: Money | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.item_id,)


class ShopeeAffiliateOpenCampaignPeriodRow(PeriodRowBase):
    """``shopee.affiliate_open_campaign_period``: one product in the Open Campaign
    (``Open Campaign Analytics_<ts>.csv``): how many KOLs sold it, revenue, units, commission."""

    item_id: ItemId
    kols: Count | None = None
    sales: Money | None = None
    units: Count | None = None
    est_commission: Money | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.item_id,)


class ShopeeAffiliatePartnerPeriodRow(_AffiliateMetrics):
    """``shopee.affiliate_partner_period``: one affiliate (KOL) over the period
    (``AMSAffiliatePerformance_<ts>.csv``). ``account`` is the creator's public handle."""

    affiliate_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")]
    account: Annotated[str, StringConstraints(max_length=120)] | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.affiliate_id,)


class ShopeeAffiliateCampaignTermsRow(PeriodRowBase):
    """``shopee.affiliate_campaign_terms``: a commission-rate row of ``target_campaign_<ts>.csv``
    (campaign x product), as it stood on the export day. A terms snapshot, not a result."""

    campaign_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")]
    campaign_name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    item_id: ItemId
    commission_rate: Rate | None = None
    running: bool | None = None
    starts_on: date | None = None
    #: None = "No limit".
    ends_on: date | None = None
    #: The ``KOL cụ thể[N]`` count: how many specific KOLs the campaign targets.
    targeted_kols: Count | None = None
    ordinal: Annotated[int, Field(ge=0, le=999)] = 0

    def key(self) -> tuple[Any, ...]:
        return (self.campaign_id, self.item_id, self.ordinal)


class ShopeeAffiliateBillPeriodRow(PeriodRowBase):
    """``shopee.affiliate_bill_period``: one month's affiliate settlement
    (``ValidationBill<ts>.csv``)."""

    bill_code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    commission: Money | None = None
    tax: Money | None = None
    cost: Money | None = None
    total_deduction: Money | None = None
    wallet_offset: Money | None = None
    pending_amount: Money | None = None
    deduction_completed: bool | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.bill_code,)


class ShopeeAdsKeywordPeriodRow(ShopeeAdsCampaignPeriodRow):
    """``shopee.ads_keyword_period``: ``ads_keyword_<range>.csv``, one campaign x product x
    keyword over the window. ``keyword`` is None for a campaign-level or automatic-placement
    row (the ORY report lists ``-`` as the type and an "automatic ad" label as the keyword)."""

    keyword: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = None
    keyword_type: Annotated[str, StringConstraints(max_length=64)] | None = None
    #: True when the report's keyword column said "automatic ad" instead of a phrase.
    auto_placement: bool | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.campaign_name, self.item_id, self.keyword, self.keyword_type, self.ordinal)


class ShopeePromotionPeriodRow(PeriodRowBase):
    """``shopee.promotion_period``: a promotion type's total over the period
    (``In_Shop_Flash_Sale_Metrics`` › ``Tổng quan``). Not a sum of ``promotions`` rows."""

    promo_type: Annotated[str, StringConstraints(max_length=64)]
    sales: Money | None = None
    orders: Count | None = None
    buyers: Count | None = None
    sales_per_buyer: Money | None = None

    @field_validator("promo_type")
    @classmethod
    def _known_promo_type(cls, value: str) -> str:
        if value not in SHOPEE_PROMO_TYPES:
            raise ValueError("unknown promo_type")
        return value

    def key(self) -> tuple[Any, ...]:
        return (self.promo_type,)


# -- connector readers (reco connector wave, ADR-120 d.14) -------------------------------

#: A platform enum that Seller Centre sends as a number or as a short label.
Tag = Annotated[str, StringConstraints(max_length=64)] | int
_Digits = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")]
_MaybeDigits = Annotated[str, StringConstraints(pattern=r"^[0-9]{0,32}$")]
Percent = Annotated[Decimal, Field(ge=0, le=100, allow_inf_nan=False)]


class ShopeeItemCatalogRow(PeriodRowBase):
    """``shopee.item_catalog``: one item or variation as the Seller Centre product list
    names it (``variation_id`` empty = the item). Lands in ``platform_items`` only: names,
    SKU and status of the newest post; the prices and stock are ``item_snapshot``'s."""

    item_id: ItemId
    variation_id: _MaybeDigits = ""
    item_name: Annotated[str, StringConstraints(max_length=500)] | None = None
    variation_name: Annotated[str, StringConstraints(max_length=255)] | None = None
    seller_sku: Annotated[str, StringConstraints(max_length=100)] | None = None
    status: Annotated[str, StringConstraints(max_length=64)] | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.item_id, self.variation_id)


class ShopeeAdsCampaignDailyRow(RowBase):
    """``shopee.ads_campaign_daily`` (the name ADR-117 §3 reserved): one finished GMT+7 day of
    one ad campaign, from ``/api/pas/v1/homepage/query/`` called for that single day.

    Platform names are kept (``impression``, ``broad_gmv``, ``atc`` ...). ``broad_*`` is the
    attribution to every product of the shop, ``direct_*`` to the clicked product only; the
    order type of the post says whether Shopee counted placed or paid orders
    (``use_paid_gmv``). ``campaign_id`` None = the shop-level ROAS-target row that
    ``/api/pas/v1/report/get_time_graph/`` gives for the day (``roi_target``)."""

    campaign_id: _Digits | None = None
    campaign_name: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = None
    ad_type: Tag | None = None
    ad_subtype: Tag | None = None
    state: Tag | None = None
    daily_budget: Money | None = None
    total_budget: Money | None = None
    #: The campaign's own ROAS target setting (custom-ROAS campaigns).
    roi_two_target: Ratio | None = None
    impression: Count | None = None
    click: Count | None = None
    ctr: Ratio | None = None
    cost: Money | None = None
    cpc: Money | None = None
    cpm: Money | None = None
    broad_gmv: Money | None = None
    broad_order: Count | None = None
    broad_roi: Ratio | None = None
    broad_cir: Ratio | None = None
    direct_gmv: Money | None = None
    direct_order: Count | None = None
    direct_roi: Ratio | None = None
    direct_cir: Ratio | None = None
    product_impression: Count | None = None
    product_click: Count | None = None
    product_ctr: Ratio | None = None
    avg_rank: Ratio | None = None
    sov: Ratio | None = None
    reach: Count | None = None
    page_views: Count | None = None
    unique_visitors: Count | None = None
    checkout: Count | None = None
    atc: Count | None = None
    voucher_amount: Money | None = None
    voucher_sales: Money | None = None
    #: Shop-level row only: the ROAS target in force that day, and whether it is Shopee's
    #: cold-start default.
    roi_target: Ratio | None = None
    roi_target_cold_start: bool | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.campaign_id)


class ShopeeVoucherSettingRow(PeriodRowBase):
    """``shopee.voucher_settings``: one shop voucher's settings and live usage on the day
    the connector read ``/api/marketing/v3/voucher/list/`` (the post's one-day period).
    Results (sales, orders) stay in the ``voucher_*.xlsx`` export. Lands in
    ``platform_promotions`` as ``promo_type = voucher``; ``voucher_code`` is kept in the raw
    copy only (a string in ``extra`` is dropped, D16)."""

    voucher_id: _Digits
    program_name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    voucher_code: Annotated[str, StringConstraints(max_length=64)] | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    status: Annotated[str, StringConstraints(max_length=64)] | None = None
    #: VND off (a fixed-amount voucher).
    discount_amount: Money | None = None
    #: Percent off, 0..100 (a percentage voucher).
    discount_percent: Percent | None = None
    max_value: Money | None = None
    #: Minimum basket spend.
    min_spend: Money | None = None
    usage_limit: Count | None = None
    current_usage: Count | None = None
    distributed_count: Count | None = None
    usage_limit_per_user: Count | None = None
    use_type: int | None = None
    reward_type: int | None = None
    purpose: int | None = None
    is_seller_absorbed: bool | None = None
    #: How many items the voucher is limited to (0 = no item list: the whole shop).
    item_count: Count | None = None
    item_scope: Annotated[str, StringConstraints(max_length=16)] | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.voucher_id,)


#: ``item_traffic_sources`` (the Connector's per-product ``traffic/details`` read): the level-1
#: stream and the level-2 source of one row. ``total`` is the L1 total (``segment = 'all'``).
#: A level-2 label may come with or without Seller Centre's ``psd_label_`` prefix.
ITEM_TRAFFIC_L1: tuple[str, ...] = ("product_card", "live", "video", "affiliate")
ITEM_TRAFFIC_L2: dict[str, str] = {
    "total": "all",
    "search": "search",
    "recommendation": "recommend",
    "my_purchase": "my_orders",
    "shopping_cart": "cart",
    "shop": "shop_page",
    "promotion": "promo",
    "others": "other",
}


class ShopeeItemTrafficSourceRow(RowBase):
    """``shopee.item_traffic_sources``: one finished day x one item x L1 stream x L2 source, from
    ``/api/mydata/v1/product/traffic/details/`` (one call per item and day, confirmed orders).
    Numbers only: the ratios and ``pct_diff`` of the response are dropped by the sender. An L2
    row is a breakdown of its L1 ``total`` row and is never added to it."""

    item_id: ItemId
    l1: Literal["product_card", "live", "video", "affiliate"]
    l2: str
    sales: Money | None = None
    orders: Count | None = None
    units: Count | None = None
    buyers: Count | None = None
    product_impressions: Count | None = None
    unique_product_impressions: Count | None = None
    product_clicks: Count | None = None
    unique_product_clicks: Count | None = None

    @field_validator("l2")
    @classmethod
    def _known_l2(cls, value: str) -> str:
        name = value.removeprefix("psd_label_")
        if name not in ITEM_TRAFFIC_L2:
            raise ValueError("unknown l2 source")
        return name

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.item_id, self.l1, self.l2)


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    #: ``day``: each row is one day inside the period; ``period``: each row totals it.
    granularity: Literal["day", "period"]

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period.end is before period.start")
        # The hard ceiling; a dataset's own, shorter limit is checked in ``validate_rows``.
        if (self.end - self.start).days + 1 > MAX_ADS_PERIOD_DAYS:
            raise ValueError(f"period is longer than {MAX_ADS_PERIOD_DAYS} days")
        return self


class IngestBody(BaseModel):
    """``POST /v1/ingest/{platform}/{dataset}``. ``rows`` are checked per dataset."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["extension", "file", "api", "vendor"]
    source_version: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._+\-]{1,64}$")]
    captured_at: AwareDatetime
    period: Period
    order_type: Literal["placed", "paid", "confirmed"] | None = None
    #: The platform's own shop id as the source saw it (Seller Centre shop id).
    platform_shop_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")] | None = None
    rows: list[dict[str, Any]] = Field(max_length=MAX_ROWS)


class DriftReport(BaseModel):
    """``POST /v1/ingest/status``: the extension saw unexpected / missing fields."""

    model_config = ConfigDict(extra="forbid")

    platform: Literal["shopee", "tiktok"]
    dataset: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,48}$")]
    state: Literal["drift", "ok"]
    source_version: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._+\-]{1,64}$")]
    endpoint: Annotated[str, StringConstraints(max_length=200)] | None = None
    unexpected: list[Annotated[str, StringConstraints(max_length=120)]] = Field(
        default_factory=list, max_length=100
    )
    missing: list[Annotated[str, StringConstraints(max_length=120)]] = Field(
        default_factory=list, max_length=100
    )
    observed_at: datetime | None = None


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, StringConstraints(min_length=6, max_length=32)]
    platform: Literal["shopee", "tiktok"] = "shopee"
    platform_shop_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")] | None = None
    client_label: Annotated[str, StringConstraints(max_length=120)] | None = None


# -- order lines, ad change log, item snapshots, shop health (P90 step 2, migration 113) --

Text64 = Annotated[str, StringConstraints(max_length=64)]
Text120 = Annotated[str, StringConstraints(max_length=120)]


ORDER_STATUSES: tuple[str, ...] = (
    "delivered",
    "cancelled",
    "in_transit",
    "refunded_accepted",
    "refunded_not_received",
)
OrderStatusName = Literal[
    "delivered", "cancelled", "in_transit", "refunded_accepted", "refunded_not_received"
]
PROMO_KIND_NAMES = Literal["none", "voucher", "discount", "flash_sale", "bundle", "add_on"]


class ShopeeOrderLineRow(PeriodRowBase):
    """``order_lines``: one line of an order export (Đơn hàng › Xuất), PII-stripped before it
    reaches here. There is no field for a buyer, a recipient, an address, a contact number,
    a tracking id, a comment or a note, and the raw order id never arrives: ``order_ref`` is a
    keyed hash.

    Money is VND. ``status`` is the contract-10 ``OrderStatus`` value. Order-level amounts
    (shop voucher, Shopee voucher, combo, buyer shipping, bank promotion, actual fees) are
    already SPLIT across the order's lines by line value (``Σ`` of the lines is the order's
    amount); fees are None when the export left them unfilled (never 0). The item is known
    by SKU (the export has no numeric item id); ``item_id`` is filled by the gateway from
    ``platform_items.seller_sku`` when the catalogue knows the SKU."""

    order_ref: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    #: Place of the line in its order after a canonical sort (stable across downloads).
    line_no: Annotated[int, Field(ge=0, le=999)] = 0
    ordered_at: datetime
    status: OrderStatusName
    sku: Text120 | None = None
    variation_sku: Text120 | None = None
    qty: Count
    returned_qty: Count = Decimal(0)
    original_price: Money
    deal_price: Money
    #: Seller-funded promotion on the line (original - deal) x qty, and Shopee-funded.
    seller_subsidy: Money = Decimal(0)
    shopee_subsidy: Money = Decimal(0)
    shop_voucher_share: Money = Decimal(0)
    #: Shopee-funded voucher and Shopee combo discount (not a seller cost).
    platform_voucher_share: Money = Decimal(0)
    #: The shop's own combo (Combo khuyến mãi / Mua kèm) discount.
    bundle_discount: Money = Decimal(0)
    promo_kind: PROMO_KIND_NAMES = "none"
    buyer_shipping_fee: Money | None = None
    bank_promo: Money | None = None
    fee_fixed: Money | None = None
    fee_service: Money | None = None
    fee_payment: Money | None = None
    completed_at: datetime | None = None
    paid_at: datetime | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.order_ref, self.line_no)


class ShopeeAffiliateOrderLineRow(PeriodRowBase):
    """``affiliate_order_lines``: one affiliate-attributed order line. It marks the matching
    ``shopee_order_lines`` row (``affiliate`` true, ``commission`` from ``cost``) and never
    creates one: the order export owns the line."""

    #: Keyed hash of the order id (HMAC-SHA256, 32 hex): the same function the browser-side
    #: order strip uses, so the two lanes agree on an order.
    order_ref: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    #: Place among lines sharing order, item and model in one export.
    line_no: Annotated[int, Field(ge=0, le=999)] = 0
    affiliate: bool = True
    item_id: ItemId
    model_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{0,32}$")] = ""
    price: Money | None = None
    qty: Count | None = None
    order_value: Money | None = None
    refund_amount: Money | None = None
    order_status: Text64 | None = None
    #: False when the platform's fraud check did not say "valid".
    valid: bool | None = None
    ordered_at: datetime
    completed_at: datetime | None = None
    conversion_at: datetime | None = None
    campaign_type: Text64 | None = None
    campaign_partner: Text120 | None = None
    commission_code: Text64 | None = None
    #: The creator's public account handle (not a buyer); the display name is not read.
    affiliate_account: Text120 | None = None
    mcn: Text120 | None = None
    order_kind: Text64 | None = None
    channel: Text64 | None = None
    xtra_product_commission: Money | None = None
    xtra_product_commission_kols: Money | None = None
    xtra_product_commission_kols_rate: Rate | None = None
    xtra_product_commission_mcn: Money | None = None
    xtra_product_commission_mcn_rate: Rate | None = None
    xtra_order_commission: Money | None = None
    xtra_order_commission_kols: Money | None = None
    xtra_order_commission_mcn: Money | None = None
    cost: Money | None = None
    deduction_status: Text64 | None = None
    deduction_method: Text64 | None = None
    deducted_at: datetime | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.order_ref, self.item_id, self.model_id, self.line_no)


class ShopeeAdsChangeLogRow(PeriodRowBase):
    """``ads_change_log``: one line of an ad campaign's change history (``ops_log_*.csv``).
    Times are Seller Centre's wall clock (GMT+7)."""

    campaign_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")]
    item_id: ItemId | None = None
    occurred_at: datetime
    #: ``system`` = Shopee's own optimiser; ``user`` = a person or sub-account of the shop.
    actor_kind: Annotated[str, StringConstraints(pattern=r"^(system|user)$")]
    actor: Text120 | None = None
    surface: Text64 | None = None
    event_type: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    detail: Annotated[str, StringConstraints(max_length=500)] | None = None
    #: Parsed from "Ngân sách hàng ngày: ₫a -> ₫b".
    budget_from: Money | None = None
    budget_to: Money | None = None
    #: Parsed from "Thay đổi số lượng sản phẩm …: a -> b".
    products_from: Count | None = None
    products_to: Count | None = None
    ordinal: Annotated[int, Field(ge=0, le=999)] = 0

    def key(self) -> tuple[Any, ...]:
        return (self.campaign_id, self.occurred_at, self.event_type, self.ordinal)


class ShopeeItemSnapshotRow(PeriodRowBase):
    """``item_snapshot``: one item (``model_id`` empty) or one of its models on the day the
    Connector read the Seller Centre product list. Item rows carry the item's price range,
    stock totals, counts and tags; model rows carry the model's own price and stock.
    Money in VND; ``discount_percent`` 0..100; times are timezone-aware."""

    item_id: ItemId
    model_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{0,32}$")] = ""
    #: Cover image (item row) or the model's image: Seller Centre's image id / URL.
    image: Annotated[str, StringConstraints(max_length=300)] | None = None
    create_time: datetime | None = None
    modify_time: datetime | None = None
    price_min: Money | None = None
    price_max: Money | None = None
    selling_price_min: Money | None = None
    selling_price_max: Money | None = None
    origin_price: Money | None = None
    promotion_price: Money | None = None
    has_discount: bool | None = None
    discount_percent: Percent | None = None
    max_discount: Money | None = None
    total_available_stock: Count | None = None
    total_seller_stock: Count | None = None
    total_shopee_stock: Count | None = None
    sellable_stock: Count | None = None
    in_transit_stock: Count | None = None
    low_stock_status: Tag | None = None
    view_count: Count | None = None
    liked_count: Count | None = None
    sold_count: Count | None = None
    promo_has_discount: bool | None = None
    promo_has_bundle_deal: bool | None = None
    promo_has_add_on_deal: bool | None = None
    promo_has_ams_commission: bool | None = None
    promo_wholesale: bool | None = None
    unlisted: bool | None = None
    #: Active campaigns the item is in (``get_campaign_info_by_item_list``), when read.
    campaign_count: Count | None = None
    tier_index: Annotated[str, StringConstraints(max_length=32)] | None = None
    is_default: bool | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.item_id, self.model_id)


class ShopeeShopHealthDailyRow(RowBase):
    """``shop_health_daily``: one Seller Centre account-health metric on one day
    (``/api/accounthealth/v1/sc/shops/metric_list`` + ``metric/configs``); ``metric_id`` None
    is the day's overview row (failed-metric count, penalty points, rating)."""

    metric_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")] | None = None
    #: The metric's title from ``metric/configs``.
    label: Annotated[str, StringConstraints(max_length=255)] | None = None
    display_value: Annotated[str, StringConstraints(max_length=64)] | None = None
    value: SignedCount | None = None
    target_display: Annotated[str, StringConstraints(max_length=64)] | None = None
    target: SignedCount | None = None
    compare_result: Tag | None = None
    #: Derived from ``compare_result`` when it says so unambiguously; None otherwise.
    passed: bool | None = None
    metric_tag: Tag | None = None
    failed_metric_count: Count | None = None
    penalty_point: Count | None = None
    performance_rating: Tag | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.metric_id)
