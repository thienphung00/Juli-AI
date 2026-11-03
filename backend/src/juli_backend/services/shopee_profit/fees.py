"""Shopee fee formula, versioned by effective date.

A formula is a list of components (code, pct|fixed, base, rate|amount, cap). Which base a
component uses (what the buyer paid / list price / order value) is configuration, never
hard-coded: the owner confirms it per fee code from the Shopee fee schedule.

Bases (contract 10): ``buyer_paid`` / ``list_price`` / ``order_value`` as before, plus
``item_after_seller_promo`` (price before Shopee subsidy - seller promotions, per item; the
phi co dinh base) and ``order_after_seller_promo_plus_shipping`` (the same per ORDER + buyer-paid
shipping - bank promotion; the phi xu ly giao dich base).

Rules: each component rounds to whole đồng (half up); ``cap`` bounds a component's amount;
PER-ORDER components (a fixed amount, or a pct on the order base) are charged ONCE PER ORDER:
``FeeFormula.fee(line)`` alone treats the line as the whole order, and for multi-line orders
:meth:`FeeFormula.split_per_order` computes each such component on the whole order and divides
it across the lines by value (remainder on the last line, so the shares add up exactly); the
shares are passed to ``fee(line, per_order=...)``. :func:`shopee_vn_non_mall` is the ready
formula (fixed % per item + 6 % transaction per order + 3.000d infrastructure per order).
The formula valid on an order date is the version with the latest ``effective_from`` <=
that date, and none -> ``None`` (never a guess).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from juli_backend.services.shopee_profit.money import ZERO, to_dong


class FeeKind(StrEnum):
    PCT = "pct"
    FIXED = "fixed"


class FeeBase(StrEnum):
    BUYER_PAID = "buyer_paid"
    LIST_PRICE = "list_price"
    ORDER_VALUE = "order_value"
    ITEM_AFTER_SELLER_PROMO = "item_after_seller_promo"
    ORDER_AFTER_SELLER_PROMO_PLUS_SHIPPING = "order_after_seller_promo_plus_shipping"


class FeeBasis(Protocol):
    """What a fee needs from an order line (``OrderLine`` satisfies it)."""

    @property
    def list_value(self) -> Decimal: ...
    @property
    def order_value(self) -> Decimal: ...
    @property
    def buyer_paid(self) -> Decimal: ...
    @property
    def item_after_seller_promo(self) -> Decimal: ...
    @property
    def shipping_net(self) -> Decimal: ...  # buyer-paid shipping - bank promotion (NULL -> 0)


@dataclass(frozen=True)
class _OrderTotals:
    """Sum of an order's lines, viewed as one ``FeeBasis``."""

    list_value: Decimal
    order_value: Decimal
    buyer_paid: Decimal
    item_after_seller_promo: Decimal
    shipping_net: Decimal


def order_totals(lines: Sequence[FeeBasis]) -> FeeBasis:
    return _OrderTotals(
        sum((x.list_value for x in lines), ZERO),
        sum((x.order_value for x in lines), ZERO),
        sum((x.buyer_paid for x in lines), ZERO),
        sum((x.item_after_seller_promo for x in lines), ZERO),
        sum((x.shipping_net for x in lines), ZERO),
    )


@dataclass(frozen=True)
class FeeComponent:
    code: str
    kind: FeeKind
    base: FeeBase = FeeBase.BUYER_PAID
    rate: Decimal | None = None
    amount: Decimal | None = None
    cap: Decimal | None = None

    def __post_init__(self) -> None:
        if self.kind is FeeKind.PCT and (self.rate is None or not ZERO <= self.rate < 1):
            raise ValueError(f"{self.code}: pct component needs 0 <= rate < 1")
        if self.kind is FeeKind.FIXED and (self.amount is None or self.amount < 0):
            raise ValueError(f"{self.code}: fixed component needs amount >= 0")
        if self.cap is not None and self.cap < 0:
            raise ValueError(f"{self.code}: cap must be >= 0")

    @property
    def per_order(self) -> bool:
        return (
            self.kind is FeeKind.FIXED
            or self.base is FeeBase.ORDER_AFTER_SELLER_PROMO_PLUS_SHIPPING
        )

    def amount_for(self, line: FeeBasis) -> Decimal:
        """Amount on ``line`` taken as the whole base (a per-order component on one line is
        that line's own order)."""
        if self.kind is FeeKind.FIXED:
            raw = self.amount or ZERO
        else:
            base = {
                FeeBase.BUYER_PAID: line.buyer_paid,
                FeeBase.LIST_PRICE: line.list_value,
                FeeBase.ORDER_VALUE: line.order_value,
                FeeBase.ITEM_AFTER_SELLER_PROMO: line.item_after_seller_promo,
                FeeBase.ORDER_AFTER_SELLER_PROMO_PLUS_SHIPPING: (
                    line.item_after_seller_promo + line.shipping_net
                ),
            }[self.base]
            raw = max(base, ZERO) * (self.rate or ZERO)
        if self.cap is not None:
            raw = min(raw, self.cap)
        return to_dong(raw)


