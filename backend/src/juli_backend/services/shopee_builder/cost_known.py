"""U1 (owner 2026-11-17): ONE answer to "does this listing have a real giá vốn?", read by the
product picker ("có giá vốn" / "thiếu giá vốn") and by the result ("Chưa có giá vốn trong Thông số
shop"), so the two never disagree. The profit engine decides: a listing is costed when every SKU
on its order lines was costed from a real rule, not from the assumed fallback."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class _Costs(Protocol):
    def cogs_is_real(self, key: str) -> bool: ...


def skus_costed(costs: _Costs, skus: Iterable[str]) -> bool | None:
    """True / False for a listing with order lines; None when it has none (the seller's rules
    for its variations then decide)."""
    keys = list(skus)
    if not keys:
        return None
    return all(costs.cogs_is_real(s) for s in keys)
