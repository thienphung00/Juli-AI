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
MAX_EXTRA_KEYS = 60
MAX_EXTRA_STRING = 200

_BIG = Decimal("1e15")

Count = Annotated[Decimal, Field(ge=0, le=_BIG, allow_inf_nan=False)]
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


class RowBase(BaseModel):
    """Every dataset row: its platform calendar day and an open ``extra`` object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    date: date
    extra: dict[ExtraKey, ExtraValue] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _extra_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_EXTRA_KEYS:
            raise ValueError(f"extra has more than {MAX_EXTRA_KEYS} keys")
        # D16: numbers, booleans and nulls only -- a string is dropped, never stored.
        return {key: item for key, item in value.items() if not isinstance(item, str)}

    def key(self) -> tuple[Any, ...]:
        return (self.date,)


class ShopeeSourceMetrics(RowBase):
    """The per-source metric set of ``/api/mydata/v1/product/traffic/overview/``."""

    source: ShopeeL1Source
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
    ads_expense: Money | None = None
    ads_roas: Ratio | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.source)


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
        return (self.date, self.item_id, self.source)


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
    new_followers: Count | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.date, self.device)


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    granularity: Literal["day"]

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end < self.start:
            raise ValueError("period.end is before period.start")
        if (self.end - self.start).days + 1 > MAX_PERIOD_DAYS:
            raise ValueError(f"period is longer than {MAX_PERIOD_DAYS} days")
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
