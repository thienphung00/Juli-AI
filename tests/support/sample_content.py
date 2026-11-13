"""P100 S2-D test helpers: a seeded title spec for any product, with titles that pass the screen.

Synthetic rows only. ``passing_titles`` derives candidates from the product's own title (its words
in another order), so no claim, number or keyword is added that the facts do not hold.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_content_specs import (
    SCHEMA_VERSION,
    SOURCE_SEEDED,
    SPEC_TITLE,
    CardContentSpec,
)
from juli_backend.services.sample_shop.content_specs import SEEDED_MODEL, canonical_hash
from juli_backend.services.shopee_builder import service as builder


async def passing_titles(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, *, as_of: date, now: datetime
) -> list[str]:
    """Two titles the screen accepts for ``item_id``: the current title's words, reordered."""
    _, facts = await builder.draft_facts(session, shop_id, item_id, as_of=as_of, now=now)
    words = facts.title.split()
    assert len(words) >= 3, facts.title
    return [" ".join(reversed(words)), " ".join(words[1:] + words[:1])]


async def seed_title_spec(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    titles: list[str],
    *,
    now: datetime,
) -> CardContentSpec:
    inputs = {"current_title": "", "keywords": [], "banned_terms": [], "max_chars": 100}
    row = CardContentSpec(
        id=uuid.uuid4(),
        shop_id=shop_id,
        spec_type=SPEC_TITLE,
        item_id=item_id,
        schema_version=SCHEMA_VERSION,
        inputs_hash=canonical_hash(inputs),
        spec={
            "inputs": inputs,
            "candidates": [
                {
                    "title": t,
                    "chars": len(t),
                    "keywords_placed": [],
                    "keywords_late": [],
                    "note": "",
                }
                for t in titles
            ],  # fmt: skip
            "chosen": None,
            "model": SEEDED_MODEL,
        },
        source=SOURCE_SEEDED,
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return row
