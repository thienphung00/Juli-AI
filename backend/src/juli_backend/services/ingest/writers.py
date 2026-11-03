"""Writers of the P90 step 2 datasets: one function per table (migration 113 / 112).

Called by ``gateway._write`` inside the shop's tenant scope; nothing here commits.

- ``order_lines`` -> ``shopee_order_lines``: upsert on (shop, platform, order_ref, line_no). A
  later export of the same order moves its status and fills fees; a NULL fee or time never
  erases a value already stored. The export names a product by SKU only, so ``item_id`` is
  resolved from ``platform_items.seller_sku`` when the catalogue knows it, else it is
  ``sku:<sku>``.
- ``affiliate_order_lines`` -> the SAME table, but only to MARK lines the order export already
  wrote (``affiliate``, ``commission`` from ``cost``, ``traffic_source``). It never creates a
  line: the order export owns the line, and a second writer on one key would overwrite it.
  Load the order export first; unmatched rows are counted and left for a re-load.
- ``ads_change_log`` and ``shop_health_daily``: append-only, ``ON CONFLICT DO NOTHING``.
- ``item_snapshot`` -> ``platform_item_snapshots``: a row is inserted only when a tracked field
  changed since the item's latest snapshot (the 112 rule lives here; SQL cannot express it).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import ITEM_LEVEL_VARIATION, PlatformItem
from juli_backend.models.shopee_profit import (
    AdsChangeLog,
    PlatformItemSnapshot,
    ShopeeOrderLine,
    ShopHealthDaily,
)
from juli_backend.services.ingest.schemas import (
    IngestBody,
    ShopeeAdsChangeLogRow,
    ShopeeAffiliateOrderLineRow,
    ShopeeItemSnapshotRow,
    ShopeeOrderLineRow,
    ShopeeShopHealthDailyRow,
)

CHUNK = 400
#: ``item_id`` of an order line whose SKU the catalogue does not know yet.
UNRESOLVED_PREFIX = "sku:"
MAX_ITEM_ID = 64


@dataclass(frozen=True)
class AffiliateMatch:
    matched: int
    unmatched: int
    invalid: int


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def _chunks(values: list[Any]) -> list[list[Any]]:
    return [values[start : start + CHUNK] for start in range(0, len(values), CHUNK)]


# -- order lines -------------------------------------------------------------------------


async def _resolve_skus(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, skus: set[str]
) -> dict[str, tuple[str, str]]:
    """``seller_sku`` -> (item_id, variation_id); the first item / variation wins on a twin."""
    found: dict[str, tuple[str, str]] = {}
    for part in _chunks(sorted(skus)):
        rows = await session.execute(
            select(PlatformItem.seller_sku, PlatformItem.item_id, PlatformItem.variation_id)
            .where(
                PlatformItem.shop_id == shop_id,
                PlatformItem.platform == platform,
                PlatformItem.seller_sku.in_(part),
            )
            .order_by(PlatformItem.item_id, PlatformItem.variation_id)
        )
        for sku, item_id, variation_id in rows:
            found.setdefault(sku, (item_id, variation_id))
    return found


def _line_item(row: ShopeeOrderLineRow, known: dict[str, tuple[str, str]]) -> tuple[str, str]:
    for sku in (row.variation_sku, row.sku):
        if sku and sku in known:
            return known[sku]
    label = row.variation_sku or row.sku or "unknown"
    return f"{UNRESOLVED_PREFIX}{label}"[:MAX_ITEM_ID], ITEM_LEVEL_VARIATION


async def write_order_lines(
    session: AsyncSession,
    rows: list[ShopeeOrderLineRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> None:
    if not rows:
        return
    shop_id, platform = provenance["shop_id"], provenance["platform"]
    skus = {sku for row in rows for sku in (row.sku, row.variation_sku) if sku}
    known = await _resolve_skus(session, shop_id, platform, skus)
    values = []
    for row in rows:
        item_id, variation_id = _line_item(row, known)
        values.append(
            {
                "id": uuid.uuid4(),
                "shop_id": shop_id,
                "platform": platform,
                "order_ref": row.order_ref,
                "line_no": row.line_no,
                "ordered_at": _naive(row.ordered_at),
                "status": row.status,
                "item_id": item_id,
                "variation_id": variation_id,
                "sku": row.sku,
                "variation_sku": row.variation_sku,
                "qty": int(row.qty),
                "returned_qty": int(row.returned_qty),
                "original_price": row.original_price,
                "deal_price": row.deal_price,
                "seller_subsidy": row.seller_subsidy,
                "shopee_subsidy": row.shopee_subsidy,
                "shop_voucher_share": row.shop_voucher_share,
                "platform_voucher_share": row.platform_voucher_share,
                "bundle_discount": row.bundle_discount,
                "promo_kind": row.promo_kind,
                "buyer_shipping_fee": row.buyer_shipping_fee,
                "bank_promo": row.bank_promo,
                "fee_fixed": row.fee_fixed,
                "fee_service": row.fee_service,
                "fee_payment": row.fee_payment,
                "completed_at": _naive(row.completed_at),
                "paid_at": _naive(row.paid_at),
                "source": provenance["source"],
                "source_version": provenance["source_version"],
                "raw_payload_id": provenance["raw_payload_id"],
                "updated_at": provenance["updated_at"],
            }
        )
    insert = _insert(session)
    keep = ("fee_fixed", "fee_service", "fee_payment", "completed_at", "paid_at")
    for part in _chunks(values):
        stmt = insert(ShopeeOrderLine).values(part)
        table = ShopeeOrderLine.__table__
        updated: dict[str, Any] = {
            column: stmt.excluded[column]
            for column in part[0]
            if column not in ("id", "shop_id", "platform", "order_ref", "line_no")
            and column not in keep
        }
        # A NULL (not filled yet) never erases a fee or time already stored.
        updated.update(
            {column: func.coalesce(stmt.excluded[column], table.c[column]) for column in keep}
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["shop_id", "platform", "order_ref", "line_no"], set_=updated
            )
        )


# -- affiliate order lines ---------------------------------------------------------------


async def write_affiliate_lines(
    session: AsyncSession,
    rows: list[ShopeeAffiliateOrderLineRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> AffiliateMatch:
    shop_id, platform = provenance["shop_id"], provenance["platform"]
    refs = sorted({row.order_ref for row in rows})
    lines: dict[str, list[tuple[uuid.UUID, str, str]]] = defaultdict(list)
    for part in _chunks(refs):
        found = await session.execute(
            select(
                ShopeeOrderLine.order_ref,
                ShopeeOrderLine.id,
                ShopeeOrderLine.item_id,
                ShopeeOrderLine.variation_id,
            ).where(
                ShopeeOrderLine.shop_id == shop_id,
                ShopeeOrderLine.platform == platform,
                ShopeeOrderLine.order_ref.in_(part),
            )
        )
        for ref, line_id, item_id, variation_id in found:
            lines[ref].append((line_id, item_id, variation_id))
    commission: dict[uuid.UUID, Decimal | None] = {}
    matched = unmatched = invalid = 0
    for row in rows:
        if row.valid is False:
            invalid += 1
            continue
        candidates = lines.get(row.order_ref, [])
        hits = [
            line_id
            for line_id, item_id, variation_id in candidates
            if item_id == row.item_id and (not row.model_id or variation_id in ("", row.model_id))
        ]
        if not hits and len(candidates) == 1:
            hits = [candidates[0][0]]
        if not hits:
            unmatched += 1
            continue
        matched += 1
        target = hits[0]
        if row.cost is not None:
            commission[target] = (commission.get(target) or Decimal(0)) + row.cost
        else:
            commission.setdefault(target, None)
    for line_id, total in commission.items():
        values: dict[str, Any] = {
            "affiliate": True,
            "traffic_source": "affiliate",
            "updated_at": provenance["updated_at"],
        }
        if total is not None:
            values["commission"] = total
        await session.execute(
            update(ShopeeOrderLine)
            .where(ShopeeOrderLine.id == line_id, ShopeeOrderLine.shop_id == shop_id)
            .values(**values)
        )
    return AffiliateMatch(matched, unmatched, invalid)


# -- ads change log ----------------------------------------------------------------------


async def write_ads_log(
    session: AsyncSession,
    rows: list[ShopeeAdsChangeLogRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> None:
    values = [
        {
            "id": uuid.uuid4(),
            "shop_id": provenance["shop_id"],
            "platform": provenance["platform"],
            "campaign_id": row.campaign_id,
            "item_id": row.item_id or "",
            "occurred_at": _naive(row.occurred_at),
            "actor_kind": row.actor_kind,
            "actor": row.actor,
            "surface": row.surface,
            "event_type": row.event_type,
            "detail": row.detail,
            "budget_from": row.budget_from,
            "budget_to": row.budget_to,
            "products_from": int(row.products_from) if row.products_from is not None else None,
            "products_to": int(row.products_to) if row.products_to is not None else None,
            "ordinal": row.ordinal,
            "source": provenance["source"],
            "source_version": provenance["source_version"],
            "raw_payload_id": provenance["raw_payload_id"],
        }
        for row in rows
    ]
    insert = _insert(session)
    for part in _chunks(values):
        await session.execute(insert(AdsChangeLog).values(part).on_conflict_do_nothing())


# -- shop health -------------------------------------------------------------------------


async def write_shop_health(
    session: AsyncSession,
    rows: list[ShopeeShopHealthDailyRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> None:
    values = [
        {
            "id": uuid.uuid4(),
            "shop_id": provenance["shop_id"],
            "platform": provenance["platform"],
            "day": row.date,
            "metric_id": row.metric_id or "",
            "captured_at": provenance["captured_at"],
            "label": row.label,
            "display_value": row.display_value,
            "value": row.value,
            "target_display": row.target_display,
            "target": row.target,
            "compare_result": None if row.compare_result is None else str(row.compare_result),
            "passed": row.passed,
            "metric_tag": None if row.metric_tag is None else str(row.metric_tag),
            "failed_metric_count": (
                int(row.failed_metric_count) if row.failed_metric_count is not None else None
            ),
            "penalty_point": int(row.penalty_point) if row.penalty_point is not None else None,
            "performance_rating": (
                None if row.performance_rating is None else str(row.performance_rating)
            ),
            "source": provenance["source"],
            "source_rank": provenance["source_rank"],
            "source_version": provenance["source_version"],
            "raw_payload_id": provenance["raw_payload_id"],
        }
        for row in rows
    ]
    insert = _insert(session)
    for part in _chunks(values):
        await session.execute(insert(ShopHealthDaily).values(part).on_conflict_do_nothing())


# -- item snapshots ----------------------------------------------------------------------

#: The fields whose change makes a new snapshot.
TRACKED = (
    "list_price",
    "current_price",
    "promo_label",
    "stock",
    "sold_total",
    "likes",
    "status",
    "created_on",
    "image_urls",
)


def snapshot_fields(row: ShopeeItemSnapshotRow) -> dict[str, Any]:
    """``ShopeeItemSnapshotRow`` -> the tracked ``platform_item_snapshots`` columns.

    Item row: list price = the top of the price range, current = the lowest selling price.
    Model row: list = ``origin_price``, current = ``promotion_price`` else ``origin_price``."""
    if row.model_id:
        list_price = row.origin_price if row.origin_price is not None else row.price_max
        current = row.promotion_price if row.promotion_price is not None else row.origin_price
    else:
        list_price = row.price_max if row.price_max is not None else row.price_min
        current = row.selling_price_min if row.selling_price_min is not None else row.price_min
    label = None
    if row.has_discount and row.discount_percent is not None:
        label = f"-{row.discount_percent.normalize():f}%"
    created = _naive(row.create_time)
    return {
        "list_price": list_price,
        "current_price": current,
        "promo_label": label,
        "stock": None if row.total_available_stock is None else int(row.total_available_stock),
        "sold_total": None if row.sold_count is None else int(row.sold_count),
        "likes": None if row.liked_count is None else int(row.liked_count),
        "status": "unlisted" if row.unlisted else None,
        "created_on": created.date() if created is not None else None,
        "image_urls": [row.image] if row.image else [],
    }


def _same(old: Any, new: Any) -> bool:
    if isinstance(old, Decimal) or isinstance(new, Decimal):
        return old is not None and new is not None and Decimal(old) == Decimal(new)
    return old == new


async def write_item_snapshots(
    session: AsyncSession,
    rows: list[ShopeeItemSnapshotRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> int:
    """Insert a snapshot per item / model that changed since its latest one; returns the
    number inserted."""
    shop_id, platform = provenance["shop_id"], provenance["platform"]
    captured = provenance["captured_at"]
    latest: dict[tuple[str, str], PlatformItemSnapshot] = {}
    items = sorted({row.item_id for row in rows})
    for part in _chunks(items):
        found = await session.execute(
            select(PlatformItemSnapshot)
            .where(
                PlatformItemSnapshot.shop_id == shop_id,
                PlatformItemSnapshot.platform == platform,
                PlatformItemSnapshot.item_id.in_(part),
            )
            .order_by(PlatformItemSnapshot.captured_at.desc())
        )
        for snapshot in found.scalars():
            latest.setdefault((snapshot.item_id, snapshot.variation_id), snapshot)
    values = []
    for row in rows:
        fields = snapshot_fields(row)
        previous = latest.get((row.item_id, row.model_id))
        if previous is not None:
            if captured <= previous.captured_at:
                continue
            if all(_same(getattr(previous, name), fields[name]) for name in TRACKED):
                continue
        values.append(
            {
                "id": uuid.uuid4(),
                "shop_id": shop_id,
                "platform": platform,
                "item_id": row.item_id,
                "variation_id": row.model_id or ITEM_LEVEL_VARIATION,
                "captured_at": captured,
                "image_hashes": [],
                "category_path": [],
                **fields,
                "source": provenance["source"],
                "source_rank": provenance["source_rank"],
                "raw_payload_id": provenance["raw_payload_id"],
            }
        )
    insert = _insert(session)
    for part in _chunks(values):
        await session.execute(insert(PlatformItemSnapshot).values(part).on_conflict_do_nothing())
    return len(values)
