"""The shop's items as stored, and the SKU -> item resolution the order export needs.

The order export names a product by SKU only, so a stored line may carry ``item_id =
'sku:<sku>'`` (the catalogue did not know the SKU when the line was loaded). Everything
downstream is keyed by the platform item id, so the lines are resolved here against
``platform_items.seller_sku`` (item and variation rows) on every read -- nothing is
rewritten. An unresolved SKU keeps its ``sku:`` id and is counted as such.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

SKU_PREFIX = "sku:"


@dataclass(frozen=True)
class Variation:
    variation_id: str
    name: str | None
    seller_sku: str | None
    status: str | None = None


@dataclass(frozen=True)
class ItemInfo:
    item_id: str
    name: str | None = None
    seller_sku: str | None = None
    status: str | None = None
    variations: tuple[Variation, ...] = ()
    category_path: tuple[str, ...] = ()
    list_price: Decimal | None = None
    current_price: Decimal | None = None
    stock: int | None = None


@dataclass
class Catalog:
    items: dict[str, ItemInfo] = field(default_factory=dict)
    sku_to_item: dict[str, str] = field(default_factory=dict)
    ambiguous_skus: set[str] = field(default_factory=set)

    def name(self, item_id: str) -> str:
        info = self.items.get(item_id)
        if info and info.name:
            return info.name
        return item_id[len(SKU_PREFIX) :] if item_id.startswith(SKU_PREFIX) else item_id

    def resolve(self, stored_item_id: str, sku: str | None, variation_sku: str | None) -> str:
        """The platform item id of a line (the stored one when it is already a real id)."""
        if stored_item_id and not stored_item_id.startswith(SKU_PREFIX):
            return stored_item_id
        for candidate in (variation_sku, sku):
            if candidate and candidate in self.sku_to_item:
                return self.sku_to_item[candidate]
        return stored_item_id


@dataclass(frozen=True)
class RawItem:
    """A ``platform_items`` row, detached from the ORM."""

    item_id: str
    variation_id: str
    name: str | None
    variation_name: str | None
    seller_sku: str | None
    status: str | None


@dataclass(frozen=True)
class RawSnapshot:
    """The newest ``platform_item_snapshots`` row of an item (variation_id '' = the item)."""

    item_id: str
    variation_id: str
    title: str | None
    list_price: Decimal | None
    current_price: Decimal | None
    stock: int | None
    category_path: tuple[str, ...]
    status: str | None


def build_catalog(items: Iterable[RawItem], snapshots: Iterable[RawSnapshot] = ()) -> Catalog:
    by_item: dict[str, list[RawItem]] = defaultdict(list)
    for row in items:
        by_item[row.item_id].append(row)
    snap: dict[str, RawSnapshot] = {s.item_id: s for s in snapshots if s.variation_id == ""}

    catalog = Catalog()
    owners: dict[str, Counter[str]] = defaultdict(Counter)
    for item_id, rows in by_item.items():
        head = next((r for r in rows if r.variation_id == ""), None)
        s = snap.get(item_id)
        catalog.items[item_id] = ItemInfo(
            item_id=item_id,
            name=(s.title if s and s.title else None) or (head.name if head else None),
            seller_sku=head.seller_sku if head else None,
            status=(s.status if s and s.status else None) or (head.status if head else None),
            variations=tuple(
                Variation(r.variation_id, r.variation_name, r.seller_sku, r.status)
                for r in rows
                if r.variation_id != ""
            ),
            category_path=s.category_path if s else (),
            list_price=s.list_price if s else None,
            current_price=s.current_price if s else None,
            stock=s.stock if s else None,
        )
        for r in rows:
            if r.seller_sku:
                owners[r.seller_sku][item_id] += 1
    for sku, counter in owners.items():
        ranked = counter.most_common()
        catalog.sku_to_item[sku] = ranked[0][0]
        if len(ranked) > 1:
            catalog.ambiguous_skus.add(sku)
    for item_id, s in snap.items():  # an item known only from a snapshot
        catalog.items.setdefault(
            item_id,
            ItemInfo(
                item_id=item_id,
                name=s.title,
                status=s.status,
                category_path=s.category_path,
                list_price=s.list_price,
                current_price=s.current_price,
                stock=s.stock,
            ),
        )
    return catalog


def merge_names(catalog: Catalog, names: Mapping[str, str]) -> None:
    """Fill item names from another source (ads reports) where the catalogue has none."""
    for item_id, name in names.items():
        info = catalog.items.get(item_id)
        if info is None:
            catalog.items[item_id] = ItemInfo(item_id=item_id, name=name)
        elif not info.name:
            catalog.items[item_id] = ItemInfo(**{**info.__dict__, "name": name})
