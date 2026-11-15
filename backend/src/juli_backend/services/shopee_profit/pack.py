"""Pack multiplier and bill of materials: how many single items one sold unit contains (P91 D-12).

Combo variations reuse the base SKU ("Combo 3 hộp", "Combo 5 hộp", "Combo 10 hộp" all carry
G500001), so a SKU's giá vốn is the cost of ONE item and a sold unit costs ``pack_count`` of
them. A listing with no SKU of its own (a multi-product combo) has a bill of materials instead:
component SKU x quantity. Packaging is per ORDER LINE and is never multiplied here.

``pack_count_from_name`` is the default the seller template shows and the profit reads until the
seller says otherwise: "Combo 3 hộp" 3, "combo 10 hộp size L" 10, "Combo 2 30cm x5m" 2, "Set 3 ..."
3; any other name 1. Only the words "combo" and "set" count - a "Bộ 2 màu" or a size such as
"30cm" is not a pack.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO

#: A pack larger than this is not a pack count (a typo in a name, a size).
MAX_PACK_COUNT = 100
_PACK = re.compile(r"(?<!\w)(?:combo|set)\s*(\d{1,3})(?!\d)")

SOURCE_SET = "set"
SOURCE_NAME = "name"
SOURCE_SINGLE = "single"


def pack_count_from_name(name: str | None) -> int | None:
    """The pack count a variation name states ("Combo 3 hộp" -> 3), else ``None``."""
    if not name:
        return None
    text = unicodedata.normalize("NFC", name).casefold()
    match = _PACK.search(text)
    if match is None:
        return None
    count = int(match.group(1))
    return count if 1 <= count <= MAX_PACK_COUNT else None


_MEASURE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(ml|l|lít|lit|g|gr|kg)(?![a-z])")
_MEASURE_BASE = {
    "ml": ("ml", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "lít": ("ml", Decimal(1000)),
    "lit": ("ml", Decimal(1000)),
    "g": ("g", Decimal(1)),
    "gr": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)),
}


def measure_from_text(*texts: str | None) -> tuple[Decimal, str] | None:
    """The first content a name states, in ml or g ("Dầu gội 500ml" -> (500, "ml"), "1,5 kg" ->
    (1500, "g")); ``None`` when no text has one (units such as "hộp" are counted, not measured)."""
    for text in texts:
        if not text:
            continue
        match = _MEASURE.search(unicodedata.normalize("NFC", text).casefold())
        if match is None:
            continue
        base, factor = _MEASURE_BASE[match.group(2)]
        amount = Decimal(match.group(1).replace(",", ".")) * factor
        if amount > 0:
            return amount, base
    return None


def price_per_measure(
    price: Decimal | None, pack_count: int, *texts: str | None
) -> tuple[Decimal, str] | None:
    """``(price per 100 ml / 100 g, "100 ml" / "100 g")`` of one sold unit holding ``pack_count``
    packs of the stated content; ``None`` when there is no price or no stated content."""
    found = measure_from_text(*texts)
    if price is None or found is None:
        return None
    amount, base = found
    return price * 100 / (amount * max(pack_count, 1)), f"100 {base}"


@dataclass(frozen=True)
class Component:
    """One line of a bill of materials: ``qty`` of the component SKU ``sku``."""

    sku: str
    qty: int


def parse_components(value: object) -> tuple[Component, ...]:
    """A stored ``pack_components`` rule value (``[{"sku": "...", "qty": 2}, ...]``) as
    components; an unreadable entry is dropped."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    out: list[Component] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        sku, qty = entry.get("sku"), entry.get("qty")
        if isinstance(sku, str) and sku.strip() and isinstance(qty, int) and qty >= 1:
            out.append(Component(sku.strip(), qty))
    return tuple(out)


def components_cost(
    components: Sequence[Component], unit_costs: Mapping[str, Decimal]
) -> Decimal | None:
    """Σ component unit cost x qty per sold unit; ``None`` when any component has no cost."""
    total = ZERO
    for component in components:
        unit = unit_costs.get(component.sku)
        if unit is None:
            return None
        total += unit * component.qty
    return total


def pack_cogs(unit_cost: Decimal | None, pack_count: int) -> Decimal | None:
    """Cost of one sold unit that holds ``pack_count`` single items."""
    return None if unit_cost is None else unit_cost * pack_count
