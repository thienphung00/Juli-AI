"""Card codes (P91 D-5): ``JC-<yymm>-<seq4>``, versions ``<code>-V1`` .. ``-V4``.

A code names one card for good: unique per shop, never reused, assigned when the card is first
persisted, readable by a person and by the later Excel export (one query by code). The month in
it is the month the card was created; the sequence is per shop across months (``JC-2611-0007``
is the seventh card the shop ever got, made in November 2026). The UUID stays the primary key.

The sequence comes from ``shop_proposal_code_counters``: one row per shop, bumped with a single
``UPDATE .. RETURNING`` that holds the row's lock until the transaction ends, so concurrent
writers never share a number. A transaction that rolls back also rolls its number back.
``backfill_codes`` codes the Shopee proposals that predate migration 116, in ``created_at``
order (the additive migration gate refuses a data step inside a migration).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import ShopProposal, ShopProposalCodeCounter
from juli_backend.services.shopee_recommendations import config

CODE_RE = re.compile(
    rf"^{config.CODE_PREFIX}-(?P<yymm>\d{{4}})-(?P<seq>\d{{{config.CODE_SEQ_DIGITS},}})"
    rf"(?:-V(?P<version>[1-9]))?$"
)


def format_code(when: datetime, seq: int) -> str:
    if seq < 1:
        raise ValueError("a card sequence number starts at 1")
    return f"{config.CODE_PREFIX}-{when:%y%m}-{seq:0{config.CODE_SEQ_DIGITS}d}"


def version_code(code: str, version: int) -> str:
    if not 1 <= version <= config.MAX_VERSIONS:
        raise ValueError(f"version must be 1..{config.MAX_VERSIONS}")
    return f"{code}-V{version}"


def parse_code(value: str) -> tuple[str, int | None] | None:
    """``(card code, version or None)`` for a well-formed code or version code, else None."""
    m = CODE_RE.match(value.strip().upper())
    if m is None:
        return None
    base = f"{config.CODE_PREFIX}-{m['yymm']}-{m['seq']}"
    return base, (int(m["version"]) if m["version"] else None)


def _counter_bump(shop_id: uuid.UUID, now: datetime):  # noqa: ANN202
    c = ShopProposalCodeCounter
    return (
        update(c)
        .where(c.shop_id == shop_id)
        .values(last_seq=c.last_seq + 1, updated_at=now)
        .returning(c.last_seq)
    )


async def next_seq(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> int:
    """The shop's next sequence number. The UPDATE locks the counter row until the caller's
    transaction ends; the first card of a shop inserts the row (a lost race retries the UPDATE)."""
    for _ in range(5):
        row = (await session.execute(_counter_bump(shop_id, now))).first()
        if row is not None:
            return int(row[0])
        try:
            async with session.begin_nested():
                session.add(ShopProposalCodeCounter(shop_id=shop_id, last_seq=1, updated_at=now))
                await session.flush()
            return 1
        except IntegrityError:
            continue  # another transaction created the row first: bump it instead
    raise RuntimeError("could not allocate a card code")  # pragma: no cover


async def assign_code(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> str:
    return format_code(now, await next_seq(session, shop_id, now))


async def backfill_codes(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> int:
    """Code every Shopee proposal of the shop that has none, in ``created_at`` order. Idempotent;
    takes the counter's lock first so two runs never code the same proposal twice."""
    probe = (
        await session.execute(
            select(ShopProposal.id).where(
                ShopProposal.shop_id == shop_id,
                ShopProposal.platform == "shopee",
                ShopProposal.code.is_(None),
            )
        )
    ).first()
    if probe is None:
        return 0
    first = await next_seq(session, shop_id, now)  # also the lock; hands the first number out
    rows = (
        await session.scalars(
            select(ShopProposal)
            .where(
                ShopProposal.shop_id == shop_id,
                ShopProposal.platform == "shopee",
                ShopProposal.code.is_(None),
            )
            .order_by(ShopProposal.created_at, ShopProposal.id)
        )
    ).all()
    n = 0
    for p in rows:
        seq = first if n == 0 else await next_seq(session, shop_id, now)
        p.code = format_code(p.created_at or now, seq)
        n += 1
    if not rows:  # lost the race: give the number back (the lock is still ours)
        await session.execute(
            update(ShopProposalCodeCounter)
            .where(ShopProposalCodeCounter.shop_id == shop_id)
            .values(last_seq=ShopProposalCodeCounter.last_seq - 1)
        )
    await session.flush()
    return n
