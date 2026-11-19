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
    if metric == "margin":
        return decimal(100 * v, 1) + "%"
    if metric == "roas":
        return decimal(v, 2)
    if metric in MONEY:
        return integer(v) + "đ"
    return integer(v)


def delta(metric: str, now: float | None, before: float | None) -> dict[str, str]:
    """`{dir, text_vi}`; dir flat when the comparison is impossible or the change is nil."""
    if now is None or before is None or before == 0:
        return {"dir": "flat", "text_vi": "–"}
    rel = (now - before) / abs(before)
    if abs(rel) < 0.0005:
        return {"dir": "flat", "text_vi": "–"}
    up = rel > 0
    return {
        "dir": "up" if up else "down",
        "text_vi": ("▲ " if up else "▼ ") + decimal(100 * abs(rel), 1) + "%",
    }


def day(d: Any) -> str:
    return f"{d:%d/%m}"
