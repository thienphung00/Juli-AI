"""F2: the days a product could not sell (out of stock or unlisted). Pure, platform-free.

Imports only the standard library, so a TikTok caller can pass its own stock reads later. The
caller turns each stored read into a :class:`StockRead` (the local day is its job).

* **Out of stock** -- every read of the product that day shows a total sellable of 0. A read is
  one ``read_at``: the variation rows (``model_id`` set) are summed; an item with only the item row
  (``model_id`` empty) uses that row. A read whose sellable is unknown is ignored; a day with no
  usable read is not out of stock.
* **Unlisted** -- any read that day with ``listing_status == "unlisted"``.
* A day with no read is available (no carry-forward).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

UNLISTED = "unlisted"


@dataclass(frozen=True)
class StockRead:
    """One stored stock read of a variation (``model_id`` empty = the item row)."""

    item_id: str
    model_id: str
    day: date
    read_at: datetime
    sellable: int | None
    listing_status: str | None


def unavailable_by_item(reads: Iterable[StockRead]) -> dict[str, frozenset[date]]:
    """``{item_id: days it was out of stock or unlisted}``; items never unavailable are absent."""
    # (item, day, read_at) -> [variation sellable values], [item-row sellable values]
    totals: dict[tuple[str, date, datetime], tuple[list[int], list[int]]] = {}
    unlisted: dict[str, set[date]] = {}
    for r in reads:
        if r.listing_status == UNLISTED:
            unlisted.setdefault(r.item_id, set()).add(r.day)
        if r.sellable is None:
            continue
        models, item_row = totals.setdefault((r.item_id, r.day, r.read_at), ([], []))
        (models if r.model_id else item_row).append(r.sellable)
    by_day: dict[tuple[str, date], list[int]] = {}
    for (item, day, _at), (models, item_row) in totals.items():
        by_day.setdefault((item, day), []).append(sum(models) if models else sum(item_row))
    out: dict[str, set[date]] = {k: set(v) for k, v in unlisted.items()}
    for (item, day), sums in by_day.items():
        if all(s == 0 for s in sums):
            out.setdefault(item, set()).add(day)
    return {k: frozenset(v) for k, v in out.items() if v}


def scope_unavailable(
    unavailable: Mapping[str, frozenset[date]], item_ids: Sequence[str]
) -> frozenset[date]:
    """Days to leave out of a product scope: any product in it unavailable. Shop scope: none."""
    days: set[date] = set()
    for item in item_ids:
        days |= unavailable.get(item, frozenset())
    return frozenset(days)


__all__ = ["UNLISTED", "StockRead", "scope_unavailable", "unavailable_by_item"]
