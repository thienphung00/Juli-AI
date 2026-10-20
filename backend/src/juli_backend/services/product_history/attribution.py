"""Per-field attribution of a product change (ADR-107 amendment 2026-10-20 §8, P60-1b). Pure.

Each field of an observed change gets one label:

- ``juli`` -- the value now on TikTok hashes to the ``after_hash`` of a Juli
  write (``run_write_values``) of that product and field recorded inside the
  tolerance window ``[occurred_at - 72 h, occurred_at + 1 h]`` (listing edits
  can sit in TikTok review for hours; clocks skew). A write with no recorded
  after-value counts, as it always has (``_value_matches``: not comparable);
- ``seller_revert`` -- otherwise, the value equals the ``before_hash`` of the
  **most recent** Juli write of that (product, field), whatever its age: the
  seller put back what Juli replaced;
- ``seller_change`` -- anything else, and every field Juli never writes
  (attributes, category, status, a product's creation, a promotion).

The row's ``attribution`` is the common label, or ``mixed`` when the fields
differ. ``matches_juli_write`` is ``all(label == 'juli')``.

Only writes known when the change was detected count (``known_at``): the live
path cannot see a later write, so the backfill does not either -- both give the
same labels for the same row.

Hashes are :func:`normalize.field_value_hash`; a write row recorded before
migration 096 (or whose hash column is NULL) is hashed from its stored value
here, so the result never depends on whether its hash was backfilled.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from juli_backend.models.history import (
    ATTRIBUTION_JULI,
    ATTRIBUTION_MIXED,
    ATTRIBUTION_SELLER_CHANGE,
    ATTRIBUTION_SELLER_REVERT,
    KIND_CONTENT,
    KIND_PRICE,
)
from juli_backend.services.product_history.normalize import ProductFields, field_value_hash

#: A Juli write counts for a change TikTok dated up to this long after the write ...
JULI_WRITE_LOOKBACK = timedelta(hours=72)
#: ... or this long before it (clock skew between TikTok and Juli).
JULI_WRITE_LOOKAHEAD = timedelta(hours=1)
#: The fields Juli's agent writes (``run_write_values.field``).
JULI_FIELDS: frozenset[str] = frozenset({"title", "description", "main_images", "price"})


@dataclass(frozen=True)
class WriteRecord:
    """What attribution needs of one ``run_write_values`` row."""

    field: str
    recorded_at: datetime
    before_value: Any
    after_value: Any
    before_hash: str | None = None
    after_hash: str | None = None
    workflow_run_id: uuid.UUID | None = None

    @classmethod
    def of(cls, row: Any) -> WriteRecord:
        return cls(
            field=row.field,
            recorded_at=row.recorded_at,
            before_value=row.before_value,
            after_value=row.after_value,
            before_hash=getattr(row, "before_hash", None),
            after_hash=getattr(row, "after_hash", None),
            workflow_run_id=getattr(row, "workflow_run_id", None),
        )

    def after(self) -> str | None:
        return self.after_hash or field_value_hash(self.field, self.after_value)

    def before(self) -> str | None:
        return self.before_hash or field_value_hash(self.field, self.before_value)


def attribution_fields(kind: str, fields: Sequence[str]) -> list[str]:
    """The fields a change is attributed on: Juli's ``price`` for a price change.

    A price change lists ``price`` plus which price moved (``list_price`` /
    ``sale_price``); Juli writes the one ``price`` field (the list price), so
    the change is attributed on that. Every other kind keeps its fields.
    """
    if kind == KIND_PRICE:
        return ["price"]
    names = [str(name) for name in fields]
    return names or ["product"]


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def label_field(
    field: str,
    state: ProductFields | None,
    writes: Iterable[WriteRecord],
    *,
    occurred_at: datetime,
    known_at: datetime | None = None,
) -> str:
    """One field's label (see module docstring). ``writes`` may hold any fields."""
    if field not in JULI_FIELDS or state is None:
        return ATTRIBUTION_SELLER_CHANGE
    occurred = _naive(occurred_at)
    latest_allowed = occurred + JULI_WRITE_LOOKAHEAD
    if known_at is not None:
        latest_allowed = min(latest_allowed, _naive(known_at))
    mine = sorted(
        (w for w in writes if w.field == field and _naive(w.recorded_at) <= latest_allowed),
        key=lambda w: _naive(w.recorded_at),
    )
    earliest = occurred - JULI_WRITE_LOOKBACK
    for write in mine:
        if _naive(write.recorded_at) < earliest:
            continue
        if write.after_value is None and write.after_hash is None:
            return ATTRIBUTION_JULI
        if write.after() == state.field_hash(field, like=write.after_value):
            return ATTRIBUTION_JULI
    if mine:
        last = mine[-1]
        before = last.before()
        if before is not None and before == state.field_hash(field, like=last.before_value):
            return ATTRIBUTION_SELLER_REVERT
    return ATTRIBUTION_SELLER_CHANGE


def label_fields(
    kind: str,
    fields: Sequence[str],
    state: ProductFields | None,
    writes: Iterable[WriteRecord],
    *,
    occurred_at: datetime,
    known_at: datetime | None = None,
) -> dict[str, str]:
    """``{field: label}`` for one change. Only content and price changes can be Juli's."""
    names = attribution_fields(kind, fields)
    rows = list(writes)
    if kind not in (KIND_CONTENT, KIND_PRICE):
        return {name: ATTRIBUTION_SELLER_CHANGE for name in names}
    return {
        name: label_field(name, state, rows, occurred_at=occurred_at, known_at=known_at)
        for name in names
    }


def uniform_labels(kind: str, fields: Sequence[str], *, juli_write: bool) -> dict[str, str]:
    """Every field ``juli`` or every field ``seller_change`` (a promotion row, §11)."""
    label = ATTRIBUTION_JULI if juli_write else ATTRIBUTION_SELLER_CHANGE
    return {name: label for name in attribution_fields(kind, fields)}


def summarize(labels: Mapping[str, str]) -> str:
    """The row's ``attribution``: the one label every field shares, else ``mixed``."""
    distinct = set(labels.values())
    if not distinct:
        return ATTRIBUTION_SELLER_CHANGE
    return distinct.pop() if len(distinct) == 1 else ATTRIBUTION_MIXED


def all_juli(labels: Mapping[str, str]) -> bool:
    return bool(labels) and all(label == ATTRIBUTION_JULI for label in labels.values())


def non_juli_fields(labels: Mapping[str, str]) -> list[str]:
    return sorted(name for name, label in labels.items() if label != ATTRIBUTION_JULI)


def event_attribution(labels: Mapping[str, str]) -> str:
    """A ``seller_change`` event's ``payload.attribution``: ``seller_revert`` only when
    every non-Juli field is a revert, else ``seller_change``."""
    others = {label for label in labels.values() if label != ATTRIBUTION_JULI}
    if others == {ATTRIBUTION_SELLER_REVERT}:
        return ATTRIBUTION_SELLER_REVERT
    return ATTRIBUTION_SELLER_CHANGE


__all__ = [
    "JULI_FIELDS",
    "JULI_WRITE_LOOKAHEAD",
    "JULI_WRITE_LOOKBACK",
    "WriteRecord",
    "all_juli",
    "attribution_fields",
    "event_attribution",
    "label_field",
    "label_fields",
    "non_juli_fields",
    "summarize",
    "uniform_labels",
]
