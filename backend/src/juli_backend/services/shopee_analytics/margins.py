"""ADR-122 d.12: the one place the two margins of a Shopee variation are computed from.

**Biên cuối** (ước tính) = **Biên ở giá bán** (chắc chắn) less the measured 30-day shares of what
the buyer paid that went to the shop voucher, affiliate commission and ads (ads allocated to the
SKUs of a product by revenue, so every SKU of a product carries the same ad rate). The product page
(``shopee_analytics.product``) and the builder (``shopee_builder.variations``, combo pricing) both
import these, so the two screens can never compute Biên cuối differently. Pure.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from juli_backend.services.shopee_profit.money import ZERO, pct_points

HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Rates:
    """Measured shares of the money the buyer paid (fractions): shop voucher, affiliate commission
    and ad cost (ads allocated to the SKUs of a product by revenue, like the product page)."""

    voucher: Decimal = ZERO
    commission: Decimal = ZERO
    ads: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.voucher + self.commission + self.ads

    def json(self) -> dict[str, float]:
        return {
            "voucher_pct": float(pct_points(self.voucher) or 0),
            "commission_pct": float(pct_points(self.commission) or 0),
            "ads_pct": float(pct_points(self.ads) or 0),
        }


def measured_rates(
    pairs: Iterable[tuple[Any, Any]], product_spend: Decimal | None
) -> tuple[Rates | None, dict[str, Rates]]:
    """``(the product's rates, SKU key -> rates)`` from the product's ``(OrderLine, breakdown)``
    pairs of the window; cancelled / excluded lines are left out. ``product_spend`` = the ads
    spend allocated to the product in the same window. ``(None, {})`` without a paid line."""
    paid: dict[str, Decimal] = {}
    voucher: dict[str, Decimal] = {}
    commission: dict[str, Decimal] = {}
    for ln, pb in pairs:
        if pb.excluded_reason is not None:
            continue
        paid[ln.sku] = paid.get(ln.sku, ZERO) + pb.revenue
        voucher[ln.sku] = voucher.get(ln.sku, ZERO) + pb.voucher
        commission[ln.sku] = commission.get(ln.sku, ZERO) + (pb.commission or ZERO)
    total = sum(paid.values(), ZERO)
    if total <= 0:
        return None, {}
    ads = (product_spend or ZERO) / total  # revenue-weighted: the same rate on every SKU
    by_sku = {
        sku: Rates(voucher[sku] / p, commission[sku] / p, ads) for sku, p in paid.items() if p > 0
    }
    return Rates(
        sum(voucher.values(), ZERO) / total, sum(commission.values(), ZERO) / total, ads
    ), by_sku


def final_margin(margin_pct: float | Decimal | None, rates: Rates | None) -> float | None:
    """Biên cuối in percent points: the price-only margin less the measured rates."""
    if margin_pct is None or rates is None:
        return None
    value = Decimal(str(margin_pct)) - rates.total * HUNDRED
    return float(value.quantize(Decimal("0.1"), ROUND_HALF_UP))
