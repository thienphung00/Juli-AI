"""The shop's SKU catalogue and the current seller inputs, as the template and the
importer read them.

A SKU is one ``(item_id, variation_id)``: an item with variations is one row per
variation, an item without any is one row with ``variation_id = ""``. The names and the
seller SKU come from ``platform_items``; the list price and the platform stock from the
latest ``platform_item_snapshots`` row (the variation's own, else the item's).

``sku_scope`` is the ``shop_rules.scope_ref`` of every per-SKU rule: ``item_id`` for an
item-level SKU, ``item_id:variation_id`` for a variation (at most 100 characters, which
the rule store checks).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.run_changes import ShopRule
from juli_backend.models.shopee_profit import PlatformItemSnapshot
from juli_backend.services.shop_rules.rules import (
    ITEM_STATUS,
    MAX_DISCOUNT_PCT,
    PACKAGING,
    PRODUCT_COST,
    PRODUCT_GROUP,
    RESTOCK_DATE,
    SKU_COST,
    SKU_INPUT_RULE_KEYS,
    STOCK,
)

PLATFORM = "shopee"
ITEM_LEVEL = ""


def sku_scope(item_id: str, variation_id: str = ITEM_LEVEL) -> str:
    """The rule scope of one SKU."""
    return f"{item_id}:{variation_id}" if variation_id else item_id


def split_scope(scope_ref: str) -> tuple[str, str]:
    item_id, _, variation_id = scope_ref.partition(":")
    return item_id, variation_id


@dataclass(frozen=True)
class CatalogueSku:
    item_id: str
    variation_id: str
    sku: str
    name: str
    list_price: Decimal | None
    snapshot_stock: int | None

    @property
    def scope(self) -> str:
        return sku_scope(self.item_id, self.variation_id)


def _price(snapshot: PlatformItemSnapshot) -> Decimal | None:
    for value in (snapshot.list_price, snapshot.current_price):
        if value is not None and value > 0:
            return Decimal(value)
    return None


async def load_catalogue(session: AsyncSession, shop_id: uuid.UUID) -> list[CatalogueSku]:
    """Every SKU of the shop, ordered by item then variation."""
    items = (
        (
            await session.execute(
                select(PlatformItem).where(
                    PlatformItem.shop_id == shop_id, PlatformItem.platform == PLATFORM
                )
            )
        )
        .scalars()
        .all()
    )
    snapshots = (
        (
            await session.execute(
                select(PlatformItemSnapshot)
                .where(
                    PlatformItemSnapshot.shop_id == shop_id,
                    PlatformItemSnapshot.platform == PLATFORM,
                )
                .order_by(PlatformItemSnapshot.captured_at.desc())
            )
        )
        .scalars()
        .all()
    )
    latest: dict[tuple[str, str], PlatformItemSnapshot] = {}
    for snap in snapshots:
        latest.setdefault((snap.item_id, snap.variation_id), snap)

    names: dict[tuple[str, str], tuple[str, str]] = {}
    for item in items:
        label = item.name or ""
        if item.variation_id and item.variation_name:
            label = f"{label} · {item.variation_name}" if label else item.variation_name
        names[(item.item_id, item.variation_id)] = (item.seller_sku or "", label)
    keys = set(names) | set(latest)
    with_variations = {item for item, variation in keys if variation}
    chosen = sorted(k for k in keys if k[1] or k[0] not in with_variations)

    item_names = {k[0]: names[k][1] for k in names if not k[1] and names[k][1]}
    out: list[CatalogueSku] = []
    for key in chosen:
        item_id, variation_id = key
        sku, label = names.get(key, ("", ""))
        found = latest.get(key) or latest.get((item_id, ITEM_LEVEL))
        if not label:
            label = (found.title if found and found.title else "") or item_names.get(item_id, "")
        out.append(
            CatalogueSku(
                item_id=item_id,
                variation_id=variation_id,
                sku=sku,
                name=label,
                list_price=_price(found) if found else None,
                snapshot_stock=found.stock if found else None,
            )
        )
    return out


#: field key -> rule key, the order the template columns use.
FIELD_RULES: dict[str, str] = {
    "cost": SKU_COST,
    "packaging": PACKAGING,
    "max_discount": MAX_DISCOUNT_PCT,
    "stock": STOCK,
    "restock": RESTOCK_DATE,
    "group": PRODUCT_GROUP,
    "status": ITEM_STATUS,
}
RULE_FIELDS: dict[str, str] = {rule: field for field, rule in FIELD_RULES.items()}


@dataclass
class CurrentInputs:
    """``scope_ref -> {rule_key: value}`` for the per-SKU keys, plus the product-level
    costs and the monthly targets."""

    per_sku: dict[str, dict[str, Any]]
    product_cost: dict[str, Any]
    monthly: dict[str, dict[str, Any]]


async def load_current(session: AsyncSession, shop_id: uuid.UUID) -> CurrentInputs:
    from juli_backend.services.shop_rules.rules import MONTHLY_RULE_KEYS

    rows = (
        (
            await session.execute(
                select(ShopRule).where(
                    ShopRule.shop_id == shop_id,
                    ShopRule.rule_key.in_([*SKU_INPUT_RULE_KEYS, PRODUCT_COST, *MONTHLY_RULE_KEYS]),
                )
            )
        )
        .scalars()
        .all()
    )
    per_sku: dict[str, dict[str, Any]] = {}
    product_cost: dict[str, Any] = {}
    monthly: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.rule_key == PRODUCT_COST:
            product_cost[row.scope_ref] = row.value
        elif row.rule_key in MONTHLY_RULE_KEYS:
            monthly.setdefault(row.scope_ref, {})[row.rule_key] = row.value
        else:
            per_sku.setdefault(row.scope_ref, {})[row.rule_key] = row.value
    return CurrentInputs(per_sku=per_sku, product_cost=product_cost, monthly=monthly)


def effective_stock(sku: CatalogueSku, current: dict[str, Any]) -> int | None:
    """The seller's stock when imported, else the platform's last known stock."""
    value = current.get(STOCK)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return sku.snapshot_stock
