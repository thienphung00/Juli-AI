"""The nightly account purge (P50-B, D68.10): due accounts and one account's deletion.

On Postgres both run as ``juli_ops`` through migration 094's SECURITY DEFINER
functions -- ``users`` is RLS-scoped to its own row and ``juli_app`` holds no
DELETE on any table. ``privacy_purge_account`` refuses an account that is not
due. SQLite (unit tests) has neither the functions nor RLS: it lists due ids with
a plain query and does not purge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import User
from juli_backend.services.ops.access import is_sqlite, ops_role


@dataclass(frozen=True)
class PurgeCounts:
    shops: int
    rows: int
    kept_periods: int


async def due_account_ids(session: AsyncSession, *, now: datetime) -> list[uuid.UUID]:
    if is_sqlite(session):
        stmt = select(User.id).where(
            User.deletion_scheduled_for.is_not(None), User.deletion_scheduled_for <= now
        )
        return list((await session.execute(stmt)).scalars())
    async with ops_role(session):
        rows = await session.execute(
            text("SELECT out_user_id FROM public.privacy_due_accounts(:now)").bindparams(now=now)
        )
        return [row[0] for row in rows.all()]


async def purge_account(session: AsyncSession, user_id: uuid.UUID) -> PurgeCounts:
    """Delete one due account and its shops' data; no commit (the task commits)."""
    if is_sqlite(session):
        raise RuntimeError("privacy_purge_account runs on Postgres only")
    async with ops_role(session):
        row = (
            await session.execute(
                text(
                    "SELECT out_shops, out_rows, out_kept_periods "
                    "FROM public.privacy_purge_account(:user_id)"
                ).bindparams(user_id=user_id)
            )
        ).one()
    return PurgeCounts(shops=int(row[0]), rows=int(row[1]), kept_periods=int(row[2]))


__all__ = ["PurgeCounts", "due_account_ids", "purge_account"]
