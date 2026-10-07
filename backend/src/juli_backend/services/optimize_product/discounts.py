"""Platform- and seller-discount share per product, from real orders (ADR-106 amendment 4).

A product whose CTR or CTOR moved while most of its orders carried a
*platform* discount was probably carried by a platform campaign — something the
Partner API cannot read (no platform-campaign endpoint), so the order lines are
the only trace. Each non-gift line of a non-cancelled order is one unit; a line
counts as platform-discounted when ``platform_discount > 0`` and as
seller-discounted when ``seller_discount > 0``. The order's ``create_time`` (the
order search payload has no per-line timestamp) places it in a window, read in
the shop's timezone (UTC+7 for Vietnam).

Pure: callers hand the orders in.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.funnel import to_decimal

CANCELLED = "CANCELLED"
SHOP_UTC_OFFSET_HOURS = 7


@dataclass(frozen=True)
class WindowShare:
    """Discounted share of one product's non-gift lines in one window."""

    lines: int
    platform_lines: int
    seller_lines: int
    #: ``None`` when fewer than ``platform_discount_min_lines`` lines exist.
    platform_share: Decimal | None
    seller_share: Decimal | None


@dataclass(frozen=True)
class DiscountPair:
    current: WindowShare
    previous: WindowShare


def _share(count: int, lines: int, min_lines: int) -> Decimal | None:
    return None if lines < min_lines or lines <= 0 else Decimal(count) / Decimal(lines)


def _window_share(lines: int, platform: int, seller: int, *, min_lines: int) -> WindowShare:
    return WindowShare(
        lines,
        platform,
        seller,
        _share(platform, lines, min_lines),
        _share(seller, lines, min_lines),
    )


def _local_date(timestamp: object) -> date | None:
    try:
        seconds = int(str(timestamp))
    except ValueError:
        return None
    zone = timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))
    return datetime.fromtimestamp(seconds, tz=zone).date()


def discount_shares(
    orders: list[dict],
    *,
    current: tuple[date, date],
    previous: tuple[date, date],
    config: StageDiagnosisConfig,
) -> dict[str, DiscountPair]:
    """Per product, both windows (inclusive ``(first, last)`` local dates)."""
    tally: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: {"current": [0, 0, 0], "previous": [0, 0, 0]}
    )
    for order in orders:
        if not isinstance(order, dict) or str(order.get("status") or "") == CANCELLED:
            continue
        day = _local_date(order.get("create_time"))
        if day is None:
            continue
        if current[0] <= day <= current[1]:
            window = "current"
        elif previous[0] <= day <= previous[1]:
            window = "previous"
        else:
            continue
        for line in order.get("line_items") or []:
            if not isinstance(line, dict) or line.get("is_gift"):
                continue
            product_id = str(line.get("product_id") or "")
            if not product_id:
                continue
            counts = tally[product_id][window]
            counts[0] += 1
            counts[1] += 1 if to_decimal(line.get("platform_discount")) > 0 else 0
            counts[2] += 1 if to_decimal(line.get("seller_discount")) > 0 else 0
    floor = config.platform_discount_min_lines
    return {
        product_id: DiscountPair(
            _window_share(*windows["current"][:3], min_lines=floor),
            _window_share(*windows["previous"][:3], min_lines=floor),
        )
        for product_id, windows in tally.items()
    }


def empty_pair(config: StageDiagnosisConfig) -> DiscountPair:
    blank = _window_share(0, 0, 0, min_lines=config.platform_discount_min_lines)
    return DiscountPair(blank, blank)
