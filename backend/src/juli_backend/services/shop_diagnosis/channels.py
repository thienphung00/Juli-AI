"""TikTok's five product channels, their funnels and their window sums — ADR-108 d.1, 4, 5.

Each A-34 row carries one block per channel. This module is the only map from a
block's fields to the report's KPIs, so the page itself can stay free of field
names (d.1):

==========================  ==================================  ==========================
Report channel              A-34 block                          Notes
==========================  ==================================  ==========================
Thẻ sản phẩm của người bán  ``seller_product_card_performance``
Tab Cửa hàng                ``shop_tab_performance``            ``shop_tab_*`` keys; no
                                                                add-to-cart; SKU orders =
                                                                ``shop_tab_ctor_sku`` ×
                                                                clicks (*ước tính*)
Video của người bán         ``seller_video_performance``
LIVE của người bán          ``seller_live_performance``
Liên kết                    ``affiliate_total_performance``     sub-rows below
  Video liên kết            ``affiliate_video_performance``     GMV ``attributed_video_gmv``
  LIVE liên kết             ``affiliate_live_performance``      GMV ``live_attributed_gmv``
Toàn shop                   ``total_performance``               ``sku_orders``, ``gmv``
==========================  ==================================  ==========================

Measured on the Fujiwa daily files (1,899 product-days): product card + seller
video + seller LIVE + affiliate sum **exactly** to the total for impressions,
clicks, add-to-carts, SKU orders and GMV. Shop Tab is reported beside them and
overlaps them, so it is never added into a shop total.

Only additive counts are summed over days; every rate is recomputed from the
sums (d.1: "never an average of daily rates") and no ``unique_*`` field is read.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from juli_backend.services.shop_diagnosis.snapshot import to_float


class Channel(StrEnum):
    PRODUCT_CARD = "product_card"
    SHOP_TAB = "shop_tab"
    SELLER_VIDEO = "seller_video"
    SELLER_LIVE = "seller_live"
    AFFILIATE = "affiliate"
    AFFILIATE_VIDEO = "affiliate_video"
    AFFILIATE_LIVE = "affiliate_live"
    TOTAL = "total"


#: The five channels of Step 1, in page order.
FIVE_CHANNELS: tuple[Channel, ...] = (
    Channel.PRODUCT_CARD,
    Channel.SHOP_TAB,
    Channel.SELLER_VIDEO,
    Channel.SELLER_LIVE,
    Channel.AFFILIATE,
)
AFFILIATE_SUB_ROWS: tuple[Channel, ...] = (Channel.AFFILIATE_VIDEO, Channel.AFFILIATE_LIVE)
#: d.4 — Nhóm khách tự tìm đến, where the hero decision tree runs.
SELF_SEARCH: tuple[Channel, ...] = (Channel.PRODUCT_CARD, Channel.SHOP_TAB)
#: d.4 — Nhóm nội dung.
CONTENT: tuple[Channel, ...] = (Channel.SELLER_VIDEO, Channel.SELLER_LIVE, Channel.AFFILIATE)
#: The channels that partition the shop total (Shop Tab overlaps them).
ADDITIVE: tuple[Channel, ...] = (
    Channel.PRODUCT_CARD,
    Channel.SELLER_VIDEO,
    Channel.SELLER_LIVE,
    Channel.AFFILIATE,
)

CHANNEL_LABELS: dict[Channel, str] = {
    Channel.PRODUCT_CARD: "Thẻ sản phẩm của người bán",
    Channel.SHOP_TAB: "Tab Cửa hàng",
    Channel.SELLER_VIDEO: "Video của người bán",
    Channel.SELLER_LIVE: "LIVE của người bán",
    Channel.AFFILIATE: "Liên kết",
    Channel.AFFILIATE_VIDEO: "Video liên kết",
    Channel.AFFILIATE_LIVE: "LIVE liên kết",
    Channel.TOTAL: "Tất cả kênh",
}
SELF_SEARCH_LABEL = "Nhóm khách tự tìm đến"
CONTENT_LABEL = "Nhóm nội dung"


@dataclass(frozen=True)
class ChannelSpec:
    """Where one channel's counts live in an A-34 row."""

    block: str
    impressions: str
    clicks: str
    #: ``None`` when TikTok does not report add-to-carts for the channel.
    add_to_cart: str | None
    #: ``None`` when the channel reports no orders (derived or absent).
    sku_orders: str | None
    gmv: str
    #: Rate field used to derive SKU orders when ``sku_orders`` is ``None``.
    derived_ctor: str | None = None


