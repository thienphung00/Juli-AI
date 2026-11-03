"""The cost fallback and which SKUs use it (owner rule, p90-metrics §13).

A SKU with no imported cost -- no ``sku_cost`` and no ``product_cost`` for its item -- is
costed at one third of its list price, labelled **assumed**. It is the default
gross-margin rule at 66,7 % (``100 - 100/3``): the seller's own ``default_gross_margin_pct``
replaces it when set. ``cost_fallbacks`` lists the SKUs that are on the fallback so the
screen and the profit pages can say so instead of passing the number off as the seller's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import ShopRule
from juli_backend.services.shop_inputs.catalogue import (
    CatalogueSku,
    CurrentInputs,
    load_catalogue,
    load_current,
)
from juli_backend.services.shop_rules import economics
from juli_backend.services.shop_rules.rules import DEFAULT_GROSS_MARGIN_PCT, SKU_COST

_HUNDRED = Decimal(100)
#: Cost as a share of the list price when nothing else is known.
ASSUMED_COST_SHARE = economics.ASSUMED_COST_SHARE
#: The default gross margin that share stands for: 66,7 %.
OWNER_DEFAULT_GROSS_MARGIN_PCT = _HUNDRED * (1 - ASSUMED_COST_SHARE)

CostSource = Literal["sku", "product", "default_margin_rule", "assumed_one_third"]


@dataclass(frozen=True)
class CostFallback:
    item_id: str
    variation_id: str
    sku: str
    name: str
    list_price: Decimal | None
    assumed_cost: Decimal | None
    #: ``default_margin_rule`` (the shop set a margin) or ``assumed_one_third`` (owner rule).
    source: CostSource
    margin_pct: Decimal


def assumed_cost(list_price: Decimal, margin_pct: Decimal | None = None) -> Decimal:
    """``list_price × (1 − margin)``; one third of the price without a margin."""
    if margin_pct is None:
        return list_price / 3
    return list_price * (1 - margin_pct / _HUNDRED)


def _margin_rule(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        margin = Decimal(str(value))
    except ArithmeticError:
        return None
    return margin if Decimal(0) < margin < _HUNDRED else None


def has_imported_cost(sku: CatalogueSku, current: CurrentInputs) -> bool:
    return SKU_COST in current.per_sku.get(sku.scope, {}) or sku.item_id in current.product_cost


async def default_margin_rule(session: AsyncSession, shop_id: uuid.UUID) -> Decimal | None:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(ShopRule.value).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == DEFAULT_GROSS_MARGIN_PCT,
                ShopRule.scope_ref == "",
            )
        )
    ).scalar_one_or_none()
    return _margin_rule(row)


async def cost_fallbacks(session: AsyncSession, shop_id: uuid.UUID) -> list[CostFallback]:
    """The SKUs that have no imported cost, with the cost they are assumed to have."""
    catalogue = await load_catalogue(session, shop_id)
    current = await load_current(session, shop_id)
    margin_rule = await default_margin_rule(session, shop_id)
    margin = margin_rule if margin_rule is not None else OWNER_DEFAULT_GROSS_MARGIN_PCT
    source: CostSource = "default_margin_rule" if margin_rule is not None else "assumed_one_third"
    return [
        CostFallback(
            item_id=sku.item_id,
            variation_id=sku.variation_id,
            sku=sku.sku,
            name=sku.name,
            list_price=sku.list_price,
            assumed_cost=assumed_cost(sku.list_price, margin_rule) if sku.list_price else None,
            source=source,
            margin_pct=margin,
        )
        for sku in catalogue
        if not has_imported_cost(sku, current)
    ]
