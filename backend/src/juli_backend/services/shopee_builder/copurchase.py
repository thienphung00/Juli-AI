"""P92 B-4 "Gợi ý ghép": the products the shop's buyers already put in one order.

Counts, over the order lines of the window, the orders that held a product ``A`` and, of those,
how many also held ``B`` (``together``). Only the shop's own confirmed order lines, only listing
ids and counts -- no order reference, no buyer. Excluded listings are never suggested.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from juli_backend.services.shopee_profit.order_profit import OrderLine

MIN_TOGETHER = 2
MAX_SUGGESTIONS = 10


def order_sets(lines: Iterable[OrderLine], skip: Mapping[str, Any] | None = None) -> list[set[str]]:
    by_order: dict[str, set[str]] = defaultdict(set)
    for ln in lines:
        if skip and ln.product_id in skip:
            continue
        by_order[ln.order_id].add(ln.product_id)
    return list(by_order.values())


def suggestions(
    sets: list[set[str]],
    anchor: str,
    *,
    names: Mapping[str, str],
    min_together: int = MIN_TOGETHER,
    limit: int = MAX_SUGGESTIONS,
) -> dict[str, Any]:
    """Partners of ``anchor``, most often bought together first."""
    with_anchor = [s for s in sets if anchor in s]
    counts: dict[str, int] = defaultdict(int)
    for s in with_anchor:
        for other in s - {anchor}:
            counts[other] += 1
    bought = {item: sum(1 for s in sets if item in s) for item in counts}
    rows: list[dict[str, Any]] = [
        {
            "item_id": item,
            "name": names.get(item) or item,
            "together": n,
            "orders_with_partner": bought[item],
            "share_of_anchor_orders": round(n / len(with_anchor), 4) if with_anchor else None,
            "share_of_partner_orders": round(n / bought[item], 4) if bought[item] else None,
        }
        for item, n in counts.items()
        if n >= min_together
    ]
    rows.sort(key=lambda r: (-int(r["together"]), str(r["item_id"])))
    return {
        "anchor": {"item_id": anchor, "name": names.get(anchor) or anchor},
        "orders_with_anchor": len(with_anchor),
        "orders_total": len(sets),
        "min_together": min_together,
        "suggestions": rows[:limit],
    }


__all__ = ["MAX_SUGGESTIONS", "MIN_TOGETHER", "order_sets", "suggestions"]
