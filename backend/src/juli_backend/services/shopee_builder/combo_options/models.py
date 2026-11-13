"""Plain, frozen inputs and outputs of the combo builder (no I/O)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from juli_backend.services.shopee_builder.combo_options import config
from juli_backend.services.shopee_builder.variations import Rates
from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_recommendations.unit_cost import UnitCost

Form = Literal["multi_pack", "bundle"]
RuleKind = Literal["ladder", "target_margin", "per_box"]


def _dec(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


@dataclass(frozen=True)
class VariationIn:
    """One variation: an economics row of ``shopee_builder.variations`` plus the unit cost."""

    variation_id: str
    name: str
    selling_price: Decimal | None
    cost: UnitCost | None = None
    sku: str | None = None
    stock: int | None = None
    sold_30d: bool = False
    orders_30d: int = 0

    @classmethod
    def from_row(cls, row: Mapping[str, Any], cost: UnitCost | None = None) -> VariationIn:
        """Build from a ``variations.variation_rows`` / ``with_orders`` row."""
        orders = int(row.get("orders_30d") or 0)
        return cls(
            variation_id=str(row.get("variation_id") or ""),
            name=str(row.get("name") or ""),
            selling_price=_dec(row.get("selling_price")),
            cost=cost,
            sku=row.get("sku"),
            stock=row.get("stock"),
            sold_30d=bool(row.get("sold_30d", orders > 0)),
            orders_30d=orders,
        )


@dataclass(frozen=True)
class ProductIn:
    item_id: str
    name: str
    variations: tuple[VariationIn, ...]
    code: str | None = None  # short code used in the SKU; defaults to the item id


@dataclass(frozen=True)
class BundleSpec:
    """A bundle of several products: ``quantities`` = ((item_id, quantity), ...)."""

    quantities: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Packs:
    sizes: tuple[int, ...] = (3, 5, 10)
    bundles: tuple[BundleSpec, ...] = ()


@dataclass(frozen=True)
class Rules:
    same_variation: bool = True  # one variation inside a multi-pack
    sold_only: bool = True  # only variations sold in the last 30 days
    max_options: int = config.DEFAULT_MAX_OPTIONS
    shop_code: str = config.DEFAULT_SHOP_CODE
    unit: str = config.DEFAULT_UNIT


@dataclass(frozen=True)
class Member:
    item_id: str
    product_name: str
    variation_id: str
    variation_name: str
    quantity: int
    unit_price: Decimal | None
    cost: UnitCost | None
    stock: int | None
    item_code: str  # slug of the product code, for the SKU
    var_code: str  # slug of the variation SKU / id, for the SKU


@dataclass(frozen=True)
class ComboOption:
    key: str
    form: Form
    members: tuple[Member, ...]
    units: int  # boxes in the option (sum of quantities)
    name: str  # full label for the table / listing title (<= title limit)
    option_name: str  # the option name inside the listing (<= Shopee option-name limit)
    sku: str
    suggested_stock: int | None
    stock_note: str = config.STOCK_NOTE


@dataclass(frozen=True)
class OptionCount:
    total: int  # before the cap
    kept: int  # what generate returns
    over_cap: int
    by_form: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceRule:
    kind: RuleKind = "ladder"
    ladder: Mapping[int, Decimal] = field(default_factory=lambda: dict(config.DEFAULT_LADDER))
    target_margin_pct: Decimal | None = None
    box_price: Decimal | None = None
    round_to: int = config.DEFAULT_ROUND_TO
    ending_9: bool = False


@dataclass(frozen=True)
class Economics:
    """``rates`` = item id -> the product's measured 30-day voucher / commission / ad rates
    (``variations.measured_rates``). With rates, pricing and the floor use Biên cuối (ADR-122
    d.12); without them (or when a member has none) they use the price-only margin."""

    schedule: FeeSchedule
    on: date
    rates: Mapping[str, Rates] = field(default_factory=dict)


@dataclass(frozen=True)
class PricedRow:
    option: ComboOption
    price: Decimal | None
    price_per_box: Decimal | None
    separate_total: Decimal | None
    saving: Decimal | None
    saving_pct: Decimal | None
    margin_pct: Decimal | None  # Biên ở giá bán (chắc chắn)
    profit_per_order: Decimal | None
    margin_label: str | None  # "chưa tính" when margin / profit cannot be computed
    below_floor: bool | None  # None = unknown; warns, never blocks
    overridden: bool = False
    basis: str = ""
    notes: tuple[str, ...] = ()
    final_margin_pct: Decimal | None = None  # Biên cuối (ước tính); None = no measured rates
    final_rates: Rates | None = None
    floor_basis: str = "price"  # which margin the floor check read: "final" | "price"


__all__ = [
    "BundleSpec",
    "ComboOption",
    "Economics",
    "Form",
    "Member",
    "OptionCount",
    "Packs",
    "PriceRule",
    "PricedRow",
    "ProductIn",
    "Rules",
    "VariationIn",
]
