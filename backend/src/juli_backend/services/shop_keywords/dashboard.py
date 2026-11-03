"""The "Từ khóa" board of one shop (ADR-119, D81.5 / D81.8): seeds joined with public metrics.

Per enabled-or-not seed: its pattern, source products, the latest volume / CPC / difficulty,
the volume per collection day (the weekly line), related keywords from the latest lookup of
that seed, and coverage:

- ``da_tra`` -- some ``ok`` lookup listed the keyword (as the seed or as a related row);
- ``khong_khop`` -- looked up, and the owner marked the site's answer empty (``no_match``);
- ``bi_chan`` -- every lookup of it was refused (``blocked``);
- ``chua_tra`` -- never looked up. Shown as "chưa tra", never as a volume of 0.

Products: ``co_tu_khoa`` when an enabled seed of the product reaches ``min_volume``;
``de_xuat_tieu_de`` (a title-proposal candidate) when every enabled seed of it has been looked
up (or it has none) and none reaches it; ``chua_du_du_lieu`` while some seed is still
``chua_tra`` / ``bi_chan``, or before any seed exists.

:func:`build_board` is pure; :func:`board` reads the shop's rows under its scope and the
public rows as ``juli_ops``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.market import (
    KEYWORD_STATUS_BLOCKED,
    KEYWORD_STATUS_NO_MATCH,
    KEYWORD_STATUS_OK,
    MarketKeywordMetric,
)
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services.shop_keywords.decompose import Title
from juli_backend.services.shop_keywords.metrics import metrics_for
from juli_backend.services.shop_keywords.seeds import list_seeds, shop_titles

COVERAGE_LOOKED_UP = "da_tra"
COVERAGE_NO_MATCH = "khong_khop"
COVERAGE_BLOCKED = "bi_chan"
COVERAGE_NOT_YET = "chua_tra"
COVERAGES = (COVERAGE_LOOKED_UP, COVERAGE_NO_MATCH, COVERAGE_BLOCKED, COVERAGE_NOT_YET)

PRODUCT_COVERED = "co_tu_khoa"
PRODUCT_TITLE_CANDIDATE = "de_xuat_tieu_de"
PRODUCT_INCOMPLETE = "chua_du_du_lieu"

DEFAULT_MIN_VOLUME = 100
MAX_RELATED = 10


@dataclass(frozen=True)
class _Point:
    collected_on: date
    row: MarketKeywordMetric


def _num(value: Decimal | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _numbers(row: MarketKeywordMetric) -> dict[str, Any]:
    return {
        "volume": row.volume,
        "cpc_min": _num(row.cpc_min),
        "cpc_max": _num(row.cpc_max),
        "difficulty": _num(row.difficulty),
        "competition": _num(row.competition),
        "opportunity": _num(row.opportunity),
    }


def _by_day(keyword: str, rows: Sequence[MarketKeywordMetric]) -> list[_Point]:
    """One row per collection day for ``keyword``: its own lookup first, else the largest
    volume any other lookup listed for it that day. ``ok`` rows with a volume only."""
    best: dict[date, MarketKeywordMetric] = {}
    for row in rows:
        if row.keyword != keyword or row.status != KEYWORD_STATUS_OK or row.volume is None:
            continue
        held = best.get(row.collected_on)
        own, held_own = row.seed == keyword, held is not None and held.seed == keyword
        if (
            held is None
            or (own and not held_own)
            or (own == held_own and (row.volume or 0) > (held.volume or 0))
        ):
            best[row.collected_on] = row
    return [_Point(day, best[day]) for day in sorted(best)]


def _coverage(keyword: str, rows: Sequence[MarketKeywordMetric]) -> str:
    ok = any(r.keyword == keyword and r.status == KEYWORD_STATUS_OK for r in rows)
    if ok:
        return COVERAGE_LOOKED_UP
    statuses = {r.status for r in rows if r.seed == keyword}
    if KEYWORD_STATUS_NO_MATCH in statuses:
        return COVERAGE_NO_MATCH
    if KEYWORD_STATUS_BLOCKED in statuses:
        return COVERAGE_BLOCKED
    return COVERAGE_NOT_YET


def _related(keyword: str, rows: Sequence[MarketKeywordMetric]) -> list[dict[str, Any]]:
    """The other rows of the latest ``ok`` lookup of this seed, by volume."""
    own = [r for r in rows if r.seed == keyword and r.status == KEYWORD_STATUS_OK]
    if not own:
        return []
    latest = max(r.collected_on for r in own)
    others = [r for r in own if r.collected_on == latest and r.keyword != keyword]
    others.sort(key=lambda r: (-(r.volume if r.volume is not None else -1), r.keyword))
    return [{"keyword": r.keyword, **_numbers(r)} for r in others[:MAX_RELATED]]


def build_board(
    seeds: Sequence[ShopKeywordSeed],
    titles: Sequence[Title],
    metrics: Sequence[MarketKeywordMetric],
    *,
    min_volume: int = DEFAULT_MIN_VOLUME,
) -> dict[str, Any]:
    names = {t.item_id: t.title for t in titles}
    relevant: dict[str, list[MarketKeywordMetric]] = defaultdict(list)
    for row in metrics:
        relevant[row.keyword].append(row)
        if row.seed != row.keyword:
            relevant[row.seed].append(row)

    keywords: list[dict[str, Any]] = []
    coverage_of: dict[str, str] = {}
    latest_volume: dict[str, int | None] = {}
    for seed in seeds:
        rows = relevant.get(seed.keyword, [])
        points = _by_day(seed.keyword, rows)
        coverage = _coverage(seed.keyword, rows)
        coverage_of[seed.keyword] = coverage
        latest = points[-1].row if points else None
        latest_volume[seed.keyword] = latest.volume if latest else None
        keywords.append(
            {
                "id": str(seed.id),
                "keyword": seed.keyword,
                "pattern": seed.pattern,
                "enabled": seed.enabled,
                "coverage": coverage,
                "products": [
                    {"item_id": item_id, "name": names.get(item_id)} for item_id in seed.item_ids
                ],
                "latest": (
                    {"collected_on": latest.collected_on.isoformat(), **_numbers(latest)}
                    if latest
                    else None
                ),
                "history": [
                    {"collected_on": p.collected_on.isoformat(), "volume": p.row.volume}
                    for p in points
                ],
                "related": _related(seed.keyword, rows),
            }
        )
    keywords.sort(
        key=lambda k: (
            not k["enabled"],
            -(k["latest"]["volume"] if k["latest"] and k["latest"]["volume"] is not None else -1),
            k["keyword"],
        )
    )

    enabled = [s for s in seeds if s.enabled]
    products: list[dict[str, Any]] = []
    for title in titles:
        mine = [s.keyword for s in enabled if title.item_id in s.item_ids]
        volumes = [v for v in (latest_volume[k] for k in mine) if v is not None]
        best = max(volumes) if volumes else None
        if best is not None and best >= min_volume:
            status = PRODUCT_COVERED
        elif not enabled or any(
            coverage_of[k] in (COVERAGE_NOT_YET, COVERAGE_BLOCKED) for k in mine
        ):
            status = PRODUCT_INCOMPLETE
        else:
            status = PRODUCT_TITLE_CANDIDATE
        products.append(
            {
                "item_id": title.item_id,
                "name": title.title,
                "keywords": len(mine),
                "best_volume": best,
                "status": status,
            }
        )
    order = {PRODUCT_TITLE_CANDIDATE: 0, PRODUCT_INCOMPLETE: 1, PRODUCT_COVERED: 2}
    products.sort(key=lambda p: (order[p["status"]], p["item_id"]))

    counts = {c: 0 for c in COVERAGES}
    for seed in enabled:
        counts[coverage_of[seed.keyword]] += 1
    return {
        "min_volume": min_volume,
        "collection_dates": sorted({r.collected_on.isoformat() for r in metrics}),
        "coverage": counts,
        "to_look_up": sorted(
            s.keyword
            for s in enabled
            if coverage_of[s.keyword] in (COVERAGE_NOT_YET, COVERAGE_BLOCKED)
        ),
        "keywords": keywords,
        "products": products,
    }


async def board(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, *, min_volume: int
) -> dict[str, Any]:
    """The board: the shop's rows under its own scope, then the public rows."""
    async with with_shop_scope(session, shop_id):
        seeds = await list_seeds(session, shop_id, platform)
        titles = await shop_titles(session, shop_id, platform)
    metrics = await metrics_for(session, (s.keyword for s in seeds))
    return build_board(seeds, titles, metrics, min_volume=min_volume)
