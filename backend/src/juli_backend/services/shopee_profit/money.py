"""Rounding rules for VND and rates -- the one place they are decided.

- Amounts that Shopee charges (fee components, ads allocation) and floor prices round to
  whole đồng, half up.
- A discount offered to buyers rounds DOWN to a step (1.000đ) so the seller never offers
  more than the floor allows.
- Percent-point outputs (``*_pct``) round half up to 0.1.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
ONE = Decimal(1)
DISCOUNT_STEP = Decimal(1000)


def to_dong(value: Decimal) -> Decimal:
    return value.quantize(ONE, rounding=ROUND_HALF_UP)


def round_down_to(value: Decimal, step: Decimal = DISCOUNT_STEP) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def pct_points(rate: Decimal | None, places: str = "0.1") -> Decimal | None:
    if rate is None:
        return None
    return (rate * 100).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator
