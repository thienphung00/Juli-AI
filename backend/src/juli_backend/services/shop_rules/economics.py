"""The seller's economics, typed, for the ranking layer (fast track P14-F).

``shop_economics`` reads the rule store once and returns a frozen
``ShopEconomics``: costs, margin and discount limits, programme fee, campaign
participation, ads targets and the regular LIVE slots -- everything the seller
tells Juli because no TikTok API does (contract
``fasttrack/contracts/p14-rules-and-cost.md`` §3).

Nothing reads it yet: the ranking / promotion consumers of D24.5, D24.11 and
D24.12 will. Every field is ``None`` / empty until the seller sets it, and the
helpers return ``None`` rather than guess.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shop_rules.rules import RuleValue, ShopRules, get_rules

_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class LiveSlot:
    """A regular LIVE slot: ``days`` (``mon``..``sun``), ``start``-``end`` local time.

    ``end`` earlier than ``start`` means the slot runs past midnight.
    """

    days: tuple[str, ...]
    start: time
    end: time


@dataclass(frozen=True)
class ShopEconomics:
    product_cost: Mapping[str, Decimal] = field(default_factory=dict)
    sku_cost: Mapping[str, Decimal] = field(default_factory=dict)
    default_gross_margin_pct: Decimal | None = None
    min_margin_pct: Decimal | None = None
    default_max_discount_pct: Decimal | None = None
    sku_max_discount_pct: Mapping[str, Decimal] = field(default_factory=dict)
    program_fee_pct: Decimal | None = None
    joins_platform_campaigns: bool | None = None
    platform_campaign_note: str | None = None
    target_roas: Decimal | None = None
    gmv_max_daily_budget: Decimal | None = None
    live_schedule: tuple[LiveSlot, ...] = ()

    def unit_cost(
        self, *, sku_id: str | None, product_id: str | None, unit_price: Decimal | None
    ) -> Decimal | None:
        """One unit's cost: SKU cost, else product cost, else price × (1 − default margin)."""
        if sku_id and sku_id in self.sku_cost:
            return self.sku_cost[sku_id]
        if product_id and product_id in self.product_cost:
            return self.product_cost[product_id]
        if unit_price is not None and self.default_gross_margin_pct is not None:
            return unit_price * (1 - self.default_gross_margin_pct / _HUNDRED)
        return None

    def gross_margin(
        self, *, sku_id: str | None, product_id: str | None, unit_price: Decimal
    ) -> Decimal | None:
        """(price − cost − programme fee) ÷ price, as a fraction; ``None`` without a cost."""
        if unit_price <= 0:
            return None
        cost = self.unit_cost(sku_id=sku_id, product_id=product_id, unit_price=unit_price)
        if cost is None:
            return None
        fee = unit_price * (self.program_fee_pct or Decimal(0)) / _HUNDRED
        return (unit_price - cost - fee) / unit_price

    def break_even_roas(
        self, *, sku_id: str | None, product_id: str | None, unit_price: Decimal
    ) -> Decimal | None:
        """1 ÷ margin (D24.11); ``None`` when the margin is unknown or not positive."""
        margin = self.gross_margin(sku_id=sku_id, product_id=product_id, unit_price=unit_price)
        if margin is None or margin <= 0:
            return None
        return 1 / margin

    def max_discount_pct(self, sku_id: str | None) -> Decimal | None:
        """The SKU's own cap, else the shop-wide one; ``None`` = no price recommendation."""
        if sku_id and sku_id in self.sku_max_discount_pct:
            return self.sku_max_discount_pct[sku_id]
        return self.default_max_discount_pct


def _decimal(value: RuleValue | None) -> Decimal | None:
    if value is None or value.value is None or isinstance(value.value, bool):
        return None
    try:
        return Decimal(str(value.value))
    except ArithmeticError:
        return None


def _decimals(values: Mapping[str, RuleValue]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for key, item in values.items():
        number = _decimal(item)
        if number is not None:
            out[key] = number
    return out


def _clock(text: str) -> time:
    hour, minute = text.split(":")
    return time(int(hour), int(minute))


def _slots(value: RuleValue | None) -> tuple[LiveSlot, ...]:
    raw: Any = value.value if value is not None else None
    if not isinstance(raw, list):
        return ()
    slots: list[LiveSlot] = []
    for slot in raw:
        try:
            slots.append(
                LiveSlot(
                    days=tuple(str(d) for d in slot["days"]),
                    start=_clock(slot["start"]),
                    end=_clock(slot["end"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(slots)


def economics_from_rules(rules: ShopRules) -> ShopEconomics:
    """``ShopRules`` (as the API returns them) -> ``ShopEconomics``."""
    joins = rules.joins_platform_campaigns
    note = rules.platform_campaign_note
    return ShopEconomics(
        product_cost=_decimals(rules.product_cost),
        sku_cost=_decimals(rules.sku_cost),
        default_gross_margin_pct=_decimal(rules.default_gross_margin_pct),
        min_margin_pct=_decimal(rules.min_margin_pct),
        default_max_discount_pct=_decimal(rules.default_max_discount_pct),
        sku_max_discount_pct=_decimals(rules.max_discount_pct),
        program_fee_pct=_decimal(rules.program_fee_pct),
        joins_platform_campaigns=joins.value if joins and isinstance(joins.value, bool) else None,
        platform_campaign_note=note.value if note and isinstance(note.value, str) else None,
        target_roas=_decimal(rules.target_roas),
        gmv_max_daily_budget=_decimal(rules.gmv_max_daily_budget),
        live_schedule=_slots(rules.live_schedule),
    )


async def shop_economics(session: AsyncSession, shop_id: uuid.UUID) -> ShopEconomics:
    """The shop's economics from its rule store (one query)."""
    return economics_from_rules(await get_rules(session, shop_id))
