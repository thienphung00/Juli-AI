"""The seller's own VAT in the profit (P91 D-12): a company that invoices VAT keeps revenue ÷
(1 + rate), not the VAT-inclusive price the buyer paid.

Two shop flags, both UNSET until the seller states them (never guessed): ``prices_include_vat``
(the listing prices contain VAT) and ``cost_includes_vat`` (the giá vốn entered contains VAT that
the seller credits as input VAT). A per-SKU ``vat_rate`` of 0, 5, 8 or 10 %.

- ``prices_include_vat`` true: revenue = buyer paid ÷ (1 + rate); the VAT is output tax, not income.
- ``prices_include_vat`` false: prices are before VAT, the buyer's VAT is on top: nothing to take
  out. Unset: the profit is shown BEFORE VAT and says so.
- ``cost_includes_vat`` true: cost = giá vốn ÷ (1 + rate), the VAT part is credited. Unset or
  false: the cost is taken as entered.
- a flag that needs the rate while the SKU has none: the line's profit is unknown (``vat_rate``
  missing), never computed at 0 %.

Shopee's own fees are not adjusted (they are VAT-inclusive invoices to the seller).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO, to_dong

#: The VAT rates a Vietnamese seller can state, as percent.
VAT_RATES_PCT: tuple[int, ...] = (0, 5, 8, 10)
BASIS_BEFORE = "before_vat"
BASIS_AFTER = "after_vat"


@dataclass(frozen=True)
class VatTreatment:
    """The shop's VAT flags and one line's SKU rate (a fraction, 0.08 for 8 %; None = not set)."""

    prices_include_vat: bool | None
    cost_includes_vat: bool | None
    rate: Decimal | None = None

    @property
    def revenue_needs_rate(self) -> bool:
        return self.prices_include_vat is True

    @property
    def cost_needs_rate(self) -> bool:
        return self.cost_includes_vat is True

    @property
    def basis(self) -> str:
        """``after_vat`` once the seller has said whether the prices carry VAT."""
        return BASIS_BEFORE if self.prices_include_vat is None else BASIS_AFTER


def output_vat(buyer_paid: Decimal, vat: VatTreatment | None) -> Decimal | None:
    """The VAT inside ``buyer_paid`` to take out of revenue; 0 when prices carry none;
    ``None`` when it is due but the SKU has no rate."""
    if vat is None or not vat.revenue_needs_rate:
        return ZERO
    if vat.rate is None:
        return None
    return to_dong(buyer_paid - buyer_paid / (1 + vat.rate))


def input_vat_credit(cogs: Decimal, vat: VatTreatment | None) -> Decimal | None:
    """The VAT inside the giá vốn that is credited; 0 when the cost carries none;
    ``None`` when it is due but the SKU has no rate."""
    if vat is None or not vat.cost_needs_rate:
        return ZERO
    if vat.rate is None:
        return None
    return to_dong(cogs - cogs / (1 + vat.rate))


def vat_label(prices_include_vat: bool | None, cost_includes_vat: bool | None) -> dict[str, object]:
    """What the profit pages print next to a profit figure."""
    basis = BASIS_BEFORE if prices_include_vat is None else BASIS_AFTER
    if prices_include_vat is None:
        text = "Lợi nhuận trước VAT: chưa khai báo giá bán đã gồm VAT hay chưa"
    elif prices_include_vat:
        text = "Lợi nhuận sau VAT: doanh thu = giá khách trả ÷ (1 + thuế suất VAT)"
    else:
        text = "Lợi nhuận sau VAT: giá bán chưa gồm VAT, không có VAT trong doanh thu"
    return {
        "basis": basis,
        "prices_include_vat": prices_include_vat,
        "cost_includes_vat": cost_includes_vat,
        "label": text,
    }
