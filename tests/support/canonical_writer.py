"""``InMemoryCanonicalWriter``: the ``CanonicalWriter`` contract held in two dicts (tests only).

The DB writer is ``services.ingest.canonical_writer.DbCanonicalWriter``; this double applies the
same rules (``canonical.replaces``, ``merge_*`` for a same-or-higher rank, ``fill_*_gaps`` for a
lower one, the line rank from ``SOURCE_RANK[source]``) so a test of a mapper or a rebuild can
assert stored state without a database. Production code never imports it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from juli_backend.models.ingest import effective_rank
from juli_backend.services.ingest.canonical import (
    OrderLine,
    OrderSettlement,
    check_scope,
    fill_line_gaps,
    fill_settlement_gaps,
    merge_line,
    merge_settlement,
    replaces,
)


class InMemoryCanonicalWriter:
    def __init__(self) -> None:
        self.lines: dict[tuple[object, ...], OrderLine] = {}
        self.settlements: dict[tuple[object, ...], OrderSettlement] = {}

    async def upsert_order_lines(
        self, shop_id: uuid.UUID, platform: str, lines: Sequence[OrderLine]
    ) -> int:
        check_scope(shop_id, platform, lines)
        written = 0
        for line in lines:
            stored = self.lines.get(line.key)
            if stored is None:
                self.lines[line.key] = line
            else:
                if replaces(effective_rank(stored.source, 0), effective_rank(line.source, 0)):
                    self.lines[line.key] = merge_line(stored, line)
                else:
                    filled = fill_line_gaps(stored, line)
                    if filled == stored:
                        continue
                    self.lines[line.key] = filled
            written += 1
        return written

    async def upsert_settlements(
        self, shop_id: uuid.UUID, platform: str, rows: Sequence[OrderSettlement]
    ) -> int:
        check_scope(shop_id, platform, rows)
        written = 0
        for row in rows:
            stored = self.settlements.get(row.key)
            if stored is None:
                self.settlements[row.key] = row
            else:
                if replaces(
                    effective_rank(stored.source, stored.source_rank),
                    effective_rank(row.source, row.source_rank),
                ):
                    self.settlements[row.key] = merge_settlement(stored, row)
                else:
                    filled = fill_settlement_gaps(stored, row)
                    if filled == stored:
                        continue
                    self.settlements[row.key] = filled
            written += 1
        return written


__all__ = ["InMemoryCanonicalWriter"]
