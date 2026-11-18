"""The per-variation stock history, written on every ``item_snapshot`` ingest (Part S).

``record(session, rows, provenance)`` is called from ``ingest.gateway._write`` (one line), inside
the shop's tenant scope, after the snapshot writer. One ``stock_history`` row per model row
(the wire's ``model_id`` set, stored as ``variation_id``); an item row is stored too
(``variation_id`` ""), it is the SKU of a listing without variations. A model row carries no
listing flag of its own, so it takes its item row's (``unlisted`` -> ``unlisted``, else
``active``). The same read posted twice is a no-op (unique on shop, item, variation,
``read_at``). Nothing commits here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.stock_alert import ShopeeStockHistory
from juli_backend.services.ingest.schemas import ShopeeItemSnapshotRow

STATUS_ACTIVE = "active"
STATUS_UNLISTED = "unlisted"
CHUNK = 400


def _status(unlisted: bool | None) -> str | None:
    if unlisted is None:
        return None
    return STATUS_UNLISTED if unlisted else STATUS_ACTIVE


def history_values(
    rows: Sequence[ShopeeItemSnapshotRow], provenance: dict[str, Any]
) -> list[dict[str, Any]]:
    """The ``stock_history`` rows of one post (pure). ``read_at`` is the post's capture time,
    naive UTC (``stock_history.read_at`` reads a naive value as UTC)."""
    item_flag = {r.item_id: r.unlisted for r in rows if not r.model_id}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if r.sellable_stock is None and r.total_available_stock is None:
            continue
        unlisted = r.unlisted if r.unlisted is not None else item_flag.get(r.item_id)
        out[(r.item_id, r.model_id)] = {
            "id": uuid.uuid4(),
            "shop_id": provenance["shop_id"],
            "item_id": r.item_id,
            "variation_id": r.model_id,
            "read_at": provenance["captured_at"],
            "sellable": None if r.sellable_stock is None else int(r.sellable_stock),
            "available": None if r.total_available_stock is None else int(r.total_available_stock),
            "listing_status": _status(unlisted),
        }
    return list(out.values())


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


async def record(
    session: AsyncSession, rows: Sequence[ShopeeItemSnapshotRow], provenance: dict[str, Any]
) -> int:
    """Store the stock of every variation in the post; returns the rows offered."""
    values = history_values(rows, provenance)
    if not values:
        return 0
    insert = _insert(session)
    for start in range(0, len(values), CHUNK):
        part = values[start : start + CHUNK]
        await session.execute(insert(ShopeeStockHistory).values(part).on_conflict_do_nothing())
    return len(values)


__all__ = ["history_values", "record"]
