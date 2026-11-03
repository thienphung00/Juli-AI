"""JSON-ready numbers and the Vietnamese labels the payloads carry.

Money is VND (an int when whole, else a float to the xu); rates are fractions unless the field
name ends in ``_pct`` (percent points, one decimal). ``None`` always means "not known", never 0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.money import pct_points

ORDER_BASIS = {"key": "confirmed", "label": "Đơn đã xác nhận"}
ADS_BASIS = {"key": "placed", "label": "đơn đã đặt"}
ADS_BASIS_NOTE = (
    "Quảng cáo tính theo đơn đã đặt (cách Shopee báo cáo); không cộng vào tổng đơn đã xác nhận."
)
ASSUMED_COST_LABEL = "giá vốn giả định (1/3 giá)"


def num(value: Any) -> int | float | None:
    """A Decimal/int/float as a JSON number: whole numbers as int, others to 2 decimals."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    if d == d.to_integral_value():
        return int(d)
    return float(round(d, 2))


def ratio(value: Decimal | None, places: int = 6) -> float | None:
    return None if value is None else float(round(value, places))


def pct(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def pct_of(value: Decimal | None) -> float | None:
    """A fraction as percent points to 0.1."""
    p = pct_points(value)
    return None if p is None else float(p)


def delta_pct(now: Decimal | None, before: Decimal | None) -> float | None:
    if now is None or before is None or before == 0:
        return None
    return float(round((now - before) / before * 100, 1))
