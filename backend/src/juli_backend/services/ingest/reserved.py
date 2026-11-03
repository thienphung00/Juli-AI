"""Dataset names the loader parses but the gateway does not accept yet.

Four datasets have no home in ``platform_period_metrics`` /
``platform_daily_metrics`` / ``platform_promotions`` (ADR-117 §1-§3):

- ``affiliate_order_lines`` -- ``SellerConversionReport_<ts>.csv``: one row per affiliate
  order LINE. It belongs in ``shopee_order_lines`` (migration 112, another lane) with
  ``affiliate = true`` and the commission fields. The raw order id never leaves the
  parser: ``order_ref`` is a keyed hash (``scripts.shopee_exports.parse.order_ref``).
- ``ads_change_log`` -- ``ops_log_*.csv``: the ad change history (budget changes, product
  changes, Shopee's automatic surge optimisation). Append-only events; needs a table.
- ``item_snapshot`` -- the Juli Connector's product-list reader (ADR-120 d.14): price, discount,
  stock per model, view / like / sold counts, images and promo tags of each item and model,
  read once a day. Append-only, written on change: ``platform_item_snapshots`` (migration 112,
  branch ``fasttrack/reco-schema-112``). The identity half (name, SKU, status) already lands
  through the live ``item_catalog`` dataset in ``platform_items``.
- ``shop_health_daily`` -- the Connector's account-health reader: one row per Shopee shop
  metric per day (value, target, pass / fail) plus the day's overview row. Not a KPI row of
  ``platform_daily_metrics`` (its columns are traffic KPIs); it needs a table of its own.

TODO(migration 112 / ad change log table): when the table and its dataset spec exist, move the
row model into ``schemas.py``, register the spec in ``mapping.DATASETS`` and delete the name
from :data:`RESERVED_DATASETS`. Until then the loader validates these bodies here, prints
their counts under "reserved", and never sends them (the gateway answers 404 for the name).

No buyer data: the models have no field for a buyer's name, phone or address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field, StringConstraints

from juli_backend.services.ingest.schemas import (
    Count,
    DatasetRow,
    IngestBody,
    ItemId,
    Money,
    Percent,
    PeriodRowBase,
    Rate,
    RowBase,
    SignedCount,
    Tag,
)

Text64 = Annotated[str, StringConstraints(max_length=64)]
Text120 = Annotated[str, StringConstraints(max_length=120)]


class ShopeeAffiliateOrderLineRow(PeriodRowBase):
    """``affiliate_order_lines``: one affiliate-attributed order line, ready for
    ``shopee_order_lines`` (``affiliate`` is always true)."""

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
    #: The creator's public display name and handle (not a buyer).
    partner_name: Text120 | None = None
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


@dataclass(frozen=True)
class ReservedDataset:
    name: str
    row_model: type[DatasetRow]
    #: Where the rows are meant to land once the gateway accepts the name.
    target: str


RESERVED_DATASETS: dict[str, ReservedDataset] = {
    "affiliate_order_lines": ReservedDataset(
        "affiliate_order_lines", ShopeeAffiliateOrderLineRow, "shopee_order_lines (migration 112)"
    ),
    "ads_change_log": ReservedDataset(
        "ads_change_log", ShopeeAdsChangeLogRow, "an ad change log table (no migration yet)"
    ),
    "item_snapshot": ReservedDataset(
        "item_snapshot",
        ShopeeItemSnapshotRow,
        "platform_item_snapshots (migration 112, branch fasttrack/reco-schema-112)",
    ),
    "shop_health_daily": ReservedDataset(
        "shop_health_daily", ShopeeShopHealthDailyRow, "a shop-health table (no migration yet)"
    ),
}


def validate_reserved(dataset: str, body: IngestBody) -> None:
    """Validate a reserved body's rows (and refuse duplicate keys) like ``validate_rows``;
    raises ``pydantic.ValidationError`` or ``ValueError``."""
    spec = RESERVED_DATASETS[dataset]
    seen: set[tuple[Any, ...]] = set()
    for raw in body.rows:
        row = spec.row_model.model_validate(raw)
        key = row.key()
        if key in seen:
            raise ValueError(f"duplicate row key in {dataset}")
        seen.add(key)
