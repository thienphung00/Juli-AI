"""Platform rows → Juli's normalized daily rows (pure; D31.1 / D31.3).

Shopee's level-1 traffic sources map onto Juli's stream frame (the same four
streams as TikTok, ads as an overlay row):

    psd_label_product_card  → product_card   Thẻ sản phẩm
    psd_label_seller_video  → seller_video   Video
    psd_label_seller_live   → seller_live    Live
    psd_label_affiliate     → affiliate      Tiếp thị liên kết
    psd_label_shopee_ads    → ads            Dịch vụ Hiển thị (overlay, not additive)

and their fields onto Juli's KPI columns (``impressions``, ``clicks``, ``ctr``,
``orders``, ``gmv``, ``buyers``, ``visitors``, ``add_to_cart``, plus ``units``,
``page_views``, ``bounce_rate``). Every other non-null field, and the row's own
``extra``, is kept in ``extra`` under its platform name -- except a string value
of the open ``extra``, which is dropped (free text; owner decision D16).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from juli_backend.models.ingest import ORDER_TYPE_NONE, SEGMENT_ALL, SHOP_LEVEL_ITEM
from juli_backend.services.ingest.schemas import (
    RowBase,
    ShopeeItemBySourceRow,
    ShopeeItemPerformanceRow,
    ShopeeShopTrafficRow,
    ShopeeTrafficOverviewRow,
)

STREAM_PRODUCT_CARD = "product_card"
STREAM_SELLER_VIDEO = "seller_video"
STREAM_SELLER_LIVE = "seller_live"
STREAM_AFFILIATE = "affiliate"
STREAM_ADS = "ads"
STREAM_TOTAL = "total"

STREAM_LABELS: dict[str, str] = {
    STREAM_PRODUCT_CARD: "Thẻ sản phẩm",
    STREAM_SELLER_VIDEO: "Video",
    STREAM_SELLER_LIVE: "Live",
    STREAM_AFFILIATE: "Tiếp thị liên kết",
    STREAM_ADS: "Dịch vụ Hiển thị",
    STREAM_TOTAL: "Tổng",
}
#: Overlay streams: shown as their own row, never summed into the shop total.
OVERLAY_STREAMS: frozenset[str] = frozenset({STREAM_ADS})

SHOPEE_L1_TO_STREAM: dict[str, str] = {
    "psd_label_product_card": STREAM_PRODUCT_CARD,
    "psd_label_seller_video": STREAM_SELLER_VIDEO,
    "psd_label_seller_live": STREAM_SELLER_LIVE,
    "psd_label_affiliate": STREAM_AFFILIATE,
    "psd_label_shopee_ads": STREAM_ADS,
}

KPI_COLUMNS: tuple[str, ...] = (
    "impressions",
    "clicks",
    "ctr",
    "orders",
    "gmv",
    "buyers",
    "visitors",
    "add_to_cart",
    "units",
    "page_views",
    "bounce_rate",
)

#: Shopee source-metric field → Juli KPI column.
_SOURCE_KPIS: dict[str, str] = {
    "product_impressions": "impressions",
    "product_clicks": "clicks",
    "ctr": "ctr",
    "orders": "orders",
    "sales": "gmv",
    "buyers": "buyers",
    "units": "units",
}
_ITEM_PERFORMANCE_KPIS: dict[str, str] = {
    "product_impressions": "impressions",
    "product_clicks": "clicks",
    "ctr": "ctr",
    "orders": "orders",
    "sales": "gmv",
    "buyers": "buyers",
    "units": "units",
    "uv": "visitors",
    "pv": "page_views",
    "atc_uv": "add_to_cart",
}
_SHOP_TRAFFIC_KPIS: dict[str, str] = {
    "visitors": "visitors",
    "page_views": "page_views",
    "bounce_rate": "bounce_rate",
}
#: Row fields that are part of the key, not metrics.
_KEY_FIELDS = frozenset({"date", "source", "item_id", "item_name", "device", "extra"})


@dataclass(frozen=True)
class NormalizedRow:
    day: date
    stream: str
    item_id: str = SHOP_LEVEL_ITEM
    platform_source: str | None = None
    segment: str = SEGMENT_ALL
    kpis: dict[str, Decimal] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def key(self, order_type: str) -> tuple[Any, ...]:
        return (self.day, self.item_id, self.stream, self.segment, order_type)


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _split(row: BaseModel, kpi_map: dict[str, str]) -> tuple[dict[str, Decimal], dict[str, Any]]:
    kpis: dict[str, Decimal] = {}
    extra: dict[str, Any] = {}
    for name, value in row:
        if name in _KEY_FIELDS or value is None:
            continue
        column = kpi_map.get(name)
        if column is not None:
            kpis[column] = value
        else:
            extra[name] = _json_number(value) if isinstance(value, Decimal) else value
    item_name = getattr(row, "item_name", None)
    if item_name:
        extra["item_name"] = item_name
    # D16: the open ``extra`` keeps numbers / booleans / nulls only (the row model
    # already drops its strings; this keeps the rule true for any row type).
    open_extra = getattr(row, "extra", {}) or {}
    extra.update({key: value for key, value in open_extra.items() if not isinstance(value, str)})
    return kpis, extra


def _source_row(row: ShopeeTrafficOverviewRow | ShopeeItemBySourceRow) -> NormalizedRow:
    kpis, extra = _split(row, _SOURCE_KPIS)
    return NormalizedRow(
        day=row.date,
        stream=SHOPEE_L1_TO_STREAM[row.source],
        item_id=getattr(row, "item_id", SHOP_LEVEL_ITEM),
        platform_source=row.source,
        kpis=kpis,
        extra=extra,
    )


def _item_performance(row: ShopeeItemPerformanceRow) -> NormalizedRow:
    kpis, extra = _split(row, _ITEM_PERFORMANCE_KPIS)
    return NormalizedRow(
        day=row.date, stream=STREAM_TOTAL, item_id=row.item_id, kpis=kpis, extra=extra
    )


def _shop_traffic(row: ShopeeShopTrafficRow) -> NormalizedRow:
    kpis, extra = _split(row, _SHOP_TRAFFIC_KPIS)
    return NormalizedRow(
        day=row.date, stream=STREAM_TOTAL, segment=row.device, kpis=kpis, extra=extra
    )


@dataclass(frozen=True)
class DatasetSpec:
    platform: str
    name: str
    row_model: type[RowBase]
    normalize: Callable[[Any], NormalizedRow]
    #: Whether the platform's numbers depend on "Loại Đơn Hàng" (placed/paid/confirmed).
    has_order_type: bool
    description: str


DATASETS: dict[tuple[str, str], DatasetSpec] = {
    ("shopee", "traffic_overview"): DatasetSpec(
        "shopee",
        "traffic_overview",
        ShopeeTrafficOverviewRow,
        _source_row,
        True,
        "Per day, per L1 source, shop totals (Lưu lượng truy cập sản phẩm › Theo nguồn).",
    ),
    ("shopee", "item_by_source"): DatasetSpec(
        "shopee",
        "item_by_source",
        ShopeeItemBySourceRow,
        _source_row,
        True,
        "Per day, per item × L1 source (Lưu lượng truy cập sản phẩm › Theo sản phẩm).",
    ),
    ("shopee", "item_performance"): DatasetSpec(
        "shopee",
        "item_performance",
        ShopeeItemPerformanceRow,
        _item_performance,
        True,
        "Per day, per item, all sources (Hiệu quả của sản phẩm).",
    ),
    ("shopee", "shop_traffic"): DatasetSpec(
        "shopee",
        "shop_traffic",
        ShopeeShopTrafficRow,
        _shop_traffic,
        False,
        "Per day shop visitors / page views / bounce, device split (Truy cập).",
    ),
}


def dataset_spec(platform: str, dataset: str) -> DatasetSpec | None:
    return DATASETS.get((platform, dataset))


def normalize_rows(spec: DatasetSpec, rows: list[RowBase]) -> list[NormalizedRow]:
    """Map validated rows; the caller has already refused duplicate keys."""
    return [spec.normalize(row) for row in rows]


def effective_order_type(spec: DatasetSpec, order_type: str | None) -> str:
    return (order_type or ORDER_TYPE_NONE) if spec.has_order_type else ORDER_TYPE_NONE
