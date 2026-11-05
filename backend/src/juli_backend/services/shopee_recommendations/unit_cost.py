"""P92: the giá vốn and packaging of a listing / variation read straight from the seller's rules.

The profit engine costs a SKU only when it has order lines in the window (``Costs`` is built from
the lines) and falls back to one third of the list price when the seller gave no cost. The P92
builder also prices things that have not sold lately (a gift, a new variation, a listing nobody
bought this month) and must say "chưa tính" instead of an assumed cost. This module reads the
imported rules only -- ``sku_cost`` > ``product_cost``, x the pack count (or a bill of materials),
``packaging_cost`` -- and returns ``None`` when the seller has not stated a cost. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_analytics.rules_view import ProfitRules
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.pack import (
    SOURCE_NAME,
    SOURCE_SET,
    SOURCE_SINGLE,
    components_cost,
    pack_count_from_name,
)
from juli_backend.services.shopee_profit.vat import VatTreatment


@dataclass(frozen=True)
class UnitCost:
    """Cost of ONE sold unit of a variation (a "Combo 3 hộp" unit holds three single items)."""

    cogs: Decimal | None  # per sold unit; None = the seller has not stated a giá vốn
    packaging: Decimal | None  # per order line; None = not stated (counted as 0, flagged)
    pack_count: int
    pack_source: str  # set (seller) | name (read from the variation name) | single
    bom: bool
    vat: VatTreatment

    @property
    def known(self) -> bool:
        return self.cogs is not None


def scope_of(item_id: str, variation_id: str = "") -> str:
    return f"{item_id}:{variation_id}" if variation_id else item_id


def unit_cost(
    rules: ProfitRules,
    item_id: str,
    variation_id: str = "",
    *,
    seller_sku: str | None = None,
    variation_name: str | None = None,
) -> UnitCost:
    """The seller's cost of one sold unit, else ``cogs = None`` (never the 1/3 fallback)."""
    scope = scope_of(item_id, variation_id)
    base = seller_sku or item_id
    components = rules.pack_components.get(scope) or rules.pack_components.get(item_id) or ()
    if scope in rules.pack_count:
        pack, source = rules.pack_count[scope], SOURCE_SET
    elif (named := pack_count_from_name(variation_name)) is not None:
        pack, source = named, SOURCE_NAME
    else:
        pack, source = 1, SOURCE_SINGLE
    cogs: Decimal | None
    if components:
        cogs = components_cost(components, dict(rules.sku_cost))
    else:
        single = next(
            (
                v
                for v in (
                    rules.sku_cost.get(scope),
                    rules.sku_cost.get(base),
                    rules.product_cost.get(item_id),
                )
                if v is not None
            ),
            None,
        )
        cogs = None if single is None else single * pack
    packaging = next(
        (
            v
            for v in (
                rules.packaging_by_key.get(scope),
                rules.packaging_by_key.get(base),
                rules.packaging_by_key.get(item_id),
            )
            if v is not None
        ),
        None,
    )
    rate = next(
        (v for v in (rules.vat_rate.get(scope), rules.vat_rate.get(base)) if v is not None), None
    )
    return UnitCost(
        cogs,
        packaging,
        pack,
        source,
        bool(components),
        VatTreatment(rules.prices_include_vat, rules.cost_includes_vat, rate),
    )


def gift_cost_of(cost: UnitCost) -> Decimal | None:
    """What handing out one unit costs: giá vốn + đóng gói; None when giá vốn is not stated."""
    if cost.cogs is None:
        return None
    return cost.cogs + (cost.packaging or ZERO)


__all__ = ["UnitCost", "gift_cost_of", "scope_of", "unit_cost"]
