"""``seller_change`` events from attributed product changes (ADR-107 amendment §8, P60-1b).

Every ``external_changes`` row that is not entirely Juli's (``attribution`` !=
``juli``) is one ``seller_change`` event, on any product of any shop:

- ``card_id`` -- the card whose run **last wrote** one of the change's non-Juli
  fields of that product (``run_write_values`` -> ``workflow_runs.action_card_id``,
  writes known when the change was detected), else the card whose **plan window
  is open** on the product: its latest executed run on the product completed at
  most :data:`OPEN_PLAN_WINDOW` before the change (the day-14 measurement of
  ``run_measurement_finals``); else NULL -- a natural action (§10), allowed by
  migration 095's CHECK;
- ``payload.attribution`` -- ``seller_revert`` when every non-Juli field is a
  revert, else ``seller_change``; the full ``field_attribution`` and the
  non-Juli ``fields`` ride along;
- ``dedup_key`` -- ``seller_change:<external_change_id>``, shared by the live
  writer (``store.record_change``) and the backfill (:func:`seller_change_specs`).

The live writer runs in the caller's transaction inside a SAVEPOINT and never
raises (``writer._guarded``).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from juli_backend.models.card_events import (
    ACTOR_SELLER,
    EVENT_SELLER_CHANGE,
    SOURCE_BACKFILL,
    SOURCE_LIVE,
)
from juli_backend.services.card_events import keys
from juli_backend.services.card_events.outcomes import is_executed
from juli_backend.services.card_events.writer import EventSpec, _guarded, insert_event
from juli_backend.services.product_history.attribution import (
    JULI_FIELDS,
    JULI_WRITE_LOOKAHEAD,
    WriteRecord,
    all_juli,
    event_attribution,
    label_fields,
    non_juli_fields,
    uniform_labels,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: A card's plan window stays open this long after its run executed (the day-14
#: final measurement, ``run_measurement_finals``).
OPEN_PLAN_WINDOW = timedelta(days=14)
#: ``workflow_key`` of a card-less seller change (amendment §10: a natural action).
NATURAL_WORKFLOW_KEY = "natural"
SUBJECT_PRODUCT = "product"
SUBJECT_SHOP = "shop"
LINK_LAST_WRITE = "last_write"
LINK_OPEN_WINDOW = "open_window"


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value


@dataclass(frozen=True)
class RunRef:
    """What linkage needs of one ``workflow_runs`` row with a card."""

    id: uuid.UUID
    card_id: uuid.UUID
    workflow_key: str
    tiktok_product_id: str | None
    completed_at: datetime | None
    executed: bool
    is_revert: bool


@dataclass(frozen=True)
class CardLink:
    card_id: uuid.UUID | None
    run_id: uuid.UUID | None
    workflow_key: str
    how: str | None


NO_CARD = CardLink(None, None, NATURAL_WORKFLOW_KEY, None)


def link_card(
    *,
    fields: Sequence[str],
    tiktok_product_id: str | None,
    occurred_at: datetime,
    known_at: datetime | None,
    writes: Iterable[WriteRecord],
    runs: Mapping[uuid.UUID, RunRef],
) -> CardLink:
    """The card a seller change belongs to (module docstring); pure.

    ``writes``: Juli's writes of this product (any fields); ``runs``: the shop's
    runs with a card, by id.
    """
    occurred = _naive_utc(occurred_at)
    assert occurred is not None
    until = occurred + JULI_WRITE_LOOKAHEAD
    known = _naive_utc(known_at)
    if known is not None:
        until = min(until, known)
    wanted = set(fields) & JULI_FIELDS
    candidates = sorted(
        (
            w
            for w in writes
            if w.field in wanted
            and (_naive_utc(w.recorded_at) or until) <= until
            and w.workflow_run_id in runs
        ),
        key=lambda w: (_naive_utc(w.recorded_at), str(w.workflow_run_id)),
    )
    if candidates:
        run = runs[candidates[-1].workflow_run_id]  # type: ignore[index]
        return CardLink(run.card_id, run.id, run.workflow_key, LINK_LAST_WRITE)
    if tiktok_product_id is None:
        return NO_CARD
    open_runs = []
    for run in runs.values():
        done = _naive_utc(run.completed_at)
        if (
            run.tiktok_product_id == tiktok_product_id
            and run.executed
            and not run.is_revert
            and done is not None
            and done <= occurred < done + OPEN_PLAN_WINDOW
        ):
            open_runs.append((done, str(run.id), run))
    if open_runs:
        run = max(open_runs, key=lambda item: (item[0], item[1]))[2]
        return CardLink(run.card_id, run.id, run.workflow_key, LINK_OPEN_WINDOW)
    return NO_CARD


def seller_change_spec(
    change: Any, labels: Mapping[str, str], link: CardLink, *, source: str
) -> EventSpec | None:
    """The ``seller_change`` row of one attributed change; ``None`` when all ``juli``."""
    if not labels or all_juli(labels):
        return None
    pid = change.tiktok_product_id
    return EventSpec(
        shop_id=change.shop_id,
        card_id=link.card_id,
        event_type=EVENT_SELLER_CHANGE,
        actor=ACTOR_SELLER,
        occurred_at=change.occurred_at,
        workflow_key=link.workflow_key,
        subject_type=SUBJECT_PRODUCT if pid else SUBJECT_SHOP,
        subject_id=str(pid) if pid else "",
        dedup_key=keys.seller_change(change.id),
        source=source,
        workflow_run_id=link.run_id,
        payload={
            "attribution": event_attribution(labels),
            "field_attribution": dict(labels),
            "fields": non_juli_fields(labels),
            "external_change_id": change.id,
            "kind": change.kind,
            "change_source": change.source,
            "detected_at": change.detected_at,
            "card_link": link.how,
        },
    )


# -- loading ------------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def _run_ref(run: Any, tiktok_ids: Mapping[uuid.UUID, str]) -> RunRef:
    return RunRef(
        id=run.id,
        card_id=run.action_card_id,
        workflow_key=run.workflow_key,
        tiktok_product_id=tiktok_ids.get(run.product_id) if run.product_id else None,
        completed_at=run.completed_at,
        executed=is_executed(_text(run.status) or "", _text(run.stop_reason)),
        is_revert=run.reverts_run_id is not None,
    )


async def _load_runs(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    tiktok_product_id: str | None = None,
    run_ids: Iterable[uuid.UUID] = (),
) -> dict[uuid.UUID, RunRef]:
    """The shop's runs with a card: all of them, or those of one product plus ``run_ids``."""
    from sqlalchemy import or_

    from juli_backend.models.models import Product, WorkflowRun

    products = {
        pid: str(tid)
        for pid, tid in (
            await session.execute(
                select(Product.id, Product.tiktok_product_id).where(
                    Product.shop_id == shop_id,
                    *(
                        [Product.tiktok_product_id == tiktok_product_id]
                        if tiktok_product_id is not None
                        else []
                    ),
                )
            )
        ).all()
        if tid
    }
    query = select(WorkflowRun).where(
        WorkflowRun.shop_id == shop_id, WorkflowRun.action_card_id.isnot(None)
    )
    if tiktok_product_id is not None:
        ids = list(run_ids)
        query = query.where(
            or_(
                WorkflowRun.product_id.in_(list(products)),
                WorkflowRun.id.in_(ids) if ids else WorkflowRun.id.is_(None),
            )
        )
    runs = (await session.execute(query)).scalars()
    return {run.id: _run_ref(run, products) for run in runs}


