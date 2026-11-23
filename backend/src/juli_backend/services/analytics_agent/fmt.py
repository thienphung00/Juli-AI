"""Vietnamese number formats and direction data for every value shown to the seller (E7).

Money 8.728.160đ, margin 42,8%, rates 3,07%, ROAS 3,41. Direction is data (up / down / flat)
for the UI to colour; the text carries the arrow.
"""

from __future__ import annotations

from typing import Any

MONEY = {"gmv", "aov", "profit", "ads_spend", "ads_gmv", "net_revenue", "cost", "cost_total"}
RATE2 = {"ctr", "ctor"}
NODATA = "chưa có dữ liệu"


def _dot(s: str) -> str:
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def integer(v: float) -> str:
    return f"{round(v):,}".replace(",", ".")


def decimal(v: float, places: int) -> str:
    return _dot(f"{v:,.{places}f}")


def value(metric: str, v: float | None) -> str:
    """One metric value in the app's format. Fractions for rates; None = no data, never 0."""
    if v is None:
        return NODATA
    if metric in RATE2:
        return decimal(100 * v, 2) + "%"
    if metric in ("margin", "cost_ratio"):  # a share, shown as % (never "0")
        return decimal(100 * v, 1) + "%"
    if metric == "roas":
        return decimal(v, 2)
    if metric in MONEY:
        return integer(v) + "đ"
    return integer(v)


POINT_METRICS = {"ctr", "ctor", "margin", "cost_ratio"}


def delta(metric: str, now: float | None, before: float | None) -> dict[str, str]:
    """`{dir, text_vi}`. A ratio in % (margin, CTR, CTOR, cost / revenue) changes in percentage
    points; an amount or count in % only when the base is positive, else as the amount itself
    (a % of a negative base reads as nonsense). dir is flat when nothing can be said or changed."""
    if now is None or before is None:
        return {"dir": "flat", "text_vi": "–"}
    diff = now - before
    if metric in POINT_METRICS:
        places = 2 if metric in RATE2 else 1
        if abs(100 * diff) < 0.5 * 10**-places:
            return {"dir": "flat", "text_vi": "–"}
        arrow = "▲ " if diff > 0 else "▼ "
        return {
            "dir": "up" if diff > 0 else "down",
            "text_vi": arrow + decimal(100 * abs(diff), places) + " điểm %",
        }
    if before == 0 or diff == 0:
        return {"dir": "flat", "text_vi": "–"}
    up = diff > 0
    arrow = "▲ " if up else "▼ "
    if before < 0:
        return {"dir": "up" if up else "down", "text_vi": arrow + value(metric, abs(diff))}
    rel = abs(diff) / before
    if rel < 0.0005:
        return {"dir": "flat", "text_vi": "–"}
    return {"dir": "up" if up else "down", "text_vi": arrow + decimal(100 * rel, 1) + "%"}


def day(d: Any) -> str:
    return f"{d:%d/%m}"
