"""The shop's keyword seeds (ADR-119, D81.4 / D81.6): generated from its titles, trimmed by Ops.

Every function runs under the caller's shop scope (``with_shop_scope``): ``platform_items``
and ``shop_keyword_seeds`` are tenant-direct, so RLS keeps one shop's titles and seeds out
of another's. Nothing here commits; the route commits after the audit row.

Re-generating never undoes the operator's trim: a combination already stored keeps its
``enabled`` flag and gets the new pattern and item ids; a new one starts enabled. A stored
combination the titles no longer produce stays as it is (the operator disables it).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import ITEM_LEVEL_VARIATION, PlatformItem
from juli_backend.models.shop_keywords import ShopKeywordSeed
from juli_backend.services.shop_keywords.collection import normalize_keyword
from juli_backend.services.shop_keywords.decompose import Title, decompose

MAX_BRAND = 100


class SeedNotFound(LookupError):
    """No such seed in this shop."""


@dataclass(frozen=True)
class GenerateResult:
    titles: int
    candidates: int
    created: int
    updated: int


async def shop_titles(session: AsyncSession, shop_id: uuid.UUID, platform: str) -> list[Title]:
    """Item-level titles the shop's exports listed (variations are not separate products)."""
    rows = await session.execute(
        select(PlatformItem.item_id, PlatformItem.name)
        .where(
            PlatformItem.shop_id == shop_id,
            PlatformItem.platform == platform,
            PlatformItem.variation_id == ITEM_LEVEL_VARIATION,
            PlatformItem.name.is_not(None),
        )
        .order_by(PlatformItem.item_id)
    )
    return [Title(item_id, name) for item_id, name in rows.all() if name]


async def list_seeds(
    session: AsyncSession, shop_id: uuid.UUID, platform: str
) -> list[ShopKeywordSeed]:
    rows = await session.scalars(
        select(ShopKeywordSeed)
        .where(ShopKeywordSeed.shop_id == shop_id, ShopKeywordSeed.platform == platform)
        .order_by(ShopKeywordSeed.keyword)
    )
    return list(rows.all())


async def generate(
    session: AsyncSession,
    shop_id: uuid.UUID,
    platform: str,
    *,
    brand: str | None,
    staff_id: uuid.UUID | None,
    now: datetime,
) -> GenerateResult:
    """Decompose the shop's titles and upsert the combinations (no commit)."""
    titles = await shop_titles(session, shop_id, platform)
    candidates = decompose(titles, brand=brand)
    existing = {s.keyword: s for s in await list_seeds(session, shop_id, platform)}
    created = updated = 0
    for candidate in candidates:
        keyword = normalize_keyword(candidate.keyword)
        item_ids = list(candidate.item_ids)
        seed = existing.get(keyword)
        if seed is None:
            session.add(
                ShopKeywordSeed(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    platform=platform,
                    keyword=keyword,
                    pattern=candidate.pattern,
                    item_ids=item_ids,
                    enabled=True,
                    created_by=staff_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        elif seed.pattern != candidate.pattern or list(seed.item_ids) != item_ids:
            seed.pattern = candidate.pattern
            seed.item_ids = item_ids
            seed.updated_at = now
            updated += 1
    await session.flush()
    return GenerateResult(len(titles), len(candidates), created, updated)


async def set_enabled(
    session: AsyncSession, shop_id: uuid.UUID, seed_id: uuid.UUID, enabled: bool, *, now: datetime
) -> ShopKeywordSeed:
    seed = await session.scalar(
        select(ShopKeywordSeed).where(
            ShopKeywordSeed.id == seed_id, ShopKeywordSeed.shop_id == shop_id
        )
    )
    if seed is None:
        raise SeedNotFound(str(seed_id))
    if seed.enabled != enabled:
        seed.enabled = enabled
        seed.updated_at = now
        await session.flush()
    return seed


def seed_json(seed: ShopKeywordSeed) -> dict[str, Any]:
    return {
        "id": str(seed.id),
        "keyword": seed.keyword,
        "pattern": seed.pattern,
        "item_ids": list(seed.item_ids),
        "enabled": seed.enabled,
    }
