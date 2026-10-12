"""The channel a card's KPI is set and measured on (D32). Pure.

D29 sets a card's target from the product's metric over ALL channels (Thẻ
sản phẩm, Video, LIVE). A lever acts on fewer: a new cover image or title is
seen on the product card (search, recommendation, shop page, Shop Tab -- A-33's
``PRODUCT_CARD`` content type), never inside a video or a LIVE, so all-channel
CTR dilutes its effect with traffic it cannot move, and the band of that
mixture is wide. D32 reads the target metric, its adaptive window, its
window-mean band, the KPI clamp, confidence and the day-14 measurement on the
lever's channel.

What is stored per channel (P1, A-33 product detail): per day and content
type, impressions and CTR (clicks = round(impressions × CTR)) and GMV. No SKU
orders, so CTOR and AOV stay all-channel (ADR-106 Amendment 2). Hence:

==================  ==================  ===========================================
Lever               Channel             Metric read per channel
==================  ==================  ===========================================
cover_image         product_card        CTR
title               product_card        CTR, Lượt hiển thị
description         product_card        none (CTOR: no per-channel orders) → total
product_discount,   total               a price shows on every channel
flash_sale,
shipping_discount,
buy_more_save_more
==================  ==================  ===========================================

Fallback: when the channel has no breakdown rows, no value, or its window is
"ít dữ liệu" (fewer than ``min_events`` clicks on the longest window), the KPI
uses the all-channel window and says so (``channel = "total"``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.funnel import ZERO
from juli_backend.services.optimize_product.tunables import DiagTunables
from juli_backend.services.optimize_product.volatility import (
    MetricWindow,
    daily_cv,
    select_window,
    window_counts,
)

CHANNEL_TOTAL = "total"
CHANNEL_PRODUCT_CARD = "product_card"
CHANNEL_VIDEO = "video"
CHANNEL_LIVE = "live"

#: D32 channel -> the A-33 ``content_type`` key P1 stores under ``traffic_breakdown``
#: / ``sales_breakdown``.
CONTENT_TYPE: Mapping[str, str] = {
    CHANNEL_PRODUCT_CARD: "PRODUCT_CARD",
    CHANNEL_VIDEO: "VIDEO",
    CHANNEL_LIVE: "LIVE",
}

#: Seller-facing channel names (the shop diagnosis's own labels).
CHANNEL_LABELS_VI: Mapping[str, str] = {
    CHANNEL_PRODUCT_CARD: "Thẻ sản phẩm",
    CHANNEL_VIDEO: "Video",
    CHANNEL_LIVE: "LIVE",
    CHANNEL_TOTAL: "tất cả kênh",
}

#: Optimize Product lever code -> the channel it acts on (ADR-106 d.1: listing
#: levers act on the PRODUCT_CARD funnel; price and basket levers everywhere).
#: Video and LIVE belong to the content cards (``content_cards``), which are
#: already read on their own stream.
LEVER_CHANNEL: Mapping[str, str] = {
    "cover_image": CHANNEL_PRODUCT_CARD,
    "title": CHANNEL_PRODUCT_CARD,
    "description": CHANNEL_PRODUCT_CARD,
    "product_discount": CHANNEL_TOTAL,
    "flash_sale": CHANNEL_TOTAL,
    "shipping_discount": CHANNEL_TOTAL,
    "buy_more_save_more": CHANNEL_TOTAL,
}

#: Metrics a channel can carry: A-33 has per-channel impressions and clicks only.
CHANNEL_METRICS: frozenset[str] = frozenset({"impressions", "ctr"})

#: Why a channel KPI fell back to all channels (``KpiWindow.fallback``).
FALLBACK_LOW_DATA = "low_data"
FALLBACK_NO_CHANNEL_DATA = "no_channel_data"
FALLBACK_METRIC_NOT_PER_CHANNEL = "metric_not_per_channel"


def lever_channel(lever: str | None) -> str:
    """The channel ``lever`` acts on; an unknown lever is all-channel."""
    return LEVER_CHANNEL.get(lever or "", CHANNEL_TOTAL)


def measured_on_vi(channel: str | None) -> str:
    """ "đo trên kênh Thẻ sản phẩm" / "đo trên tất cả kênh" (seller copy)."""
    if not channel or channel == CHANNEL_TOTAL or channel not in CHANNEL_LABELS_VI:
        return "đo trên tất cả kênh"
    return f"đo trên kênh {CHANNEL_LABELS_VI[channel]}"


def channel_days(rows: Sequence[ProductDay], channel: str) -> list[ProductDay]:
    """The rows projected onto one channel: its impressions, clicks and GMV.

    A day stored with a breakdown but without this content type is a day the
    channel showed nothing (zeros); a day stored without any breakdown is left
    out (unknown, never zero). Orders are not per channel and read as zero.
    """
    if channel == CHANNEL_TOTAL:
        return list(rows)
    key = CONTENT_TYPE.get(channel)
    if key is None:
        return []
    out: list[ProductDay] = []
    for row in rows:
        if not row.channels:
            continue
        traffic = row.channels.get(key)
        out.append(
            ProductDay(
                day=row.day,
                impressions=traffic.impressions if traffic is not None else ZERO,
                clicks=traffic.clicks if traffic is not None else ZERO,
                gmv=(traffic.gmv or ZERO) if traffic is not None else ZERO,
            )
        )
    return out


def channel_gmv_per_day(
    rows: Sequence[ProductDay], channel: str, as_of: date, days: int
) -> float | None:
    """The channel's GMV per day over the ``days`` ending ``as_of``; ``None``
    when no day of the window carries a GMV for it (no sales breakdown)."""
    key = CONTENT_TYPE.get(channel)
    if key is None:
        return None
    first = as_of - timedelta(days=days - 1)
    seen = False
    total = ZERO
    for row in rows:
        if not first <= row.day <= as_of:
            continue
        traffic = row.channels.get(key) if row.channels else None
        if traffic is not None and traffic.gmv is not None:
            seen = True
            total += traffic.gmv
    return float(total) / days if seen and days > 0 else None


@dataclass(frozen=True)
class KpiWindow:
    """The window a card's KPI is read on (D32)."""

    #: The channel actually used: the lever's, or ``total`` after a fallback.
    channel: str
    #: The lever's own channel, before any fallback.
    requested: str
    window: MetricWindow
    #: The rows the window was read on (the channel's projection, or all rows).
    rows: tuple[ProductDay, ...]
    #: Why ``channel`` is ``total`` although the lever's channel is not, else ``None``.
    fallback: str | None = None

    @property
    def per_channel(self) -> bool:
        return self.channel != CHANNEL_TOTAL

    def impressions_cv(self, as_of: date) -> float | None:
        """CV of the window's daily impressions on this channel (stability, confidence)."""
        counts = window_counts(self.rows, as_of, self.window.window_days)
        return daily_cv(counts.daily_values("impressions"))


