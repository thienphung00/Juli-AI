"""How much of a product's keyword weight a title / first line holds (P100 UI fix).

The weight of a keyword is its monthly search volume (``market_keyword_metrics.volume``, the same
numbers as the Tiêu đề keyword table). Coverage = the weight share of the keywords a text
contains, whole words, case and diacritics folded. Pure functions: no database below here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

from juli_backend.services.shopee_analytics.fee_table import fold

_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
#: kinds whose lift follows the keyword coverage / that wait for the banner checks
KEYWORD_KINDS = ("title", "description_first_line")
UNMEASURED_KINDS = ("cover_image", "price_display")
#: the gap a text can still close is never smaller than this (a title that already holds every
#: keyword has nothing left to gain)
EPSILON = Decimal("0.0001")


def _padded(text: str) -> str:
    return " " + _NON_WORD.sub(" ", fold(text)).strip() + " "


def contains(text: str, keyword: str) -> bool:
    key = _NON_WORD.sub(" ", fold(keyword)).strip()
    return bool(key) and f" {key} " in _padded(text)


def coverage(text: str, weights: Mapping[str, float]) -> Decimal:
    """Share (0..1) of the keywords' total weight that ``text`` contains."""
    total = sum(w for w in weights.values() if w > 0)
    if total <= 0:
        return Decimal(0)
    held = sum(w for k, w in weights.items() if w > 0 and contains(text, k))
    return Decimal(str(held)) / Decimal(str(total))


def gain_share(current: str | None, new: str, weights: Mapping[str, float]) -> Decimal:
    """0..1: the share of the keyword weight the current text misses that ``new`` captures. 1 =
    ``new`` holds all of it (the prior's full effect); 0 = nothing gained (or lost)."""
    now = coverage(current, weights) if current else Decimal(0)
    gap = max(Decimal(1) - now, EPSILON)
    share = (coverage(new, weights) - now) / gap
    return min(max(share, Decimal(0)), Decimal(1))


def weights_of_table(table: Mapping[str, object]) -> dict[str, float]:
    """The weights out of a ``keywords.keyword_table`` answer: every row with a volume."""
    out: dict[str, float] = {}
    rows = table.get("keywords")
    for row in rows if isinstance(rows, list) else []:
        volume = row.get("volume") if isinstance(row, dict) else None
        if volume is not None and float(volume) > 0:
            out.setdefault(str(row["keyword"]), float(volume))
    return out


__all__ = [
    "KEYWORD_KINDS",
    "UNMEASURED_KINDS",
    "EPSILON",
    "contains",
    "coverage",
    "gain_share",
    "weights_of_table",
]
