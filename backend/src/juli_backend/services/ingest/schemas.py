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


class ShopeeShopOverviewRow(RowBase):
    """``shopee.shop_overview``: one day, whole shop (Phân tích bán hàng › Tổng quan).

    One post per order type: the export has a sheet each for placed / confirmed / paid.
    """

    sales: Money | None = None
    sales_excl_shopee_subsidy: Money | None = None
    orders: Count | None = None
    sales_per_order: Money | None = None
    product_clicks: Count | None = None
    visitors: Count | None = None
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
