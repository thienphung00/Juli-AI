"""Snapshot and external-change persistence (D30.1a, D30.4).

Every function takes the caller's session and shop; nothing commits. Under
Postgres the caller holds the shop's scope, so RLS restates the ``shop_id``
filter every query here already has.

- ``latest_snapshots`` -- each product's newest snapshot, one query.
- ``record_read`` -- store a product read when its state changed since the
  latest snapshot and record what changed as ``external_changes`` rows; Juli's
  own writes are recorded with ``juli_write = true``.
- ``record_change`` -- insert one change unless its ``dedup_key`` exists.
- ``matches_juli_write`` -- the tolerance-window match against
  ``run_write_values``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.history import (
    KIND_CONTENT,
    KIND_CREATION,
    KIND_PRICE,
    SOURCE_BASELINE,
    ExternalChange,
    ProductSnapshot,
)
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.product_history.normalize import (
    Change,
    NormalizedProduct,
    PreviousState,
    diff,
    epoch_to_naive_utc,
    local_day,
    sha256_text,
)

#: A Juli write counts for a change TikTok dated up to this long after the write
#: (listing edits can sit in TikTok review for hours) ...
JULI_WRITE_LOOKBACK = timedelta(hours=72)
#: ... or this long before it (clock skew between TikTok and Juli).
JULI_WRITE_LOOKAHEAD = timedelta(hours=1)
#: The fields Juli's agent writes (``run_write_values.field``) per change kind.
_JULI_FIELDS = {"title", "description", "main_images", "price"}


def previous_state(row: ProductSnapshot) -> PreviousState:
    return PreviousState(
        title=row.title,
        description_hash=row.description_hash,
        image_uris=[str(i.get("uri")) for i in row.main_images or [] if isinstance(i, Mapping)],
        attributes_hash=row.attributes_hash,
        skus=list(row.skus or []),
        category_id=row.category_id,
        status=row.status,
        content_hash=row.content_hash,
        state_hash=row.state_hash,
        tiktok_update_time=row.tiktok_update_time,
    )


async def latest_snapshots(
    session: AsyncSession, shop_id: uuid.UUID, product_ids: Sequence[str] | None = None
) -> dict[str, ProductSnapshot]:
    """``{tiktok_product_id: newest snapshot}`` for the shop (or the given products)."""
    newest = select(
        ProductSnapshot.tiktok_product_id.label("pid"),
        func.max(ProductSnapshot.taken_at).label("taken"),
    ).where(ProductSnapshot.shop_id == shop_id)
    if product_ids is not None:
        newest = newest.where(ProductSnapshot.tiktok_product_id.in_(list(product_ids)))
    sub = newest.group_by(ProductSnapshot.tiktok_product_id).subquery()
    rows = (
        await session.execute(
            select(ProductSnapshot)
            .join(
                sub,
                and_(
                    ProductSnapshot.tiktok_product_id == sub.c.pid,
                    ProductSnapshot.taken_at == sub.c.taken,
                ),
            )
            .where(ProductSnapshot.shop_id == shop_id)
            .order_by(ProductSnapshot.created_at)
        )
    ).scalars()
    return {row.tiktok_product_id: row for row in rows}


async def has_any_snapshot(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    found = await session.execute(
        select(ProductSnapshot.id).where(ProductSnapshot.shop_id == shop_id).limit(1)
    )
    return found.first() is not None


async def record_change(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str | None,
    kind: str,
    fields: Sequence[str],
    occurred_at: datetime,
    detected_at: datetime,
    source: str,
    juli_write: bool,
    details: Mapping[str, Any] | None,
    dedup_key: str,
) -> ExternalChange | None:
    """Insert one change; ``None`` when ``dedup_key`` was already recorded (idempotent)."""
    key = dedup_key[:255]
    exists = await session.execute(
        select(ExternalChange.id).where(
            ExternalChange.shop_id == shop_id, ExternalChange.dedup_key == key
        )
    )
    if exists.first() is not None:
        return None
    row = ExternalChange(
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        kind=kind,
        fields=list(fields),
        occurred_at=occurred_at,
        detected_at=detected_at,
        source=source,
        juli_write=juli_write,
        details=dict(details) if details is not None else None,
        dedup_key=key,
    )
    session.add(row)
    await session.flush()
    return row


def _same_price(after: Any, new: NormalizedProduct) -> bool:
    if not isinstance(after, list):
        return False
    current = {row["sku_id"]: row["list_price"] for row in new.skus}
    for item in after:
        if not isinstance(item, Mapping):
            return False
        try:
            wanted = str(Decimal(str(item.get("amount"))).normalize())
        except (InvalidOperation, ValueError):
            return False
        if current.get(str(item.get("sku_id"))) != wanted:
            return False
    return True


def _value_matches(field_name: str, after: Any, new: NormalizedProduct) -> bool:
    """Juli's recorded after-value equals what TikTok now shows (``None``: not comparable)."""
    if after is None:
        return True
    if field_name == "title":
        return str(after).strip() == (new.title or "")
    if field_name == "description":
        return sha256_text(str(after).strip()) == new.description_hash
    if field_name == "main_images":
        uris = [
            str(i.get("uri")) if isinstance(i, Mapping) else str(i)
            for i in (after if isinstance(after, list) else [])
        ]
        return uris == new.image_uris
    if field_name == "price":
        return _same_price(after, new)
    return False


