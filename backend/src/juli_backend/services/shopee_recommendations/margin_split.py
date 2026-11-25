"""The with / without-discount split of a card's margin (L1 / A9, owner #65 / #66 / #74).

A product-level layer shows its Biên đóng góp (before ads and AFF) for the purchases WITH a shop
discount and WITHOUT one, so the discount's effect is visible. Both come from the stored facts
through :func:`juli_backend.services.metrics.query.query` (``group_by="discounted"``): one registry
metric, ``margin_contribution``, per cell. Purchases whose discount status is not known
(``unknown``) are never folded into either side: they show only as a count, and only when it is
not zero. A side with no row is ``None`` ("—"), never 0.

Shape::

    {"with": {"margin_pct", "gmv", "orders"} | None,
     "without": {...} | None,
     "unknown": {"orders", "gmv"} | None}      # only when non-zero
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.metrics import query as metrics_query
from juli_backend.services.metrics.query import Scope

WITH, WITHOUT, UNKNOWN = "with", "without", "unknown"
MARGIN_METRIC = "margin_contribution"


def _f(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def _side(row: dict[str, Any] | None, orders_known: bool) -> dict[str, Any] | None:
    if row is None:
        return None
    margin = row.get(MARGIN_METRIC)
    return {
        "margin_pct": None if margin is None else round(float(margin), 1),
        "gmv": _f(row.get("gmv")),
        "orders": _f(row.get("orders")) if orders_known else None,
    }


async def margin_split(
    session: AsyncSession | None,
    shop_id: uuid.UUID,
    items: Sequence[str],
    window: tuple[date, date],
    *,
    source: Any = None,
) -> dict[str, Any]:
    """The split for ``items`` (one product, several, or ``()`` = the whole shop)."""
    ids = [str(i) for i in items if i]
    scope = Scope.products(ids) if ids else Scope.shop()
    # đơn is counted once per order at its own grain: a sum over several products is refused, so
    # a multi-product scope shows the margin and GMV of each side and no order count
    orders_known = len(ids) <= 1
    metrics = [MARGIN_METRIC, "gmv", *(["orders"] if orders_known else [])]
    res = await metrics_query.query(
        session, shop_id, metrics, scope=scope, window=window, group_by="discounted", source=source
    )
    by = {str(r["discounted"]): r for r in res.rows}
    unknown = by.get(UNKNOWN)
    unknown_out = None
    if unknown is not None:
        orders = unknown.get("orders") if orders_known else None
        gmv = unknown.get("gmv")
        if (orders or 0) != 0 or (gmv or 0) != 0:
            unknown_out = {"orders": _f(orders), "gmv": _f(gmv)}
    return {
        WITH: _side(by.get(WITH), orders_known),
        WITHOUT: _side(by.get(WITHOUT), orders_known),
        "unknown": unknown_out,
    }


class SplitCache:
    """One query per scope inside a run (cards of one product share it)."""

    def __init__(self, session: AsyncSession | None, shop_id: uuid.UUID, window: tuple[date, date]):
        self._s, self._shop, self._w = session, shop_id, window
        self._done: dict[tuple[str, ...], dict[str, Any]] = {}

    async def of(self, items: Sequence[str]) -> dict[str, Any]:
        key = tuple(sorted(str(i) for i in items if i))
        if key not in self._done:
            self._done[key] = await margin_split(self._s, self._shop, key, self._w)
        return self._done[key]
