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

ADR-117 (``MAPPER_VERSION`` 1, written on every row so a file-vs-API reconciliation can
tell a mapping change from a data change):

- a level-2 source (``sub_source``) is the row's ``segment`` (``schemas.SHOPEE_L2_SOURCES``);
  the L1 total keeps ``segment = 'all'`` and readers never add a child to it;
- ``impressions`` follows the stream: product impressions on the product card, views on
  live / video / affiliate content, ad impressions on ads; a CTR is never compared
  across streams;
- ads rows in the shop-stats export follow the sheet's order type like every other
  stream (a client export's ad orders differ between its placed and confirmed sheets), so they carry
  the post's ``order_type``; only the Ads section's own reports count placed orders;
- period datasets (``granularity: "period"``) land in ``platform_period_metrics``;
  ``product_flags`` and ``promotions`` have tables of their own;
- ``ads_campaign_period`` (the CPC / group-campaign reports) is the one period dataset longer
  than a month: its windows are about three months and overlap between exports, so a reader
  never adds two of its periods together. Rows are stream ``ads`` (an overlay), the campaign
  is ``segment`` (hash) + ``platform_source`` (name), and the ad's cost and ROAS are in
  ``extra`` (``ads_expense``, ``ads_roas``) like the shop-stats ads rows.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from juli_backend.models.ingest import ORDER_TYPE_NONE, SEGMENT_ALL, SHOP_LEVEL_ITEM
from juli_backend.models.platform_data import ITEM_LEVEL_VARIATION
from juli_backend.services.ingest.schemas import (
    MAX_ADS_PERIOD_DAYS,
    MAX_PERIOD_DAYS,
    SHOPEE_L2_SOURCES,
    SHOPEE_PROMO_TYPES,
    DatasetRow,
    ShopeeAdsCampaignPeriodRow,
    ShopeeItemBySourcePeriodRow,
    ShopeeItemBySourceRow,
    ShopeeItemPerformanceRow,
    ShopeeProductFlagRow,
    ShopeeProductOverviewRow,
    ShopeeProductPeriodRow,
    ShopeePromotionDailyRow,
    ShopeePromotionRow,
    ShopeeShopOverviewRow,
    ShopeeShopTrafficRow,
    ShopeeTrafficOverviewPeriodRow,
    ShopeeTrafficOverviewRow,
)

#: The version of this module's field meanings (ADR-117 §1). Bump it whenever a field
#: changes meaning; NULL on a stored row = written before ADR-117.
MAPPER_VERSION = 1

STREAM_PRODUCT_CARD = "product_card"
STREAM_SELLER_VIDEO = "seller_video"
STREAM_SELLER_LIVE = "seller_live"
STREAM_AFFILIATE = "affiliate"
STREAM_ADS = "ads"
STREAM_TOTAL = "total"
STREAM_PROMO = "promo"

STREAM_LABELS: dict[str, str] = {
    STREAM_PRODUCT_CARD: "Thẻ sản phẩm",
    STREAM_SELLER_VIDEO: "Video",
    STREAM_SELLER_LIVE: "Live",
    STREAM_AFFILIATE: "Tiếp thị liên kết",
    STREAM_ADS: "Dịch vụ Hiển thị",
    STREAM_TOTAL: "Tổng",
    STREAM_PROMO: "Khuyến mãi",
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
#: The field each stream's ``impressions`` holds (ADR-117 §1); the product card's
#: ``product_impressions`` is ``_SOURCE_KPIS``' default.
_STREAM_IMPRESSIONS: dict[str, str] = {
    STREAM_SELLER_LIVE: "live_views",
    STREAM_SELLER_VIDEO: "video_views",
    STREAM_AFFILIATE: "content_views",
    STREAM_ADS: "ads_impressions",
}
_SHOP_OVERVIEW_KPIS: dict[str, str] = {
    "sales": "gmv",
    "orders": "orders",
    "product_clicks": "clicks",
    "visitors": "visitors",
    "buyers": "buyers",
}
_PRODUCT_OVERVIEW_KPIS: dict[str, str] = {
    "product_visitors": "visitors",
    "product_page_views": "page_views",
    "bounce_rate": "bounce_rate",
    "atc_visitors": "add_to_cart",
    "buyers": "buyers",
    "units": "units",
    "sales": "gmv",
}
_PROMOTION_KPIS: dict[str, str] = {
    "sales": "gmv",
    "orders": "orders",
    "units": "units",
    "buyers": "buyers",
}
_PRODUCT_PERIOD_KPIS: dict[str, str] = {
    "product_impressions": "impressions",
    "product_clicks": "clicks",
    "ctr": "ctr",
    "orders": "orders",
    "sales": "gmv",
    "buyers": "buyers",
    "units": "units",
    "product_visitors": "visitors",
    "product_page_views": "page_views",
    "atc_visitors": "add_to_cart",
    "bounce_rate": "bounce_rate",
}
_ADS_CAMPAIGN_KPIS: dict[str, str] = {
    "ads_impressions": "impressions",
    "ad_clicks": "clicks",
    "ctr": "ctr",
    "conversions": "orders",
    "units_sold": "units",
    "sales": "gmv",
    "add_to_cart": "add_to_cart",
}
#: Row fields that are part of the key or the item's identity, not metrics.
_KEY_FIELDS = frozenset(
    {
        "campaign_name",
        "ordinal",
        "date",
        "source",
        "sub_source",
        "item_id",
        "item_name",
        "device",
        "promo_type",
        "variation_id",
        "variation_name",
        "item_status",
        "variation_status",
        "seller_sku",
        "extra",
    }
)
#: Period rows describe the item in ``platform_items``; its name is not copied to ``extra``.
_ITEM_TABLE_ROWS = (ShopeeItemBySourcePeriodRow, ShopeeProductPeriodRow)


@dataclass(frozen=True)
class NormalizedRow:
    #: None on a period row: the body's period is the row's.
    day: date | None
    stream: str
    item_id: str = SHOP_LEVEL_ITEM
    platform_source: str | None = None
    segment: str = SEGMENT_ALL
    variation_id: str = ITEM_LEVEL_VARIATION
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
    if item_name and not isinstance(row, _ITEM_TABLE_ROWS):
        extra["item_name"] = item_name
    # D16: the open ``extra`` keeps numbers / booleans / nulls only (the row model
    # already drops its strings; this keeps the rule true for any row type).
    open_extra = getattr(row, "extra", {}) or {}
    extra.update({key: value for key, value in open_extra.items() if not isinstance(value, str)})
    return kpis, extra


_SourceRow = (
    ShopeeTrafficOverviewRow
    | ShopeeItemBySourceRow
    | ShopeeTrafficOverviewPeriodRow
    | ShopeeItemBySourcePeriodRow
)


def _source_row(row: _SourceRow) -> NormalizedRow:
    stream = SHOPEE_L1_TO_STREAM[row.source]
    views = _STREAM_IMPRESSIONS.get(stream)
    kpi_map = dict(_SOURCE_KPIS)
    if views is not None and getattr(row, views) is not None:
        # The stream's own views; ``product_impressions`` (if sent) stays in ``extra``.
        del kpi_map["product_impressions"]
        kpi_map[views] = "impressions"
    kpis, extra = _split(row, kpi_map)
    return NormalizedRow(
        day=getattr(row, "date", None),
        stream=stream,
        item_id=getattr(row, "item_id", SHOP_LEVEL_ITEM),
        platform_source=row.source,
        segment=(
            SHOPEE_L2_SOURCES[row.source][row.sub_source]
            if row.sub_source is not None
            else SEGMENT_ALL
        ),
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


def _total_row(kpi_map: dict[str, str]) -> Callable[[Any], NormalizedRow]:
    def normalize(row: Any) -> NormalizedRow:
        kpis, extra = _split(row, kpi_map)
        return NormalizedRow(
            day=getattr(row, "date", None), stream=STREAM_TOTAL, kpis=kpis, extra=extra
        )

    return normalize


def _promotion_daily(row: ShopeePromotionDailyRow) -> NormalizedRow:
    kpis, extra = _split(row, _PROMOTION_KPIS)
    return NormalizedRow(
        day=row.date,
        stream=STREAM_PROMO,
        segment=SHOPEE_PROMO_TYPES[row.promo_type],
        kpis=kpis,
        extra=extra,
    )


def _product_period(row: ShopeeProductPeriodRow) -> NormalizedRow:
    kpis, extra = _split(row, _PRODUCT_PERIOD_KPIS)
    return NormalizedRow(
        day=None,
        stream=STREAM_TOTAL,
        item_id=row.item_id,
        variation_id=row.variation_id,
        kpis=kpis,
        extra=extra,
    )


def _ads_campaign(row: ShopeeAdsCampaignPeriodRow) -> NormalizedRow:
    """One campaign x product total: a Juli ``ads`` overlay row. The platform has no campaign
    id, so ``segment`` is a short hash of the name (and twin place) and ``platform_source``
    holds the name itself, cut to its column."""
    kpis, extra = _split(row, _ADS_CAMPAIGN_KPIS)
    digest = hashlib.sha1(f"{row.campaign_name}|{row.ordinal}".encode(), usedforsecurity=False)
    return NormalizedRow(
        day=None,
        stream=STREAM_ADS,
        item_id=row.item_id or SHOP_LEVEL_ITEM,
        platform_source=row.campaign_name[:64],
        segment=f"c{digest.hexdigest()[:12]}",
        kpis=kpis,
        extra=extra,
    )


def _not_metrics(row: Any) -> NormalizedRow:
    raise TypeError(f"{type(row).__name__} has its own table, not a metrics row")


GRANULARITY_DAY = "day"
GRANULARITY_PERIOD = "period"
#: Where a dataset's rows land.
WRITE_DAILY = "daily"  # platform_daily_metrics
WRITE_PERIOD = "period"  # platform_period_metrics (+ platform_items for item rows)
WRITE_FLAGS = "flags"  # platform_product_flags
WRITE_PROMOTIONS = "promotions"  # platform_promotions


@dataclass(frozen=True)
class DatasetSpec:
    platform: str
    name: str
    row_model: type[DatasetRow]
    normalize: Callable[[Any], NormalizedRow]
    #: Whether the platform's numbers depend on "Loại Đơn Hàng" (placed/paid/confirmed).
    has_order_type: bool
    description: str
    granularity: str = GRANULARITY_DAY
    writes: str = WRITE_DAILY
    #: The longest period one post may cover (days); ``schemas.Period`` holds the ceiling.
    max_period_days: int = MAX_PERIOD_DAYS


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
    ("shopee", "shop_overview"): DatasetSpec(
        "shopee",
        "shop_overview",
        ShopeeShopOverviewRow,
        _total_row(_SHOP_OVERVIEW_KPIS),
        True,
        "Per day, whole shop: sales, orders, visits, cancels / returns, buyers (Tổng quan).",
    ),
    ("shopee", "product_overview"): DatasetSpec(
        "shopee",
        "product_overview",
        ShopeeProductOverviewRow,
        _total_row(_PRODUCT_OVERVIEW_KPIS),
        True,
        "Per day, the shop's product funnel: visits, add-to-cart, buyers (Sản phẩm › Tổng quan).",
    ),
    ("shopee", "promotion_daily"): DatasetSpec(
        "shopee",
        "promotion_daily",
        ShopeePromotionDailyRow,
        _promotion_daily,
        True,
        "Per day, per promotion type (Khuyến mãi › Biểu đồ).",
    ),
    ("shopee", "traffic_overview_period"): DatasetSpec(
        "shopee",
        "traffic_overview_period",
        ShopeeTrafficOverviewPeriodRow,
        _source_row,
        True,
        "Per period, per L1 / L2 source, shop totals (… › Theo nguồn lưu lượng, total rows).",
        GRANULARITY_PERIOD,
        WRITE_PERIOD,
    ),
    ("shopee", "item_by_source_period"): DatasetSpec(
        "shopee",
        "item_by_source_period",
        ShopeeItemBySourcePeriodRow,
        _source_row,
        True,
        "Per period, per item × L1 source (Tổng quan › Theo sản phẩm).",
        GRANULARITY_PERIOD,
        WRITE_PERIOD,
    ),
    ("shopee", "product_period"): DatasetSpec(
        "shopee",
        "product_period",
        ShopeeProductPeriodRow,
        _product_period,
        True,
        "Per period, per item / variation, 40 metrics (parentskudetail › Sản Phẩm Hiệu Quả Tốt).",
        GRANULARITY_PERIOD,
        WRITE_PERIOD,
    ),
    ("shopee", "ads_campaign_period"): DatasetSpec(
        "shopee",
        "ads_campaign_period",
        ShopeeAdsCampaignPeriodRow,
        _ads_campaign,
        True,
        "Per report window (up to 100 days), per ad campaign x product (CPC / group campaign).",
        GRANULARITY_PERIOD,
        WRITE_PERIOD,
        MAX_ADS_PERIOD_DAYS,
    ),
    ("shopee", "product_flags"): DatasetSpec(
        "shopee",
        "product_flags",
        ShopeeProductFlagRow,
        _not_metrics,
        False,
        "Per period, the items Seller Centre flagged (parentskudetail flag sheets).",
        GRANULARITY_PERIOD,
        WRITE_FLAGS,
    ),
    ("shopee", "promotions"): DatasetSpec(
        "shopee",
        "promotions",
        ShopeePromotionRow,
        _not_metrics,
        True,
        "Per period, per promotion program (Khuyến mãi › Danh sách hiệu suất).",
        GRANULARITY_PERIOD,
        WRITE_PROMOTIONS,
    ),
}


def dataset_spec(platform: str, dataset: str) -> DatasetSpec | None:
    return DATASETS.get((platform, dataset))


def normalize_rows(spec: DatasetSpec, rows: list[DatasetRow]) -> list[NormalizedRow]:
    """Map validated rows; the caller has already refused duplicate keys."""
    return [spec.normalize(row) for row in rows]


def effective_order_type(spec: DatasetSpec, order_type: str | None) -> str:
    return (order_type or ORDER_TYPE_NONE) if spec.has_order_type else ORDER_TYPE_NONE
