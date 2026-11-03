"""Shopee fee formula, versioned by effective date.

A formula is a list of components (code, pct|fixed, base, rate|amount, cap). Which base a
component uses (what the buyer paid / list price / order value) is configuration, never
hard-coded: the owner confirms it per fee code from the Shopee fee schedule.

Rules: each component rounds to whole đồng (half up); ``cap`` bounds a component's amount;
a fixed component applies once per order line passed in (pass one line per order for
single-item orders); the formula valid on an order date is the version with the latest
``effective_from`` <= that date, and none -> ``None`` (never a guess).
"""

from __future__ import annotations

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


class FeeBasis(Protocol):
    """What a fee needs from an order line (``OrderLine`` satisfies it)."""

    @property
    def list_value(self) -> Decimal: ...
    @property
    def order_value(self) -> Decimal: ...
    @property
    def buyer_paid(self) -> Decimal: ...


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

    def amount_for(self, line: FeeBasis) -> Decimal:
        if self.kind is FeeKind.FIXED:
            raw = self.amount or ZERO
        else:
            base = {
                FeeBase.BUYER_PAID: line.buyer_paid,
                FeeBase.LIST_PRICE: line.list_value,
                FeeBase.ORDER_VALUE: line.order_value,
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

    def fee(self, line: FeeBasis) -> FeeResult:
        parts = tuple((c.code, c.amount_for(line)) for c in self.components)
        return FeeResult(parts, sum((a for _, a in parts), ZERO))

    @property
    def pct_rate_on_buyer_paid(self) -> Decimal:
        """Sum of pct components based on buyer-paid -- the floor's ``phí sàn %``."""
        return sum(
            (
                c.rate or ZERO
                for c in self.components
                if c.kind is FeeKind.PCT and c.base is FeeBase.BUYER_PAID
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
