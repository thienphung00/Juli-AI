"""P100 B.5: "Số liệu đến dd/mm" per screen section.

Each Tổng quan / Phân tích section reads a few datasets; its day is the oldest of their newest
days (:func:`loaders.load_freshness`), never past the window end. ``ads`` is the window's last
day with an ad figure (``AdsDaily.source_by_day``). A dataset the shop has no rows for is left
out; a section with none of its datasets is ``None`` ("—").
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

ADS = "ads"
#: the datasets each section's figures come from
SECTION_DATASETS: dict[str, tuple[str, ...]] = {
    # GMV / đơn (shop totals), Lợi nhuận (order lines), Tổng chi phí (ads)
    "kpis": ("shop_overview", "order_lines", ADS),
    # the composition and the channel table: sources (traffic) on the shop totals, ads
    "channels": ("shop_overview", "traffic_overview", ADS),
    # Kế hoạch: GMV and Lợi nhuận against the goal
    "plan": ("shop_overview", "order_lines"),
    # Phân tích › Theo sản phẩm: product rows from the order lines on the shop totals
    "products": ("shop_overview", "order_lines"),
}


def data_through(
    latest: Mapping[str, Mapping[str, Any]], window_end: date, *, ads_last: date | None
) -> dict[str, str | None]:
    """``{section: "YYYY-MM-DD" | None}`` (pure)."""
    days: dict[str, date] = {
        name: v["latest_day"] for name, v in latest.items() if v.get("latest_day") is not None
    }
    if ads_last is not None:
        days[ADS] = ads_last
    out: dict[str, str | None] = {}
    for section, datasets in SECTION_DATASETS.items():
        have = [min(days[d], window_end) for d in datasets if d in days]
        out[section] = min(have).isoformat() if have else None
    return out


def ads_last_day(source_by_day: Mapping[date, str]) -> date | None:
    return max(source_by_day) if source_by_day else None
