"""Snapshot and external-change persistence (D30.1a, D30.4).

Every function takes the caller's session and shop; nothing commits. Under
Postgres the caller holds the shop's scope, so RLS restates the ``shop_id``
filter every query here already has.

- ``latest_snapshots`` -- each product's newest snapshot, one query.
- ``record_read`` -- store a product read when its state changed since the
  latest snapshot and record what changed as ``external_changes`` rows; Juli's
  own writes are recorded with ``juli_write = true``.
- ``record_change`` -- insert one change unless its ``dedup_key`` exists.
- ``attribute_fields`` -- per-field ``juli`` / ``seller_revert`` /
  ``seller_change`` against ``run_write_values`` hashes (ADR-107 amendment §8,
  ``attribution.py``); ``matches_juli_write`` is "every field ``juli``".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.history import (
    KIND_CREATION,
    SOURCE_BASELINE,
    ExternalChange,
    ProductSnapshot,
)
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.product_history.attribution import (
    JULI_FIELDS,
    JULI_WRITE_LOOKAHEAD,
    JULI_WRITE_LOOKBACK,
    WriteRecord,
    all_juli,
    attribution_fields,
    label_fields,
    summarize,
    uniform_labels,
)
from juli_backend.services.product_history.normalize import (
    Change,
    NormalizedProduct,
    PreviousState,
    ProductFields,
    diff,
    epoch_to_naive_utc,
    local_day,
)


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
    field_attribution: Mapping[str, str] | None = None,
) -> ExternalChange | None:
    """Insert one change; ``None`` when ``dedup_key`` was already recorded (idempotent).

    ``field_attribution`` is the per-field labels (amendment §8); without it every
    field is ``juli`` or ``seller_change`` by ``juli_write`` (a promotion row,
    §11). A change that is not entirely Juli's also writes its ``seller_change``
    ``card_events`` row (live, never raises).
    """
    key = dedup_key[:255]
    exists = await session.execute(
        select(ExternalChange.id).where(
            ExternalChange.shop_id == shop_id, ExternalChange.dedup_key == key
        )
    )
    if exists.first() is not None:
        return None
    labels = (
        dict(field_attribution)
        if field_attribution
        else uniform_labels(kind, fields, juli_write=juli_write)
    )
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
        attribution=summarize(labels),
        field_attribution=labels,
    )
    session.add(row)
    await session.flush()
    if not all_juli(labels):
        from juli_backend.services.card_events.natural import record_seller_change

        await record_seller_change(session, row)
    return row


def product_fields_of_snapshot(row: ProductSnapshot) -> ProductFields:
    """The per-field hashable state a stored snapshot holds (the backfill's "now")."""
    return ProductFields(
        title=row.title,
        description_hash=row.description_hash,
        image_uris=tuple(
            str(i.get("uri")) for i in row.main_images or [] if isinstance(i, Mapping)
        ),
        list_prices={
            str(sku.get("sku_id")): sku.get("list_price")
            for sku in row.skus or []
            if isinstance(sku, Mapping)
        },
    )


async def juli_writes(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    fields: Iterable[str],
    until: datetime,
) -> list[WriteRecord]:
    """Juli's ``run_write_values`` of one product and the given fields, recorded by ``until``."""
    wanted = sorted(set(fields) & JULI_FIELDS)
    if not wanted:
        return []
    rows = (
        await session.execute(
            select(RunWriteValue)
            .where(
                RunWriteValue.shop_id == shop_id,
                RunWriteValue.tiktok_product_id == tiktok_product_id,
                RunWriteValue.field.in_(wanted),
                RunWriteValue.recorded_at <= until,
            )
            .order_by(RunWriteValue.recorded_at, RunWriteValue.id)
        )
    ).scalars()
    return [WriteRecord.of(row) for row in rows]


async def attribute_fields(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    change: Change,
    new: NormalizedProduct,
    occurred_at: datetime,
    known_at: datetime | None = None,
) -> dict[str, str]:
    """``{field: juli | seller_revert | seller_change}`` for one change (amendment §8).

    See ``attribution.py``: ``juli`` when the value now on TikTok hashes to a
    Juli write's after-value inside [occurred_at - 72 h, occurred_at + 1 h];
    ``seller_revert`` when it hashes to the most recent Juli write's
    before-value (any age); else ``seller_change`` -- also for every field Juli
    never writes.
    """
    names = attribution_fields(change.kind, change.fields)
    until = occurred_at + JULI_WRITE_LOOKAHEAD
    if known_at is not None:
        until = min(until, known_at)
    writes = await juli_writes(
        session,
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        fields=names,
        until=until,
    )
    return label_fields(
        change.kind,
        change.fields,
        ProductFields.of(new),
        writes,
        occurred_at=occurred_at,
        known_at=known_at,
    )


async def matches_juli_write(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    change: Change,
    new: NormalizedProduct,
    occurred_at: datetime,
) -> bool:
    """True when every field of ``change`` is Juli's (``attribute_fields``, all ``juli``).

    A field Juli never writes (attributes, category, status) makes the change
    external. A write matches when it touched the same product and field,
    was recorded within [occurred_at - 72 h, occurred_at + 1 h], and its
    after-value hash equals what TikTok now shows (or it has no after-value).
    """
    labels = await attribute_fields(
        session,
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
        change=change,
        new=new,
        occurred_at=occurred_at,
    )
    return all_juli(labels)


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
        labels = await attribute_fields(
            session,
            shop_id=shop_id,
            tiktok_product_id=new.tiktok_product_id,
            change=change,
            new=new,
            occurred_at=occurred_at,
            known_at=now,
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
            juli_write=all_juli(labels),
            details=details,
            dedup_key=f"snap:{snapshot.id}:{change.kind}",
            field_attribution=labels,
        )
        if row is not None:
            recorded.append(row)
    return ReadOutcome(snapshot, recorded)


__all__ = [
    "JULI_WRITE_LOOKAHEAD",
    "JULI_WRITE_LOOKBACK",
    "ReadOutcome",
    "attribute_fields",
    "has_any_snapshot",
    "juli_writes",
    "latest_snapshots",
    "matches_juli_write",
    "previous_state",
    "product_fields_of_snapshot",
    "record_change",
    "record_read",
]
