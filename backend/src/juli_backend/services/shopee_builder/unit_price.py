"""P92 B-10: pack-normalised price per unit for competitor listings. Pure.

A listing's title states what is sold ("Hộp 100 găng tay", "Combo 3 hộp", "Nước giặt 2 chai
500ml", "Băng keo 5 cuộn"). ``parse`` reads a quantity in one of five units; ``per_unit_price``
turns the price into a price per comparable unit:

| unit  | per            | read from                                            |
|-------|----------------|------------------------------------------------------|
| hop   | 1 hộp          | "N hộp", "hộp"                                       |
| cai   | 100 cái        | "N cái / chiếc / miếng / viên", "hộp N" (N >= 10)    |
| ml    | 500 ml         | "N ml", "N l / lít" (x1000)                          |
| g     | 100 g          | "N g / gr / gram", "N kg" (x1000)                    |
| cuon  | 1 cuộn         | "N cuộn"                                             |
| item  | 1 sold unit    | nothing readable: the pack count of the listing      |

The pack multiplier is the "combo N" / "set N" of the pack parser the variations use
(``shopee_profit.pack.pack_count_from_name``) or an explicit "N hộp / N chai"; it multiplies a
stated content ("2 chai 500ml" = 1000 ml). Only listings with the SAME unit as the product are
compared. Heuristic by design: a title the parser cannot read falls back to ``item`` and is then
only compared with other ``item`` listings, never guessed into another unit.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import cast

from juli_backend.services.shopee_profit.pack import pack_count_from_name

UNITS: dict[str, dict[str, object]] = {
    "hop": {"label": "hộp", "per": 1, "per_label": "giá / hộp"},
    "cai": {"label": "100 cái", "per": 100, "per_label": "giá / 100 cái"},
    "ml": {"label": "500 ml", "per": 500, "per_label": "giá / 500 ml"},
    "g": {"label": "100 g", "per": 100, "per_label": "giá / 100 g"},
    "cuon": {"label": "cuộn", "per": 1, "per_label": "giá / cuộn"},
    "item": {"label": "sản phẩm", "per": 1, "per_label": "giá / sản phẩm"},
}
MAX_MULTIPLIER = 100

_NUM = r"(\d{1,6}(?:[.,]\d{1,2})?)"
_CONTENT = re.compile(_NUM + r"\s*(ml|lit|l|kg|gram|gr|g|cai|chiec|mieng|vien|cuon)(?![a-z0-9])")
_BOXES = re.compile(r"(?<!\w)(\d{1,3})\s*(?:hop|chai|tui|goi|lo|tuyp|tube)(?![a-z])")
_BOX_WORD = re.compile(r"(?<![a-z])hop(?![a-z])")
_BOX_THEN_COUNT = re.compile(r"(?<![a-z])hop\s*(\d{2,4})(?!\d|\s*(?:ml|g|kg|l)\b)")
_MULTI = re.compile(r"(?<![a-z0-9])(?:combo|set)\s*(\d{1,3})(?!\d)")
_STOP = frozenset(
    {
        "cho", "va", "voi", "cua", "cac", "mot", "la", "co", "the", "loai", "bo", "set", "combo",
        "hop", "cai", "chiec", "cuon", "chai", "goi", "tui", "gia", "re", "chinh", "hang",
        "freeship", "sale", "ml", "kg", "gr", "gram", "mieng", "vien", "lit",
    }
)  # fmt: skip
_WORD = re.compile(r"[a-z]{2,}")


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@dataclass(frozen=True)
class Quantity:
    unit: str
    qty: float
    #: how it was read: ``content`` (a stated amount), ``boxes``, ``rolls``, ``combo`` or ``none``
    source: str

    @property
    def label(self) -> str:
        return str(UNITS[self.unit]["label"])


def _amount(text: str) -> float:
    return float(text.replace(",", "."))


_UNIT_OF = {
    "ml": ("ml", 1.0),
    "l": ("ml", 1000.0),
    "lit": ("ml", 1000.0),
    "g": ("g", 1.0),
    "gr": ("g", 1.0),
    "gram": ("g", 1.0),
    "kg": ("g", 1000.0),
    "cai": ("cai", 1.0),
    "chiec": ("cai", 1.0),
    "mieng": ("cai", 1.0),
    "vien": ("cai", 1.0),
    "cuon": ("cuon", 1.0),
}


def parse(text: str, *, multiplier: bool = True) -> Quantity:
    """The quantity a title states. ``multiplier=False`` leaves the "combo N" / box count out
    (the product's own title: its variation carries the pack count)."""
    folded = fold(text)
    combo = pack_count_from_name(text) if multiplier else None
    boxes_match = _BOXES.search(folded) if multiplier else None
    boxes = int(boxes_match.group(1)) if boxes_match else None
    mult = min(boxes or combo or 1, MAX_MULTIPLIER)
    content = _CONTENT.search(folded)
    if content:
        unit, scale = _UNIT_OF[content.group(2)]
        value = _amount(content.group(1)) * scale
        # "N cuộn" is the multiplier itself, not content per pack
        if unit == "cuon":
            return Quantity("cuon", value, "rolls")
        if value > 0:
            return Quantity(unit, value * mult, "content")
    per_box = _BOX_THEN_COUNT.search(folded)
    if per_box and int(per_box.group(1)) >= 10:
        return Quantity("cai", float(per_box.group(1)) * mult, "content")
    if _BOX_WORD.search(folded) or boxes:
        return Quantity("hop", float(mult), "boxes")
    return Quantity("item", float(combo or 1) if multiplier else 1.0, "combo" if combo else "none")


def per_unit_price(price: float, quantity: Quantity) -> float | None:
    """``price`` for the comparable unit of ``quantity`` (per hộp / 100 cái / 500 ml / ...)."""
    if price <= 0 or quantity.qty <= 0:
        return None
    return price / quantity.qty * float(cast("float", UNITS[quantity.unit]["per"]))


def tokens(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(fold(text)) if w not in _STOP)


def similarity(a: str, b: str) -> float:
    """Dice coefficient of the content words of two titles (0..1)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return 2 * len(ta & tb) / (len(ta) + len(tb))


__all__ = ["UNITS", "Quantity", "parse", "per_unit_price", "similarity", "tokens"]
