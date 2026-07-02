"""Parquet column contracts for P1.5 backtest datasets."""

from __future__ import annotations

RETURN_TYPE_VALUES = frozenset({"item_swap", "empty_return", "other"})
RETURN_CONDITION_VALUES = frozenset(
    {"wrong_item", "empty_parcel", "correct_item", "unknown"}
)
RETURN_STATUS_VALUES = frozenset({"pending_review", "approved", "rejected"})

ORDERS_COLUMNS: tuple[str, ...] = (
    "order_id",
    "tiktok_order_id",
    "shop_id",
    "buyer_id",
    "status",
    "order_value",
    "currency",
    "payment_time",
    "ship_time",
    "delivery_time",
    "created_at",
    "cancel_reason",
    "is_seller_fault",
)

ORDER_ITEMS_COLUMNS: tuple[str, ...] = (
    "id",
    "order_id",
    "tiktok_order_id",
    "product_id",
    "sku_id",
    "quantity",
    "unit_price",
    "line_total",
)

RETURNS_COLUMNS: tuple[str, ...] = (
    "return_id",
    "tiktok_return_id",
    "order_id",
    "tiktok_order_id",
    "shop_id",
    "buyer_id",
    "product_id",
    "sku_id",
    "return_type",
    "return_condition",
    "return_reason",
    "refund_amount",
    "status",
    "created_at",
)

LABELS_COLUMNS: tuple[str, ...] = (
    "return_id",
    "ground_truth_anomaly",
    "return_type",
)

ADS_COLUMNS: tuple[str, ...] = (
    "shop_id",
    "campaign_id",
    "campaign_name",
    "date",
    "spend_vnd",
    "impressions",
    "clicks",
    "conversions",
    "roas",
    "cpc_vnd",
)

REQUIRED_PARQUET_FILES: tuple[str, ...] = (
    "orders.parquet",
    "order_items.parquet",
    "returns.parquet",
    "labels.parquet",
    "ads.parquet",
)
