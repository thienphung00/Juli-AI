"""C9 (E150): a collapsed combo post never replaces the combo's own stored lines.

``get_one_order`` answers a combo as ONE line with the whole combo price and no SKU; the order
page then splits it into the combo's products (0.3.36). Every later read of the same order posts
the collapsed line again, and the line upsert (key = order + line number) replaced line 0 only:
the combo total stood beside the other split lines. A post whose combo lines say less than the
stored ones (a line with no SKU, or fewer combo lines) keeps the stored content: it only moves the
order's status and times, on every line of the order.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_EXTENSION, IngestRawPayload, effective_rank
from juli_backend.models.shopee_profit import ShopeeOrderLine, as_vn
from juli_backend.services.ingest.schemas import ShopeeOrderLineRow

logger = logging.getLogger(__name__)

BUNDLE = "bundle"
PLACEHOLDER = "sku:"
UNRESOLVED_SKU = "unresolved_item"
#: A late upload of an older read never moves an order back to one of these.
EARLY = frozenset(("pending", "confirmed", "on_hold", "in_transit"))


def _named(row: ShopeeOrderLineRow) -> bool:
    return any(sku and sku != UNRESOLVED_SKU for sku in (row.sku, row.variation_sku))


def says_less(posted: list[ShopeeOrderLineRow], stored: list[Any]) -> bool:
    """The post's combo lines say less than the stored combo lines of the same order."""
    combos = [row for row in posted if row.promo_kind == BUNDLE]
    if not combos:
        return False
    held = [
        ln
        for ln in stored
        if ln.promo_kind == BUNDLE
        and not ln.item_id.startswith(PLACEHOLDER)
        and (ln.sku or ln.variation_sku)
    ]
    if not held:
        return False
    return len(combos) < len(held) or not all(_named(row) for row in combos)


async def keep_named_combos(
    session: AsyncSession, rows: list[ShopeeOrderLineRow], provenance: dict[str, Any]
) -> list[ShopeeOrderLineRow]:
    """The rows still to upsert: the orders whose post says less are taken out (their stored
    lines get the post's status and times)."""
    refs = {row.order_ref for row in rows if row.promo_kind == BUNDLE}
    if provenance["source"] != SOURCE_EXTENSION or not refs:
        return rows
    shop_id, platform = provenance["shop_id"], provenance["platform"]
    found = await session.execute(
        select(ShopeeOrderLine)
        .where(
            ShopeeOrderLine.shop_id == shop_id,
            ShopeeOrderLine.platform == platform,
            ShopeeOrderLine.order_ref.in_(sorted(refs)),
        )
        .execution_options(populate_existing=True)
    )
    stored: dict[str, list[ShopeeOrderLine]] = defaultdict(list)
    for line in found.scalars():
        stored[line.order_ref].append(line)
    posted: dict[str, list[ShopeeOrderLineRow]] = defaultdict(list)
    for row in rows:
        posted[row.order_ref].append(row)
    kept = {
        ref
        for ref in refs
        if says_less(posted[ref], stored[ref])
        # a higher-ranked source keeps its own rule (the line upsert only fills its NULLs)
        and all(
            effective_rank(ln.source, ln.source_rank) <= int(provenance["source_rank"])
            for ln in stored[ref]
        )
    }
    if not kept:
        return rows
    captured = await _captures(session, kept, stored, provenance)
    for ref in kept:
        await _move_status(session, posted[ref], stored[ref], captured, provenance)
    logger.info(
        "order_line_combo_parent_kept", extra={"shop_id": str(shop_id), "orders": len(kept)}
    )
    return [row for row in rows if row.order_ref not in kept]


async def _captures(
    session: AsyncSession,
    refs: set[str],
    stored: dict[str, list[ShopeeOrderLine]],
    provenance: dict[str, Any],
) -> dict[Any, Any]:
    ids = {ln.raw_payload_id for ref in refs for ln in stored[ref]} | {provenance["raw_payload_id"]}
    ids.discard(None)
    found = await session.execute(
        select(IngestRawPayload.id, IngestRawPayload.captured_at).where(
            IngestRawPayload.id.in_(ids)
        )
    )
    return {raw_id: at for raw_id, at in found}


async def _move_status(
    session: AsyncSession,
    posted: list[ShopeeOrderLineRow],
    stored: list[ShopeeOrderLine],
    captured: dict[Any, Any],
    provenance: dict[str, Any],
) -> None:
    from juli_backend.services.ingest.writers import canonical_status

    first = posted[0]
    status = canonical_status(first.status, paid=first.paid_at is not None)
    at = captured.get(provenance["raw_payload_id"])
    for line in stored:
        before = captured.get(line.raw_payload_id)
        if at is not None and before is not None and before > at:
            continue  # an older read uploaded late
        values: dict[str, Any] = {"updated_at": provenance["updated_at"]}
        if status not in EARLY or line.status in EARLY:
            values["status"] = status
        if first.completed_at is not None:
            values["completed_at"] = as_vn(first.completed_at)
        if first.paid_at is not None:
            values["paid_at"] = as_vn(first.paid_at)
        await session.execute(
            update(ShopeeOrderLine)
            .where(ShopeeOrderLine.id == line.id, ShopeeOrderLine.shop_id == provenance["shop_id"])
            .values(**values)
        )
