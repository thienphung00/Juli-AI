"""File vs Connector on the same key (P90 D-5, G-22): who wins, and how often they differ.

The winner is decided by the upsert in ``gateway.py`` (rank: api > file > extension > vendor, a
row is replaced only by the same or a higher rank). This module only COUNTS what that decision
did, before the write, so an operator sees "n file rows kept over the Connector, m Connector rows
replaced by a file, k of them with different numbers" in one ``ingest_source_conflicts`` log line.
Counts only -- never a row value.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_RANK, effective_rank
from juli_backend.services.ingest.mapping import KPI_COLUMNS

logger = logging.getLogger(__name__)

#: A numeric column is stored to 4 decimals; a smaller gap is rounding, not a difference.
TOLERANCE = Decimal("0.0001")


@dataclass(frozen=True)
class SourceConflicts:
    """What an incoming post meets on keys another source already wrote."""

    #: The stored row outranks the post (a Connector post over a file row): the post is dropped.
    kept_existing: int = 0
    #: The post outranks the stored row (a file post over a Connector row): it is replaced.
    replaced_existing: int = 0
    #: Same rank, other source (cannot happen with today's ranks; counted if it does).
    same_rank: int = 0
    #: Of all of the above, the keys whose KPI values differ (both sides non-null).
    differing: int = 0

    @property
    def total(self) -> int:
        return self.kept_existing + self.replaced_existing + self.same_rank


def _differs(existing: Any, incoming: dict[str, Any]) -> bool:
    for column in KPI_COLUMNS:
        old, new = getattr(existing, column), incoming.get(column)
        if old is None or new is None:
            continue
        if abs(Decimal(old) - Decimal(new)) > TOLERANCE:
            return True
    return False


async def count_source_conflicts(
    session: AsyncSession, model: Any, key_columns: tuple[str, ...], values: list[dict[str, Any]]
) -> SourceConflicts:
    """Compare ``values`` (rows about to be upserted into ``model``) with stored rows of ANOTHER
    source on the same key. Reads only; the shop scope is the caller's."""
    if not values:
        return SourceConflicts()
    table = model.__table__
    first = values[0]
    source = first["source"]
    where = [
        table.c.shop_id == first["shop_id"],
        table.c.platform == first["platform"],
        table.c.dataset == first["dataset"],
        table.c.source != source,
    ]
    if "day" in key_columns:
        days = [v["day"] for v in values]
        where.append(and_(table.c.day >= min(days), table.c.day <= max(days)))
    else:
        where += [
            table.c.period_start == first["period_start"],
            table.c.period_end == first["period_end"],
        ]
    stored = (await session.execute(select(model).where(*where))).scalars().all()
    if not stored:
        return SourceConflicts()
    by_key = {tuple(getattr(row, column) for column in key_columns): row for row in stored}
    incoming_rank = SOURCE_RANK[source]
    kept = replaced = same = differing = 0
    for value in values:
        row = by_key.get(tuple(value[column] for column in key_columns))
        if row is None:
            continue
        rank = effective_rank(row.source, row.source_rank)
        if rank > incoming_rank:
            kept += 1
        elif rank < incoming_rank:
            replaced += 1
        else:
            same += 1
        differing += _differs(row, value)
    return SourceConflicts(kept, replaced, same, differing)


def log_source_conflicts(shop_id: Any, dataset: str, source: str, found: SourceConflicts) -> None:
    if not found.total:
        return
    logger.info(
        "ingest_source_conflicts",
        extra={
            "shop_id": str(shop_id),
            "dataset": dataset,
            "source": source,
            "kept_existing": found.kept_existing,
            "replaced_existing": found.replaced_existing,
            "same_rank": found.same_rank,
            "differing": found.differing,
        },
    )
