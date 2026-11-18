"""One guard for every ranked upsert: the higher rank wins, and at an equal rank the newer
capture wins (R7). An older read uploaded after a newer one (the Connector runs on several
computers) never overwrites it. No rank is ever lowered.

Tables without a ``captured_at`` column compare through ``raw_payload_id`` ->
``ingest_raw_payloads.captured_at`` (``payload_captured_at``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, literal_column, or_, select

from juli_backend.models.ingest import SOURCE_RANK, IngestRawPayload


def stored_rank(table: Any) -> Any:
    """The rank a stored row counts at: its ``source`` decides (``effective_rank``), so a row
    written before D-5 (file = extension = 2) is still outranked by a file post."""
    return case(
        *[(table.c.source == source, rank) for source, rank in SOURCE_RANK.items()],
        else_=table.c.source_rank,
    )


def payload_captured_at(table: Any) -> Any:
    """The capture time of the raw payload a stored row came from (NULL when it has none).

    Used inside ``INSERT ... ON CONFLICT DO UPDATE WHERE``, where SQLAlchemy does not correlate
    a subquery to the insert target: a bound ``table.c.raw_payload_id`` would add the table to
    the subquery's FROM (a cross join returning many rows). The stored row is referenced by
    name instead, which Postgres resolves to the conflicting row."""
    stored_raw_id = literal_column(f"{table.name}.raw_payload_id")
    return (
        select(IngestRawPayload.captured_at)
        .where(IngestRawPayload.id == stored_raw_id)
        .scalar_subquery()
    )


def not_older(stored_captured: Any, incoming_captured: Any) -> Any:
    """True when the stored capture time is unknown or not newer than the incoming one."""
    return or_(stored_captured.is_(None), stored_captured <= incoming_captured)


def newer_wins_where(
    table: Any,
    excluded: Any,
    *,
    stored_captured: Any = None,
    incoming_captured: Any = None,
) -> Any:
    """The ``DO UPDATE ... WHERE`` of a rank-guarded upsert: update when the stored rank is
    lower, or equal and the stored capture is not newer. ``stored_captured`` defaults to the
    table's ``captured_at`` and ``incoming_captured`` to ``excluded.captured_at``."""
    if stored_captured is None:
        stored_captured = table.c.captured_at
    if incoming_captured is None:
        incoming_captured = excluded.captured_at
    stored = stored_rank(table)
    return or_(
        stored < excluded.source_rank,
        and_(stored == excluded.source_rank, not_older(stored_captured, incoming_captured)),
    )


def incoming_capture(provenance: dict[str, Any]) -> Any:
    """The capture time of the post being written: its ``captured_at`` when provenance carries
    it, else its raw payload's (a bound id), else ``None``."""
    value = provenance.get("captured_at")
    if isinstance(value, datetime):
        return value
    raw_id = provenance.get("raw_payload_id")
    if raw_id is None:
        return None
    return (
        select(IngestRawPayload.captured_at).where(IngestRawPayload.id == raw_id).scalar_subquery()
    )