def _write_fields(change: Change) -> set[str]:
    """The ``run_write_values.field`` names a change needs Juli to have written."""
    if change.kind == KIND_PRICE:
        return {"price"}
    if change.kind == KIND_CONTENT:
        return set(change.fields)
    return set()


async def matches_juli_write(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    change: Change,
    new: NormalizedProduct,
    occurred_at: datetime,
) -> bool:
    """True when every field of ``change`` matches a Juli write in the tolerance window.

    A field Juli never writes (attributes, category, status) makes the change
    external. A write matches when it touched the same product and field,
    was recorded within [occurred_at - 72 h, occurred_at + 1 h], and its
    after-value equals what TikTok now shows (when the value is comparable).
    """
    needed = _write_fields(change)
    if not needed or not needed <= _JULI_FIELDS:
        return False
    rows = (
        await session.execute(
            select(RunWriteValue).where(
                RunWriteValue.shop_id == shop_id,
                RunWriteValue.tiktok_product_id == tiktok_product_id,
                RunWriteValue.field.in_(sorted(needed)),
                RunWriteValue.recorded_at >= occurred_at - JULI_WRITE_LOOKBACK,
                RunWriteValue.recorded_at <= occurred_at + JULI_WRITE_LOOKAHEAD,
            )
        )
    ).scalars()
    covered = {row.field for row in rows if _value_matches(row.field, row.after_value, new)}
    return needed <= covered


@dataclass
class ReadOutcome:
    snapshot: ProductSnapshot | None
    changes: list[ExternalChange]


def _snapshot_row(
    shop_id: uuid.UUID, new: NormalizedProduct, *, now: datetime, source: str
) -> ProductSnapshot:
    return ProductSnapshot(
        shop_id=shop_id,
        tiktok_product_id=new.tiktok_product_id,
        snapshot_date=local_day(now),
        taken_at=now,
        content_hash=new.content_hash,
        state_hash=new.state_hash,
        title=new.title[:500] if new.title else new.title,
        description_hash=new.description_hash,
        description=new.description,
        main_images=list(new.main_images),
        attributes_hash=new.attributes_hash,
        skus=list(new.skus),
        category_id=new.category_id,
        status=new.status,
        tiktok_update_time=new.update_time,
        source=source,
    )


async def _same_day_state_exists(
    session: AsyncSession, shop_id: uuid.UUID, new: NormalizedProduct, now: datetime
) -> bool:
    found = await session.execute(
        select(ProductSnapshot.id).where(
            ProductSnapshot.shop_id == shop_id,
            ProductSnapshot.tiktok_product_id == new.tiktok_product_id,
            ProductSnapshot.snapshot_date == local_day(now),
            ProductSnapshot.state_hash == new.state_hash,
        )
    )
    return found.first() is not None


async def record_read(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    new: NormalizedProduct,
    previous: ProductSnapshot | None,
    source: str,
    now: datetime,
    baseline: bool = False,
    hint_fields: Iterable[str] = (),
    hint_kind: str | None = None,
) -> ReadOutcome:
    """Store ``new`` when it differs from ``previous`` and record its changes.

    - same state as ``previous`` (or already stored today) → nothing.
    - no ``previous`` and ``baseline`` → a snapshot, no change (the first full pass).
    - no ``previous`` otherwise → a snapshot and one change: ``creation`` for a
      product created after the baseline, or ``hint_kind`` with the webhook's
      ``hint_fields`` (no before-state to diff against).
    - otherwise → a snapshot and one change per kind ``diff`` reports.
    """
    if previous is not None and previous.state_hash == new.state_hash:
        return ReadOutcome(None, [])
    if await _same_day_state_exists(session, shop_id, new, now):
        return ReadOutcome(None, [])
    snapshot = _snapshot_row(
        shop_id, new, now=now, source=SOURCE_BASELINE if baseline and previous is None else source
    )
    session.add(snapshot)
    await session.flush()

    occurred_at = epoch_to_naive_utc(new.update_time) or now
    if previous is None:
        if baseline:
            return ReadOutcome(snapshot, [])
        kind = hint_kind or KIND_CREATION
        changes = [Change(kind, sorted(set(hint_fields)) or ["product"], {"first_seen": True})]
    else:
        changes = diff(previous_state(previous), new)

    recorded: list[ExternalChange] = []
    for change in changes:
        juli = await matches_juli_write(
            session,
            shop_id=shop_id,
            tiktok_product_id=new.tiktok_product_id,
            change=change,
            new=new,
            occurred_at=occurred_at,
        )
        details = dict(change.details)
        details["snapshot_id"] = str(snapshot.id)
        row = await record_change(
            session,
            shop_id=shop_id,
            tiktok_product_id=new.tiktok_product_id,
            kind=change.kind,
            fields=change.fields,
            occurred_at=occurred_at,
            detected_at=now,
            source=source,
            juli_write=juli,
            details=details,
            dedup_key=f"snap:{snapshot.id}:{change.kind}",
        )
        if row is not None:
            recorded.append(row)
    return ReadOutcome(snapshot, recorded)


__all__ = [
    "JULI_WRITE_LOOKAHEAD",
    "JULI_WRITE_LOOKBACK",
    "ReadOutcome",
    "has_any_snapshot",
    "latest_snapshots",
    "matches_juli_write",
    "previous_state",
    "record_change",
    "record_read",
]
