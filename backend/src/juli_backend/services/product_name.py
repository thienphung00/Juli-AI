"""Short product names for card headings (the demo's copy rule: no full TikTok titles).

TikTok titles are long, keyword-stuffed and often end in a parenthetical. Headings and
queue rows show :func:`short_product_name`; the full title stays available as hover text.
The frontend has the same helper (``apps/demo/src/lib/quyet-dinh/product-name.ts``); keep
the two byte-for-byte in behaviour.
"""

from __future__ import annotations

import re

#: P71: a product row carried "Unknown" before its name was synced (the ETL product
#: transform's default for a status-only webhook). Never a seller-facing name.
from juli_backend.repositories.commerce import is_placeholder_product_name

MAX_NAME_CHARS = 40
#: A clause break is only used when the part before it is at least this long.
MIN_CLAUSE_CHARS = 12

_PARENTHETICAL = re.compile(r"\s*[(\[（][^)\]）]*[)\]）]")
_CLAUSE_BREAK = re.compile(r"\s*[,;|–—]\s+|\s+-\s+")
_TRAILING_JUNK = re.compile(r"[\s,;:|\-–—/·]+$")


def short_product_name(name: str | None, max_chars: int = MAX_NAME_CHARS) -> str:
    """``name`` without parentheticals, cut at ~``max_chars`` on a word boundary + "…"."""
    text = " ".join(_PARENTHETICAL.sub("", name or "").split())
    if not text:
        return ""
    cut = False
    clause = _CLAUSE_BREAK.search(text)
    if clause is not None and clause.start() >= MIN_CLAUSE_CHARS:
        text = text[: clause.start()]
        cut = True
    if len(text) > max_chars:
        head = text[: max_chars + 1]
        space = head.rfind(" ")
        text = head[:space] if space >= MIN_CLAUSE_CHARS else text[:max_chars]
        cut = True
    text = _TRAILING_JUNK.sub("", text)
    return f"{text}…" if cut else text


#: ``catalog_create`` stamps every product Juli creates with ``JULI-<8 hex>``; it is an internal id.
INTERNAL_SKU_PREFIX = "JULI-"


def is_seller_visible_sku(sku: str | None) -> bool:
    """A seller SKU worth showing: set, and not one of Juli's own generated ids."""
    value = (sku or "").strip()
    return bool(value) and not value.upper().startswith(INTERNAL_SKU_PREFIX)


def known_product_name(*candidates: str | None) -> str | None:
    """The first candidate that is a real product name, else ``None`` (P71)."""
    for candidate in candidates:
        if not is_placeholder_product_name(candidate):
            return (candidate or "").strip()
    return None


__all__ = [
    "INTERNAL_SKU_PREFIX",
    "MAX_NAME_CHARS",
    "is_placeholder_product_name",
    "is_seller_visible_sku",
    "known_product_name",
    "short_product_name",
]
