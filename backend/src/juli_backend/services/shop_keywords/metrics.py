"""Public keyword metrics (ADR-119, D81.5): written and read as ``juli_ops``.

``market_keyword_metrics`` is the public lane (no ``shop_id``) and Ops-only, so every
statement here runs under :func:`ops_role`. Nothing here commits.

A re-upload of the same (source, keyword, seed, day) replaces its numbers, with one
exception: a ``blocked`` / ``no_match`` row never overwrites an ``ok`` row of the same day
(a refused retry must not erase a result already collected).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PLATFORM_SHOPEE
from juli_backend.models.market import (
    KEYWORD_SOURCE_SHOPEEANALYTICS,
    KEYWORD_STATUS_OK,
    MarketKeywordMetric,
)
from juli_backend.services.ops import ops_role
from juli_backend.services.shop_keywords.collection import (
    CollectionRecord,
    MetricRow,
    metric_rows,
)

SOURCE = KEYWORD_SOURCE_SHOPEEANALYTICS
#: Bound parameters per ``IN`` list.
CHUNK = 500


@dataclass(frozen=True)
class StoreResult:
    records: int
    rows_written: int
    rows_kept: int
    by_status: dict[str, int]
    collected_on: list[str]


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _apply(target: MarketKeywordMetric, row: MetricRow, now: datetime) -> None:
    target.status = row.status
    target.volume = row.volume
    target.cpc_min = _decimal(row.cpc_min)
    target.cpc_max = _decimal(row.cpc_max)
    target.difficulty = _decimal(row.difficulty)
    target.competition = _decimal(row.competition)
    target.opportunity = _decimal(row.opportunity)
    target.extra = dict(row.extra)
    target.updated_at = now


async def store_records(
    session: AsyncSession, records: Sequence[CollectionRecord], *, now: datetime
) -> StoreResult:
    """Upsert every record's rows (no commit)."""
    by_key: dict[tuple[str, str, date], MetricRow] = {}
    for record in records:
        for row in metric_rows(record):
            # Within one upload the last line for a key wins, as a re-upload would.
            by_key[(row.keyword, row.seed, row.collected_on)] = row
    written = kept = 0
    async with ops_role(session):
        existing: dict[tuple[str, str, date], MarketKeywordMetric] = {}
        seeds = sorted({row.seed for row in by_key.values()})
        days = sorted({row.collected_on for row in by_key.values()})
        for start in range(0, len(seeds), CHUNK):
            found = await session.scalars(
                select(MarketKeywordMetric).where(
                    MarketKeywordMetric.source == SOURCE,
                    MarketKeywordMetric.seed.in_(seeds[start : start + CHUNK]),
                    MarketKeywordMetric.collected_on.in_(days),
                )
            )
            for m in found.all():
                existing[(m.keyword, m.seed, m.collected_on)] = m
        for key, row in by_key.items():
            current = existing.get(key)
            if current is None:
                fresh = MarketKeywordMetric(
                    platform=PLATFORM_SHOPEE,
                    source=SOURCE,
                    keyword=row.keyword,
                    seed=row.seed,
                    collected_on=row.collected_on,
                    created_at=now,
                )
                _apply(fresh, row, now)
                session.add(fresh)
                written += 1
            elif current.status == KEYWORD_STATUS_OK and row.status != KEYWORD_STATUS_OK:
                kept += 1
            else:
                _apply(current, row, now)
                written += 1
    status_counts = Counter(r.status for r in records)
    return StoreResult(
        records=len(records),
        rows_written=written,
        rows_kept=kept,
        by_status=dict(sorted(status_counts.items())),
        collected_on=sorted({r.collected_on.isoformat() for r in records}),
    )


async def metrics_for(session: AsyncSession, keywords: Iterable[str]) -> list[MarketKeywordMetric]:
    """Every row whose keyword or seed is one of ``keywords`` (oldest day first)."""
    wanted = sorted(set(keywords))
    out: list[MarketKeywordMetric] = []
    async with ops_role(session):
        for start in range(0, len(wanted), CHUNK):
            part = wanted[start : start + CHUNK]
            found = await session.scalars(
                select(MarketKeywordMetric)
                .where(
                    or_(MarketKeywordMetric.keyword.in_(part), MarketKeywordMetric.seed.in_(part))
                )
                .order_by(MarketKeywordMetric.collected_on, MarketKeywordMetric.id)
            )
            out.extend(found.all())
    unique = {m.id: m for m in out}
    return sorted(unique.values(), key=lambda m: (m.collected_on, m.seed, m.keyword))