def _usable(window: MetricWindow) -> bool:
    return (
        not window.low_data
        and window.value is not None
        and window.value > 0
        and window.band_pct is not None
    )


def kpi_window(
    rows: Sequence[ProductDay],
    *,
    as_of: date,
    metric: str,
    lever: str | None,
    tunables: DiagTunables,
    total: MetricWindow | None = None,
) -> KpiWindow:
    """The lever's channel window for ``metric``, or the all-channel one (fallback).

    ``total`` is the all-channel window when the caller already has it.
    """
    requested = lever_channel(lever)
    all_rows = tuple(rows)
    total = total or select_window(all_rows, as_of, metric, tunables)

    def _total(reason: str | None) -> KpiWindow:
        return KpiWindow(CHANNEL_TOTAL, requested, total, all_rows, reason)

    if requested == CHANNEL_TOTAL:
        return _total(None)
    if metric not in CHANNEL_METRICS:
        return _total(FALLBACK_METRIC_NOT_PER_CHANNEL)
    projected = tuple(channel_days(all_rows, requested))
    if not projected:
        return _total(FALLBACK_NO_CHANNEL_DATA)
    window = select_window(projected, as_of, metric, tunables)
    if window.low_data:
        return _total(FALLBACK_LOW_DATA)
    if not _usable(window):
        return _total(FALLBACK_NO_CHANNEL_DATA)
    return KpiWindow(requested, requested, window, projected, None)


__all__ = [
    "CHANNEL_LABELS_VI",
    "CHANNEL_LIVE",
    "CHANNEL_METRICS",
    "CHANNEL_PRODUCT_CARD",
    "CHANNEL_TOTAL",
    "CHANNEL_VIDEO",
    "CONTENT_TYPE",
    "FALLBACK_LOW_DATA",
    "FALLBACK_METRIC_NOT_PER_CHANNEL",
    "FALLBACK_NO_CHANNEL_DATA",
    "LEVER_CHANNEL",
    "KpiWindow",
    "channel_days",
    "channel_gmv_per_day",
    "kpi_window",
    "lever_channel",
    "measured_on_vi",
]
