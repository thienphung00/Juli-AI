"""One precedence rule for every ranked upsert (owner 2026-11-18 + R7), composed per column by
``ranked_set`` and gated by ``ranked_where``:

- a HIGHER rank (``SOURCE_RANK``: API > Connector > file > vendor) replaces with its non-null
  values;
- at an EQUAL rank the newer capture wins (an older read uploaded after a newer one -- the
  Connector runs on several computers -- is ignored), and a NULL still never clears;
- a LOWER rank only fills the stored row's NULL columns;
- the provenance columns (source, rank, capture, versions, payload id, updated_at) follow the
  winning writer, never a gap-filler. No rank is ever lowered.

Tables without a ``captured_at`` column compare through ``raw_payload_id`` ->
``ingest_raw_payloads.captured_at`` (``payload_captured_at`` for the stored row,
``excluded_payload_captured_at`` for the post)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnClause, and_, case, func, literal_column, or_, select

from juli_backend.models.ingest import SOURCE_RANK, IngestRawPayload


def stored_rank(table: Any) -> Any:
    """The rank a stored row counts at: its ``source`` decides (``effective_rank``), so a row
    stored under older rank numbers (P90 D-5: file 3 > extension 2) counts at today's order."""
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
    stored_raw_id: ColumnClause[Any] = literal_column(f"{table.name}.raw_payload_id")
    return (
        select(IngestRawPayload.captured_at)
        .where(IngestRawPayload.id == stored_raw_id)
        .scalar_subquery()
    )


def not_older(stored_captured: Any, incoming_captured: Any) -> Any:
    """True when the stored capture time is unknown or not newer than the incoming one."""
    return or_(stored_captured.is_(None), stored_captured <= incoming_captured)


def excluded_payload_captured_at() -> Any:
    """The capture time of the raw payload the POSTED row names (NULL when it names none).

    ``excluded`` is referenced by name for the same reason as ``payload_captured_at``: a bound
    ``stmt.excluded.raw_payload_id`` would put ``excluded`` in the subquery's FROM."""
    posted_raw_id: ColumnClause[Any] = literal_column("excluded.raw_payload_id")
    return (
        select(IngestRawPayload.captured_at)
        .where(IngestRawPayload.id == posted_raw_id)
        .scalar_subquery()
    )


def _captures(table: Any, excluded: Any, stored_captured: Any, incoming_captured: Any) -> Any:
    """``(stored, incoming)`` capture times: the ``captured_at`` columns by default; a table
    without one passes its payloads' (``payload_captured_at`` / ``excluded_payload_...``)."""
    if stored_captured is None:
        stored_captured = table.c.captured_at
    if incoming_captured is None:
        incoming_captured = excluded.captured_at
    return stored_captured, incoming_captured


def _capture_not_older(stored_captured: Any, incoming_captured: Any) -> Any:
    """At an equal rank: the post is not older than the stored row. An unknown capture on either
    side does not block (a row written before captures were kept, a post without a payload)."""
    return or_(
        stored_captured.is_(None),
        incoming_captured.is_(None),
        stored_captured <= incoming_captured,
    )


def writer_wins(
    table: Any,
    excluded: Any,
    *,
    stored_captured: Any = None,
    incoming_captured: Any = None,
) -> Any:
    """SQL: the post is the row's winning writer -- a higher rank, or an equal rank and not an
    older capture. A post that does not win can only fill NULLs (a lower rank) or is dropped
    (``ranked_where``: an equal rank and an older capture)."""
    stored_captured, incoming_captured = _captures(
        table, excluded, stored_captured, incoming_captured
    )
    stored = stored_rank(table)
    return or_(
        stored < excluded.source_rank,
        and_(
            stored == excluded.source_rank,
            _capture_not_older(stored_captured, incoming_captured),
        ),
    )


def ranked_where(
    table: Any,
    excluded: Any,
    *,
    stored_captured: Any = None,
    incoming_captured: Any = None,
) -> Any:
    """The ``DO UPDATE ... WHERE`` of the composed rule: every post updates (a winner replaces, a
    lower rank fills NULLs) except an equal-rank one with an older capture, which is ignored."""
    stored_captured, incoming_captured = _captures(
        table, excluded, stored_captured, incoming_captured
    )
    return or_(
        stored_rank(table) != excluded.source_rank,
        _capture_not_older(stored_captured, incoming_captured),
    )


def ranked_value(
    table: Any,
    excluded: Any,
    column: str,
    *,
    wins: Any,
    provenance: bool = False,
) -> Any:
    """SQL for one column of the composed rule, given ``wins`` (``writer_wins``): the winner's
    non-null value, else the stored one; a non-winner's value only where the stored one is NULL;
    a ``provenance`` column is the winner's own (a NULL included) and never a gap-filler's."""
    incoming, stored = excluded[column], table.c[column]
    if provenance:
        return case((wins, incoming), else_=stored)
    return case((wins, func.coalesce(incoming, stored)), else_=func.coalesce(stored, incoming))


def ranked_set(
    table: Any,
    excluded: Any,
    columns: Iterable[str],
    provenance: Iterable[str],
    *,
    stored_captured: Any = None,
    incoming_captured: Any = None,
) -> dict[str, Any]:
    """The ``DO UPDATE SET`` of the composed rule for ``columns`` (``provenance`` names the
    columns that follow the winning writer). Use with ``ranked_where`` and the same captures."""
    wins = writer_wins(
        table, excluded, stored_captured=stored_captured, incoming_captured=incoming_captured
    )
    kept = frozenset(provenance)
    return {
        column: ranked_value(table, excluded, column, wins=wins, provenance=column in kept)
        for column in columns
    }


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
