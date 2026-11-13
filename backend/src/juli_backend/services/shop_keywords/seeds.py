"""The shop's keyword seeds (ADR-119, D81.4 / D81.6): generated from its titles, trimmed by Ops.

Every function runs under the caller's shop scope (``with_shop_scope``): ``platform_items``
and ``shop_keyword_seeds`` are tenant-direct, so RLS keeps one shop's titles and seeds out
of another's. Nothing here commits; the route commits after the audit row.

Re-generating never undoes the operator's trim: a combination already stored keeps its
``enabled`` flag and gets the new pattern and item ids; a new one starts enabled. A stored
combination the titles no longer produce stays as it is (the operator disables it).

With a model client, one call per shop refines the decomposer's candidates
(:mod:`.llm_seeds`); the "từ gần nghĩa" it returns are stored disabled for the owner to tick.
Without one, or when the model is unavailable, the deterministic candidates are stored as before.
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
from juli_backend.services.shop_keywords import llm_seeds
from juli_backend.services.shop_keywords.collection import normalize_keyword
from juli_backend.services.shop_keywords.decompose import Candidate, Title, decompose
from juli_backend.services.shopee_builder.llm import LLMClient, LLMUnavailable

MAX_BRAND = 100


class SeedNotFound(LookupError):
    """No such seed in this shop."""


@dataclass(frozen=True)
class GenerateResult:
    titles: int
    candidates: int
    created: int
    updated: int
    titles_hash: str = ""
    llm_used: bool = False
    llm_reason: str | None = None
    near: tuple[str, ...] = ()


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
    client: LLMClient | None = None,
    llm_reason: str | None = None,
) -> GenerateResult:
    """Decompose the shop's titles and upsert the combinations (no commit).

    ``client`` is the shop's gated model client; ``llm_reason`` says why there is none.
    """
    titles = await shop_titles(session, shop_id, platform)
    candidates = decompose(titles, brand=brand)
    refined: llm_seeds.Refinement | None = None
    if client is not None and candidates:
        try:
            refined = await llm_seeds.refine(client, titles, candidates)
        except LLMUnavailable as exc:
            llm_reason = exc.reason
    elif client is None and llm_reason is None:
        llm_reason = "no_client"
    stored: list[tuple[Candidate, bool]] = [(c, True) for c in candidates]
    near: tuple[str, ...] = ()
    if refined is not None:
        stored = [(c, True) for c in refined.seeds] + [(c, False) for c in refined.near]
        near = tuple(c.keyword for c in refined.near)
    created, updated = await _upsert(session, shop_id, platform, stored, staff_id, now)
    return GenerateResult(
        len(titles),
        len(stored),
        created,
        updated,
        titles_hash=llm_seeds.titles_hash(titles, brand),
        llm_used=refined is not None,
        llm_reason=None if refined is not None else llm_reason,
        near=near,
    )


async def _upsert(
    session: AsyncSession,
    shop_id: uuid.UUID,
    platform: str,
    stored: list[tuple[Candidate, bool]],
    staff_id: uuid.UUID | None,
    now: datetime,
) -> tuple[int, int]:
    existing = {s.keyword: s for s in await list_seeds(session, shop_id, platform)}
    created = updated = 0
    for candidate, enabled in stored:
        keyword = normalize_keyword(candidate.keyword)
        item_ids = list(candidate.item_ids)
        seed = existing.get(keyword)
        if seed is None:
            row = ShopKeywordSeed(
                id=uuid.uuid4(),
                shop_id=shop_id,
                platform=platform,
                keyword=keyword,
                pattern=candidate.pattern,
                item_ids=item_ids,
                enabled=enabled,
                created_by=staff_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            existing[keyword] = row
            created += 1
        elif seed.pattern != candidate.pattern or list(seed.item_ids) != item_ids:
            seed.pattern = candidate.pattern
            seed.item_ids = item_ids
            seed.updated_at = now
            updated += 1
    await session.flush()
    return created, updated


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
