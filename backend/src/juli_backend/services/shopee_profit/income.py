"""The income export's actual amounts per order, and their split over the order's lines
(P91 D-12). Pure: the stored ``shopee_order_income`` row is read into :class:`IncomeOrder` by the
analytics loader, and :func:`split_income` hands each line its share.

Everything in :class:`IncomeOrder` is what the SELLER bore, positive = a cost (the income export
shows a cost as a negative number; the ingest parser has already turned them round). ``None`` =
the export did not state it. The actuals WIN over the order export's fee columns and over the fee
formula: a line with an income share is charged exactly its share of what Shopee charged.

Per-order amounts are split over the order's lines by value (``buyer_paid`` of each line, equal
shares when no line has a value), in whole cents, largest remainder first, so the shares always
add up to the order's amount.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO

CENT = Decimal("0.01")

#: Fee codes of the actual fee components, in the order they are shown.
FEE_FIXED = "phi_co_dinh"
FEE_SERVICE = "phi_dich_vu"
FEE_PAYMENT = "phi_xu_ly_giao_dich"
FEE_PISHIP = "phi_dich_vu_piship"
FEE_NTTD = "phi_nttd"
FEE_CODES = (FEE_FIXED, FEE_SERVICE, FEE_PAYMENT, FEE_PISHIP, FEE_NTTD)
#: The order amounts that are costs on top of the fees, in the order they are shown.
COST_NET_SHIPPING = "van_chuyen_rong"
COST_RETURN_SHIPPING = "van_chuyen_tra_hang"
COST_REFUND = "hoan_tien"
COST_COIN = "xu_nguoi_ban_chiu"
COST_TAX = "thue_gtgt_tncn_khau_tru"
COST_TRADE_IN = "trade_in_nguoi_ban"
COST_COMPENSATION = "den_bu_mat_hang"


@dataclass(frozen=True)
class IncomeOrder:
    """One order's actuals from the income export (a ``shopee_order_income`` row)."""

    order_ref: str
    fee_fixed: Decimal | None = None
    fee_service: Decimal | None = None
    fee_payment: Decimal | None = None
    fee_piship: Decimal | None = None
    fee_nttd: Decimal | None = None
    affiliate_commission: Decimal | None = None
    net_shipping_cost: Decimal | None = None
    return_ship_refund: Decimal | None = None
    return_ship_failed: Decimal | None = None
    refund_amount: Decimal | None = None
    lost_compensation: Decimal | None = None
    vat_withheld: Decimal | None = None
    pit_withheld: Decimal | None = None
    seller_coin_borne: Decimal | None = None
    trade_in_bonus_seller: Decimal | None = None
    payout: Decimal | None = None

    def fee(self, code: str) -> Decimal:
        return {
            FEE_FIXED: self.fee_fixed,
            FEE_SERVICE: self.fee_service,
            FEE_PAYMENT: self.fee_payment,
            FEE_PISHIP: self.fee_piship,
            FEE_NTTD: self.fee_nttd,
        }[code] or ZERO

    @property
    def fees_total(self) -> Decimal:
        return sum((self.fee(code) for code in FEE_CODES), ZERO)

    @property
    def return_shipping(self) -> Decimal:
        return (self.return_ship_refund or ZERO) + (self.return_ship_failed or ZERO)

    @property
    def tax_withheld(self) -> Decimal:
        return (self.vat_withheld or ZERO) + (self.pit_withheld or ZERO)


@dataclass(frozen=True)
class LineIncome:
    """One line's share of its order's actuals (cost positive)."""

    fees: tuple[tuple[str, Decimal], ...]
    commission: Decimal
    net_shipping: Decimal
    return_shipping: Decimal
    refund: Decimal
    compensation: Decimal
    tax_withheld: Decimal
    seller_coin: Decimal
    trade_in: Decimal
    payout: Decimal | None

    @property
    def fees_total(self) -> Decimal:
        return sum((amount for _, amount in self.fees), ZERO)

    def other_costs(self, *, with_refund: bool) -> tuple[tuple[str, Decimal], ...]:
        """The costs on top of fees and commission. ``with_refund``: the line was delivered, so
        a refund is money given back after the sale (an accepted-refund line already earns 0)."""
        parts: list[tuple[str, Decimal]] = [
            (COST_NET_SHIPPING, self.net_shipping),
            (COST_RETURN_SHIPPING, self.return_shipping),
            (COST_COIN, self.seller_coin),
            (COST_TAX, self.tax_withheld),
            (COST_TRADE_IN, self.trade_in),
        ]
        if with_refund:
            parts.append((COST_REFUND, self.refund))
        if self.compensation:
            parts.append((COST_COMPENSATION, -self.compensation))
        return tuple(parts)


def _cents(value: Decimal) -> int:
    scaled = value * 100
    return int(scaled.to_integral_value())


def split_amount(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """``total`` cut into cents proportional to ``weights`` (equal shares when none is positive);
    the pieces add up to ``total`` exactly (largest remainder, ties to the earlier line)."""
    count = len(weights)
    if count == 0:
        raise ValueError("no lines to split over")
    cents = _cents(total)
    shares = [max(_cents(w), 0) for w in weights]
    if sum(shares) <= 0:
        shares = [1] * count
    weight_sum = sum(shares)
    sign = -1 if cents < 0 else 1
    magnitude = abs(cents)
    parts = [divmod(magnitude * share, weight_sum) for share in shares]
    pieces = [quotient for quotient, _ in parts]
    left = magnitude - sum(pieces)
    for i in sorted(range(count), key=lambda i: (-parts[i][1], i))[:left]:
        pieces[i] += 1
    return [Decimal(sign * piece) * CENT for piece in pieces]


def split_income(income: IncomeOrder, weights: Sequence[Decimal]) -> list[LineIncome]:
    """Every line's share of the order's actuals, by ``weights`` (the lines' value)."""
    count = len(weights)

    def cut(amount: Decimal | None) -> list[Decimal]:
        return split_amount(amount or ZERO, weights) if count else []

    fees = {code: cut(income.fee(code)) for code in FEE_CODES}
    commission = cut(income.affiliate_commission)
    shipping = cut(income.net_shipping_cost)
    returns = cut(income.return_shipping)
    refund = cut(income.refund_amount)
    compensation = cut(income.lost_compensation)
    tax = cut(income.tax_withheld)
    coin = cut(income.seller_coin_borne)
    trade_in = cut(income.trade_in_bonus_seller)
    payout = split_amount(income.payout, weights) if income.payout is not None and count else None
    return [
        LineIncome(
            fees=tuple((code, fees[code][i]) for code in FEE_CODES),
            commission=commission[i],
            net_shipping=shipping[i],
            return_shipping=returns[i],
            refund=refund[i],
            compensation=compensation[i],
            tax_withheld=tax[i],
            seller_coin=coin[i],
            trade_in=trade_in[i],
            payout=payout[i] if payout is not None else None,
        )
        for i in range(count)
    ]