# -- live ---------------------------------------------------------------------------------


async def record_seller_change(session: AsyncSession, change: Any) -> None:
    """``seller_change`` for a just-inserted ``external_changes`` row (live, never raises)."""
    labels = dict(change.field_attribution or {})
    if not labels or all_juli(labels):
        return
    async with _guarded(session, EVENT_SELLER_CHANGE, external_change_id=change.id):
        link = await _live_link(session, change, labels)
        spec = seller_change_spec(change, labels, link, source=SOURCE_LIVE)
        if spec is not None:
            await insert_event(session, spec)


async def _live_link(session: AsyncSession, change: Any, labels: Mapping[str, str]) -> CardLink:
    from juli_backend.models.run_changes import RunWriteValue

    pid = change.tiktok_product_id
    fields = sorted(set(non_juli_fields(labels)) & JULI_FIELDS)
    writes: list[WriteRecord] = []
    if pid is not None and fields:
        writes = [
            WriteRecord.of(row)
            for row in (
                await session.execute(
                    select(RunWriteValue).where(
                        RunWriteValue.shop_id == change.shop_id,
                        RunWriteValue.tiktok_product_id == pid,
                        RunWriteValue.field.in_(fields),
                    )
                )
            ).scalars()
        ]
    if pid is None:
        return NO_CARD
    runs = await _load_runs(
        session,
        change.shop_id,
        tiktok_product_id=pid,
        run_ids={w.workflow_run_id for w in writes if w.workflow_run_id is not None},
    )
    return link_card(
        fields=fields,
        tiktok_product_id=pid,
        occurred_at=change.occurred_at,
        known_at=change.detected_at,
        writes=writes,
        runs=runs,
    )


