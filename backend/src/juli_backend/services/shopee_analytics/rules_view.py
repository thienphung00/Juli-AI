"""The seller's rules relevant to profit, as the analytics read them (``shop_rules``, current).

Cost rules (contract 13): ``sku_cost`` (scope = SKU or variation id, per unit), ``product_cost``
(scope = item id, per unit), ``packaging_cost`` (scope = SKU or item id, per order line). The
targets and the daily marketing cap are the Cài đặt › Mục tiêu keys; they are read by the names
below (the first present alias wins) and are simply absent until the seller sets them -- a
missing target is ``None``, never a default.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

SKU_COST = "sku_cost"
PRODUCT_COST = "product_cost"
PACKAGING_COST = "packaging_cost"
MIN_MARGIN_PCT = "min_margin_pct"
MAX_DISCOUNT_PCT = "max_discount_pct"
DEFAULT_MAX_DISCOUNT_PCT = "default_max_discount_pct"

TARGET_ALIASES: dict[str, tuple[str, ...]] = {
    "gmv_month": ("monthly_gmv_target", "target_gmv_month", "gmv_target_month"),
    "orders_month": ("monthly_orders_target", "target_orders_month", "orders_target_month"),
    "aov_month": ("monthly_aov_target", "target_aov_month", "aov_target_month"),
    "margin_pct": (
        "monthly_margin_target",
        "target_margin_pct",
        "margin_target_pct",
        MIN_MARGIN_PCT,
    ),
    "daily_marketing_cap": ("daily_marketing_cap", "marketing_cap_daily", "daily_ad_budget_cap"),
}
RULE_KEYS_READ: tuple[str, ...] = (
    SKU_COST,
    PRODUCT_COST,
    PACKAGING_COST,
    MAX_DISCOUNT_PCT,
    DEFAULT_MAX_DISCOUNT_PCT,
    *(alias for aliases in TARGET_ALIASES.values() for alias in aliases),
)


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, dict):  # tolerate {"value": n}
        return _number(value.get("value"))
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - an unreadable value is "not set"
        return None


_MONTH = re.compile(r"\d{4}-\d{2}")


@dataclass(frozen=True)
class RuleRow:
    rule_key: str
    scope_ref: str
    value: Any


@dataclass
class ProfitRules:
    sku_cost: dict[str, Decimal] = field(default_factory=dict)
    product_cost: dict[str, Decimal] = field(default_factory=dict)
    packaging_by_key: dict[str, Decimal] = field(default_factory=dict)
    max_discount_pct: dict[str, Decimal] = field(default_factory=dict)
    default_max_discount_pct: Decimal | None = None
    targets: dict[str, Decimal | None] = field(default_factory=dict)
    #: month ("YYYY-MM") -> target name -> value, from the seller import's monthly targets (Step 4).
    targets_by_month: dict[str, dict[str, Decimal]] = field(default_factory=dict)

    def target(self, name: str) -> Decimal | None:
        return self.targets.get(name)

    def for_month(self, month: str) -> ProfitRules:
        """These rules with the month's own targets over the shop-wide ones."""
        merged = dict(self.targets)
        merged.update(self.targets_by_month.get(month, {}))
        return replace(self, targets=merged)


def read_rules(rows: Iterable[RuleRow]) -> ProfitRules:
    rules = ProfitRules()
    shop_wide: dict[str, Decimal] = {}
    monthly: dict[str, dict[str, Decimal]] = {}
    for row in rows:
        number = _number(row.value)
        if number is None:
            continue
        scope = (row.scope_ref or "").strip()
        if row.rule_key == SKU_COST and scope:
            rules.sku_cost[scope] = number
        elif row.rule_key == PRODUCT_COST and scope:
            rules.product_cost[scope] = number
        elif row.rule_key == PACKAGING_COST and scope:
            rules.packaging_by_key[scope] = number
        elif row.rule_key == MAX_DISCOUNT_PCT and scope:
            rules.max_discount_pct[scope] = number
        elif row.rule_key == DEFAULT_MAX_DISCOUNT_PCT and not scope:
            rules.default_max_discount_pct = number
        elif not scope:
            shop_wide[row.rule_key] = number
        elif _MONTH.fullmatch(scope):
            monthly.setdefault(scope, {})[row.rule_key] = number
    for name, aliases in TARGET_ALIASES.items():
        rules.targets[name] = next((shop_wide[a] for a in aliases if a in shop_wide), None)
        for month, keyed in monthly.items():
            value = next((keyed[a] for a in aliases if a in keyed), None)
            if value is not None:
                rules.targets_by_month.setdefault(month, {})[name] = value
    return rules


def rules_summary(rules: ProfitRules) -> Mapping[str, Any]:
    return {
        "sku_cost_count": len(rules.sku_cost),
        "product_cost_count": len(rules.product_cost),
        "packaging_count": len(rules.packaging_by_key),
        "targets": {k: (float(v) if v is not None else None) for k, v in rules.targets.items()},
    }