@dataclass(frozen=True)
class FeeResult:
    components: tuple[tuple[str, Decimal], ...]
    total: Decimal


@dataclass(frozen=True)
class FeeFormula:
    effective_from: date
    components: tuple[FeeComponent, ...]

    def fee(self, line: FeeBasis, per_order: Mapping[str, Decimal] | None = None) -> FeeResult:
        """Fee of one line. ``per_order`` = this line's share of each per-order component (see
        :meth:`split_per_order`); omitted, the line is the whole order and pays them in full."""
        parts = tuple(
            (
                c.code,
                per_order[c.code] if per_order is not None and c.per_order else c.amount_for(line),
            )
            for c in self.components
        )
        return FeeResult(parts, sum((a for _, a in parts), ZERO))

    def split_per_order(self, lines: Sequence[FeeBasis]) -> list[dict[str, Decimal]]:
        """Each per-order component computed once on the whole order, split over its lines by
        value (``buyer_paid``); whole đồng, remainder on the last line so shares sum exactly."""
        n = len(lines)
        out: list[dict[str, Decimal]] = [{} for _ in range(n)]
        if n == 0:
            return out
        weights = [max(x.buyer_paid, ZERO) for x in lines]
        total_w = sum(weights, ZERO)
        whole = order_totals(lines)
        for c in self.components:
            if not c.per_order:
                continue
            charge = c.amount_for(whole)
            left = charge
            for i, w in enumerate(weights):
                if i == n - 1:
                    share = left
                elif total_w > 0:
                    share = to_dong(charge * w / total_w)
                else:
                    share = to_dong(charge / n)
                left -= share
                out[i][c.code] = share
        return out

    @property
    def pct_rate_on_buyer_paid(self) -> Decimal:
        """Sum of pct components on the price (buyer-paid, item or order base) -- the floor's
        ``phí sàn %``. The order base's shipping / bank-promotion terms are ignored here."""
        price_bases = (
            FeeBase.BUYER_PAID,
            FeeBase.ITEM_AFTER_SELLER_PROMO,
            FeeBase.ORDER_AFTER_SELLER_PROMO_PLUS_SHIPPING,
        )
        return sum(
            (
                c.rate or ZERO
                for c in self.components
                if c.kind is FeeKind.PCT and c.base in price_bases
            ),
            ZERO,
        )

    @property
    def fixed_per_order(self) -> Decimal:
        return sum((c.amount or ZERO for c in self.components if c.kind is FeeKind.FIXED), ZERO)


@dataclass(frozen=True)
class FeeSchedule:
    versions: tuple[FeeFormula, ...]

    def __post_init__(self) -> None:
        dates = [v.effective_from for v in self.versions]
        if len(set(dates)) != len(dates):
            raise ValueError("two fee formulas share an effective_from")

    def formula_on(self, on: date) -> FeeFormula | None:
        valid = [v for v in self.versions if v.effective_from <= on]
        return max(valid, key=lambda v: v.effective_from) if valid else None


TRANSACTION_FEE_RATE = Decimal("0.06")  # phi xu ly giao dich, non-Mall from 01/05/2026
INFRASTRUCTURE_FEE = Decimal(3000)  # phi ha tang per order (orders created from 01/07/2025)


def shopee_vn_non_mall(fixed_fee_rate: Decimal, effective_from: date) -> FeeFormula:
    """Shopee VN non-Mall formula (contract 10): phi co dinh ``fixed_fee_rate`` per ITEM on the
    price after seller promotions + 6 % phi xu ly giao dich per ORDER + 3.000d phi ha tang per
    order. The category rate is injected (the category table comes later). Phi dich vu
    (Voucher / Freeship Xtra) is not included: add a component when the shop is enrolled."""
    return FeeFormula(
        effective_from,
        (
            FeeComponent(
                "phi_co_dinh", FeeKind.PCT, FeeBase.ITEM_AFTER_SELLER_PROMO, rate=fixed_fee_rate
            ),
            FeeComponent(
                "phi_xu_ly_giao_dich",
                FeeKind.PCT,
                FeeBase.ORDER_AFTER_SELLER_PROMO_PLUS_SHIPPING,
                rate=TRANSACTION_FEE_RATE,
            ),
            FeeComponent("phi_ha_tang", FeeKind.FIXED, amount=INFRASTRUCTURE_FEE),
        ),
    )