# -- backfill -----------------------------------------------------------------------------


def stored_or_computed_labels(
    change: Any,
    *,
    snapshot: Any | None,
    writes: Sequence[WriteRecord],
) -> dict[str, str]:
    """A row's labels: stored ``field_attribution``, else computed as the live path would.

    ``juli_write`` rows are entirely Juli's (the stored verdict wins). A content
    or price row is labelled against the snapshot it recorded
    (``details.snapshot_id``); without that snapshot no field can be matched and
    every field is ``seller_change``.
    """
    from juli_backend.models.history import KIND_CONTENT, KIND_PRICE
    from juli_backend.services.product_history.store import product_fields_of_snapshot

    if change.field_attribution:
        return dict(change.field_attribution)
    if change.juli_write or change.kind not in (KIND_CONTENT, KIND_PRICE):
        return uniform_labels(change.kind, change.fields or [], juli_write=change.juli_write)
    state = product_fields_of_snapshot(snapshot) if snapshot is not None else None
    return label_fields(
        change.kind,
        change.fields or [],
        state,
        writes,
        occurred_at=change.occurred_at,
        known_at=change.detected_at,
    )


async def seller_change_specs(session: AsyncSession, shop_id: uuid.UUID) -> list[EventSpec]:
    """Every ``seller_change`` the shop's ``external_changes`` imply (``source='backfill'``)."""
    from juli_backend.models.history import ExternalChange, ProductSnapshot
    from juli_backend.models.run_changes import RunWriteValue

    changes = list(
        (
            await session.execute(
                select(ExternalChange)
                .where(ExternalChange.shop_id == shop_id, ExternalChange.juli_write.is_(False))
                .order_by(ExternalChange.occurred_at, ExternalChange.id)
            )
        ).scalars()
    )
    if not changes:
        return []
    writes_by_product: dict[str, list[WriteRecord]] = {}
    for row in (
        await session.execute(
            select(RunWriteValue)
            .where(RunWriteValue.shop_id == shop_id)
            .order_by(RunWriteValue.recorded_at, RunWriteValue.id)
        )
    ).scalars():
        writes_by_product.setdefault(row.tiktok_product_id, []).append(WriteRecord.of(row))
    snapshot_ids: set[uuid.UUID] = set()
    for change in changes:
        raw = (
            (change.details or {}).get("snapshot_id") if change.field_attribution is None else None
        )
        try:
            if raw:
                snapshot_ids.add(uuid.UUID(str(raw)))
        except ValueError:
            continue
    snapshots: dict[str, Any] = {}
    if snapshot_ids:
        for snap in (
            await session.execute(
                select(ProductSnapshot).where(
                    ProductSnapshot.shop_id == shop_id, ProductSnapshot.id.in_(list(snapshot_ids))
                )
            )
        ).scalars():
            snapshots[str(snap.id)] = snap
    runs = await _load_runs(session, shop_id)

    specs: list[EventSpec] = []
    for change in changes:
        pid = change.tiktok_product_id
        writes = writes_by_product.get(pid, []) if pid else []
        snapshot = snapshots.get(str((change.details or {}).get("snapshot_id")))
        labels = stored_or_computed_labels(change, snapshot=snapshot, writes=writes)
        if all_juli(labels):
            continue
        link = link_card(
            fields=non_juli_fields(labels),
            tiktok_product_id=pid,
            occurred_at=change.occurred_at,
            known_at=change.detected_at,
            writes=writes,
            runs=runs,
        )
        spec = seller_change_spec(change, labels, link, source=SOURCE_BACKFILL)
        if spec is not None:
            specs.append(spec)
    return specs


__all__ = [
    "LINK_LAST_WRITE",
    "LINK_OPEN_WINDOW",
    "NATURAL_WORKFLOW_KEY",
    "NO_CARD",
    "OPEN_PLAN_WINDOW",
    "CardLink",
    "RunRef",
    "link_card",
    "record_seller_change",
    "seller_change_spec",
    "seller_change_specs",
    "stored_or_computed_labels",
]
