"""Floor price per SKU (the red line) and the maximum discount.

absolute floor  = (cogs + packaging + fixed fee/order) / (1 - fee%)
operating floor = (cogs + packaging + fixed fee/order)
                  / (1 - fee% - ads% - affiliate% - target margin%)
max discount    = 1 - operating floor / list price, capped by the seller's own cap.

Rules:
- Rates are fractions. Floors round to whole đồng, half up (121.176,47 -> 121.176).
- Max discount amount = list - operating floor, rounded DOWN to 1.000đ (18.021 -> 18.000);
  ``max_discount_pct`` is the unrounded ratio shown to 0.1 (9,0%). A seller cap (% of
  list) lowers both. A floor above list gives a 0 discount with reason ``list_below_floor``.
- Missing input -> ``None`` + a reason code; a denominator <= 0 -> ``None`` +
  ``denominator_non_positive`` (never a negative or infinite price).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO, pct_points, round_down_to, to_dong


@dataclass(frozen=True)
class FloorInputs:
    list_price: Decimal | None = None
    cogs: Decimal | None = None
    packaging: Decimal | None = None
    fixed_fee_per_order: Decimal = ZERO
    platform_fee_rate: Decimal | None = None
    ads_rate: Decimal | None = None
    affiliate_rate: Decimal | None = None
    target_margin_rate: Decimal | None = None
    seller_max_discount_rate: Decimal | None = None


@dataclass(frozen=True)
class FloorResult:
    absolute_floor: Decimal | None
    operating_floor: Decimal | None
    max_discount_pct: Decimal | None
    max_discount_amount: Decimal | None
    reasons: dict[str, str] = field(default_factory=dict)  # field name -> reason code


def _missing(names: dict[str, Decimal | None]) -> str | None:
    gone = [n for n, v in names.items() if v is None]
    return "missing:" + ",".join(gone) if gone else None


def compute_floor(inp: FloorInputs) -> FloorResult:
    reasons: dict[str, str] = {}
    absolute: Decimal | None = None
    operating: Decimal | None = None

    base_missing = _missing({"cogs": inp.cogs, "packaging": inp.packaging})
    abs_missing = base_missing or _missing({"platform_fee_rate": inp.platform_fee_rate})
    if abs_missing:
        reasons["absolute_floor"] = abs_missing
    else:
        assert inp.cogs is not None and inp.packaging is not None
        assert inp.platform_fee_rate is not None
        denom = 1 - inp.platform_fee_rate
        if denom <= 0:
            reasons["absolute_floor"] = "denominator_non_positive"
        else:
            absolute = to_dong((inp.cogs + inp.packaging + inp.fixed_fee_per_order) / denom)

    op_missing = abs_missing or _missing(
        {
            "ads_rate": inp.ads_rate,
            "affiliate_rate": inp.affiliate_rate,
            "target_margin_rate": inp.target_margin_rate,
        }
    )
    if op_missing:
        reasons["operating_floor"] = op_missing
    else:
        assert inp.cogs is not None and inp.packaging is not None
        assert inp.platform_fee_rate is not None and inp.ads_rate is not None
        assert inp.affiliate_rate is not None and inp.target_margin_rate is not None
        denom = (
            1 - inp.platform_fee_rate - inp.ads_rate - inp.affiliate_rate - inp.target_margin_rate
        )
        if denom <= 0:
            reasons["operating_floor"] = "denominator_non_positive"
        else:
            operating = to_dong((inp.cogs + inp.packaging + inp.fixed_fee_per_order) / denom)

    pct: Decimal | None = None
    amount: Decimal | None = None
    if operating is None:
        reasons["max_discount"] = reasons["operating_floor"]
    elif inp.list_price is None:
        reasons["max_discount"] = "missing:list_price"
    elif inp.list_price <= 0:
        reasons["max_discount"] = "list_price_non_positive"
    else:
        raw = max(inp.list_price - operating, ZERO)
        if inp.list_price <= operating:
            reasons["max_discount"] = "list_below_floor"
        rate = raw / inp.list_price
        amount = round_down_to(raw)
        if inp.seller_max_discount_rate is not None:
            rate = min(rate, inp.seller_max_discount_rate)
            amount = min(amount, round_down_to(inp.list_price * inp.seller_max_discount_rate))
        pct = pct_points(rate)

    return FloorResult(absolute, operating, pct, amount, reasons)