SPECS: dict[Channel, ChannelSpec] = {
    Channel.PRODUCT_CARD: ChannelSpec(
        "seller_product_card_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        "attributed_sku_orders",
        "attributed_gmv",
    ),
    Channel.SHOP_TAB: ChannelSpec(
        "shop_tab_performance",
        "shop_tab_product_impressions",
        "shop_tab_product_clicks",
        None,
        None,
        "shop_tab_gmv",
        derived_ctor="shop_tab_ctor_sku",
    ),
    Channel.SELLER_VIDEO: ChannelSpec(
        "seller_video_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        "attributed_sku_orders",
        "attributed_gmv",
    ),
    Channel.SELLER_LIVE: ChannelSpec(
        "seller_live_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        "attributed_sku_orders",
        "attributed_gmv",
    ),
    Channel.AFFILIATE: ChannelSpec(
        "affiliate_total_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        "attributed_sku_orders",
        "attributed_gmv",
    ),
    Channel.AFFILIATE_VIDEO: ChannelSpec(
        "affiliate_video_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        None,
        "attributed_video_gmv",
    ),
    Channel.AFFILIATE_LIVE: ChannelSpec(
        "affiliate_live_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        None,
        "live_attributed_gmv",
    ),
    Channel.TOTAL: ChannelSpec(
        "total_performance",
        "product_impressions",
        "product_clicks",
        "add_cart_count",
        "sku_orders",
        "gmv",
    ),
}


@dataclass(frozen=True)
class Counts:
    """Additive counts of one channel over some days.

    ``add_to_cart`` / ``sku_orders`` are ``None`` when the channel does not report
    them; ``orders_estimated`` marks Shop Tab's derived SKU orders.
    """

    impressions: float = 0.0
    clicks: float = 0.0
    add_to_cart: float | None = 0.0
    sku_orders: float | None = 0.0
    gmv: float = 0.0
    orders_estimated: bool = False
    #: Total block only: orders, items sold and refunds, for the shop KPI table.
    orders: float = 0.0
    items_sold: float = 0.0
    refunds: float = 0.0

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.impressions + other.impressions,
            self.clicks + other.clicks,
            _add_optional(self.add_to_cart, other.add_to_cart),
            _add_optional(self.sku_orders, other.sku_orders),
            self.gmv + other.gmv,
            self.orders_estimated or other.orders_estimated,
            self.orders + other.orders,
            self.items_sold + other.items_sold,
            self.refunds + other.refunds,
        )

    def scaled(self, factor: float) -> Counts:
        """Every count multiplied by ``factor`` (a daily average is ``scaled(1 / days)``)."""
        return replace(
            self,
            impressions=self.impressions * factor,
            clicks=self.clicks * factor,
            add_to_cart=None if self.add_to_cart is None else self.add_to_cart * factor,
            sku_orders=None if self.sku_orders is None else self.sku_orders * factor,
            gmv=self.gmv * factor,
            orders=self.orders * factor,
            items_sold=self.items_sold * factor,
            refunds=self.refunds * factor,
        )

    @property
    def ctr(self) -> float | None:
        return _ratio(self.clicks, self.impressions)

    @property
    def add_to_cart_rate(self) -> float | None:
        return None if self.add_to_cart is None else _ratio(self.add_to_cart, self.clicks)

    @property
    def ctor(self) -> float | None:
        return None if self.sku_orders is None else _ratio(self.sku_orders, self.clicks)

    @property
    def aov(self) -> float | None:
        return None if self.sku_orders is None else _ratio(self.gmv, self.sku_orders)

    @property
    def orders_per_add_to_cart(self) -> float | None:
        if self.add_to_cart is None or self.sku_orders is None:
            return None
        return _ratio(self.sku_orders, self.add_to_cart)

    @property
    def items_per_order(self) -> float | None:
        return _ratio(self.items_sold, self.orders)

    @property
    def refund_share(self) -> float | None:
        return _ratio(self.refunds, self.gmv)


def _add_optional(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def empty(channel: Channel) -> Counts:
    """Zero counts with the channel's own ``None`` fields."""
    spec = SPECS[channel]
    return Counts(
        add_to_cart=0.0 if spec.add_to_cart else None,
        sku_orders=0.0 if (spec.sku_orders or spec.derived_ctor) else None,
        orders_estimated=spec.derived_ctor is not None,
    )


def read_counts(row: dict, channel: Channel) -> Counts:
    """One A-34 row's counts for ``channel``; a missing block reads as zero."""
    spec = SPECS[channel]
    raw = row.get(spec.block)
    block: dict = raw if isinstance(raw, dict) else {}
    clicks = to_float(block.get(spec.clicks))
    if spec.sku_orders is not None:
        sku_orders: float | None = to_float(block.get(spec.sku_orders))
    elif spec.derived_ctor is not None:
        sku_orders = to_float(block.get(spec.derived_ctor)) * clicks
    else:
        sku_orders = None
    counts = Counts(
        impressions=to_float(block.get(spec.impressions)),
        clicks=clicks,
        add_to_cart=to_float(block.get(spec.add_to_cart)) if spec.add_to_cart else None,
        sku_orders=sku_orders,
        gmv=to_float(block.get(spec.gmv)),
        orders_estimated=spec.derived_ctor is not None,
    )
    if channel is Channel.TOTAL:
        counts = replace(
            counts,
            orders=to_float(block.get("orders")),
            items_sold=to_float(block.get("items_sold")),
            refunds=to_float(block.get("refunds")),
        )
    return counts


#: ``series[channel][product_id][day]`` — one product-day's counts.
Series = dict[Channel, dict[str, dict[date, Counts]]]


def build_series(daily: dict[date, list[dict]]) -> Series:
    """Per channel, per product, per day: the counts the daily files carry."""
    out: Series = {channel: defaultdict(dict) for channel in Channel}
    for day, rows in daily.items():
        for row in rows:
            product_id = str(row.get("id") or "")
            if not product_id:
                continue
            for channel in Channel:
                out[channel][product_id][day] = read_counts(row, channel)
    return {channel: dict(by_product) for channel, by_product in out.items()}


def window_sum(
    series: Series,
    channel: Channel,
    days: Iterable[date],
    products: Iterable[str] | None = None,
) -> Counts:
    """Sum of ``channel`` over ``days`` for ``products`` (every product when ``None``)."""
    by_product = series.get(channel, {})
    chosen = by_product.keys() if products is None else products
    wanted = list(days)
    total = empty(channel)
    for product_id in chosen:
        per_day = by_product.get(product_id, {})
        for day in wanted:
            counts = per_day.get(day)
            if counts is not None:
                total = total + counts
    return total


def group_sum(
    series: Series,
    channels: Iterable[Channel],
    days: Iterable[date],
    products: Iterable[str] | None = None,
) -> Counts:
    """Several channels summed — the self-search group is product card + Shop Tab.

    When one member has no add-to-cart data the group has none either: a group
    rate over a partial numerator would understate it.
    """
    wanted = list(days)
    chosen = None if products is None else list(products)
    total: Counts | None = None
    partial_cart = False
    for channel in channels:
        part = window_sum(series, channel, wanted, chosen)
        partial_cart = partial_cart or part.add_to_cart is None
        total = part if total is None else total + part
    if total is None:
        return Counts()
    return replace(total, add_to_cart=None) if partial_cart else total


def daily_values(
    series: Series,
    channels: Iterable[Channel],
    days: Iterable[date],
    products: Iterable[str] | None = None,
) -> list[Counts]:
    """One summed ``Counts`` per day, in ``days`` order (for intervals and timelines)."""
    channel_list = list(channels)
    chosen = None if products is None else list(products)
    return [group_sum(series, channel_list, [day], chosen) for day in days]
