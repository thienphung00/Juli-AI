"""The ops audit log (D25.2): who, which shop, what, before/after, when."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.ops.access import ops_role


@dataclass(frozen=True)
class Actor:
    """Who did it: a staff row, or the system (``staff_id=None``)."""

    staff_id: uuid.UUID | None
    email: str


SYSTEM_ACTOR = Actor(staff_id=None, email="system")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))


async def record(
    session: AsyncSession,
    actor: Actor,
    action: str,
    *,
    shop_id: uuid.UUID | None = None,
    before: Any = None,
    after: Any = None,
    at: datetime | None = None,
) -> OpsAuditLog:
    """Append one audit row (no commit; the caller's transaction owns it)."""
    row = OpsAuditLog(
        id=uuid.uuid4(),
        actor_staff_id=actor.staff_id,
        actor_email=actor.email,
        shop_id=shop_id,
        action=action,
        before=_jsonable(before),
        after=_jsonable(after),
    )
    if at is not None:
        row.at = at
    async with ops_role(session):
        session.add(row)
    return row


async def list_entries(
    session: AsyncSession, *, shop_id: uuid.UUID | None = None, limit: int = 100
) -> list[OpsAuditLog]:
    stmt = select(OpsAuditLog).order_by(OpsAuditLog.at.desc(), OpsAuditLog.id).limit(limit)
    if shop_id is not None:
        stmt = stmt.where(OpsAuditLog.shop_id == shop_id)
    async with ops_role(session):
        return list((await session.execute(stmt)).scalars().all())
