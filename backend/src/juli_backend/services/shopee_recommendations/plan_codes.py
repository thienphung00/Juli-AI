"""Plan codes (P91 D-10): ``KH-<yymm>-<seq3>``, issued when a plan is confirmed.

Per shop, never reused, the sequence runs across months (``KH-2611-003`` is the third plan the
shop ever confirmed). The same technique as the card codes (:mod:`.codes`): one
``UPDATE .. RETURNING`` on the shop's counter row holds its lock until the transaction ends, so
concurrent confirms never share a number and a rolled-back confirm gives its number back.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_plans import ShopRecoPlan, ShopRecoPlanCounter
from juli_backend.services.shopee_recommendations import config

PLAN_CODE_RE = re.compile(
    rf"^{config.PLAN_CODE_PREFIX}-(?P<yymm>\d{{4}})-(?P<seq>\d{{{config.PLAN_SEQ_DIGITS},}})$"
)


def format_plan_code(when: datetime, seq: int) -> str:
    if seq < 1:
        raise ValueError("a plan sequence number starts at 1")
    return f"{config.PLAN_CODE_PREFIX}-{when:%y%m}-{seq:0{config.PLAN_SEQ_DIGITS}d}"


def parse_plan_code(value: str) -> str | None:
    """The normalised plan code, or None when ``value`` is not one."""
    m = PLAN_CODE_RE.match(value.strip().upper())
    return None if m is None else f"{config.PLAN_CODE_PREFIX}-{m['yymm']}-{m['seq']}"


async def next_seq(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> int:
    c = ShopRecoPlanCounter
    for _ in range(5):
        row = (
            await session.execute(
                update(c)
                .where(c.shop_id == shop_id)
                .values(last_seq=c.last_seq + 1, updated_at=now)
                .returning(c.last_seq)
            )
        ).first()
        if row is not None:
            return int(row[0])
        try:
            async with session.begin_nested():
                session.add(ShopRecoPlanCounter(shop_id=shop_id, last_seq=1, updated_at=now))
                await session.flush()
            return 1
        except IntegrityError:
            continue  # another transaction created the row first: bump it instead
    raise RuntimeError("could not allocate a plan code")  # pragma: no cover


async def assign_plan_code(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> str:
    return format_plan_code(now, await next_seq(session, shop_id, now))


async def plan_codes_for(
    session: AsyncSession, shop_id: uuid.UUID, plan_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, str | None]:
    """``{plan id: code}`` (None for a draft) -- what a card summary shows as its plan code."""
    wanted = sorted({p for p in plan_ids if p is not None}, key=str)
    if not wanted:
        return {}
    rows = await session.execute(
        select(ShopRecoPlan.id, ShopRecoPlan.code).where(
            ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.id.in_(wanted)
        )
    )
    return {pid: code for pid, code in rows.all()}
