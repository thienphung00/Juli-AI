"""Ops staff and roles (D25.2): Xem (viewer) < Vận hành (operator) < Admin."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ops import (
    ROLE_ADMIN,
    ROLE_LABELS,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    ROLES,
    OpsStaff,
)
from juli_backend.repositories._base import utc_now_naive as _now
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import ops_role

_RANK = {ROLE_VIEWER: 0, ROLE_OPERATOR: 1, ROLE_ADMIN: 2}


class StaffError(ValueError):
    """A staff change the rules refuse (unknown role, last admin, …)."""


@dataclass(frozen=True)
class StaffMember:
    id: uuid.UUID
    email: str
    role: str
    active: bool
    user_id: uuid.UUID | None

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def at_least(self, role: str) -> bool:
        return _RANK.get(self.role, -1) >= _RANK[role]

    @property
    def actor(self) -> audit.Actor:
        return audit.Actor(staff_id=self.id, email=self.email)


def _member(row: OpsStaff) -> StaffMember:
    return StaffMember(
        id=row.id, email=row.email, role=row.role, active=row.active, user_id=row.user_id
    )


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def resolve_staff(
    session: AsyncSession, *, user_id: uuid.UUID, email: str | None
) -> StaffMember | None:
    """The active staff row for this Supabase user, binding ``user_id`` on first sight.

    A row seeded by e-mail only (``user_id`` NULL) is bound to the first
    Supabase user who signs in with that verified e-mail.
    """
    wanted = normalise_email(email) if email else None
    criteria = [OpsStaff.user_id == user_id]
    if wanted:
        criteria.append((OpsStaff.user_id.is_(None)) & (OpsStaff.email == wanted))
    async with ops_role(session):
        row = (
            (await session.execute(select(OpsStaff).where(or_(*criteria)).limit(1)))
            .scalars()
            .first()
        )
        if row is None or not row.active:
            return None
        if row.user_id is None:
            row.user_id = user_id
            row.updated_at = _now()
    return _member(row)


async def list_staff(session: AsyncSession) -> list[StaffMember]:
    async with ops_role(session):
        rows = (await session.execute(select(OpsStaff).order_by(OpsStaff.email))).scalars().all()
    return [_member(row) for row in rows]


async def _active_admins(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(OpsStaff)
                .where(OpsStaff.role == ROLE_ADMIN, OpsStaff.active.is_(True))
            )
        ).scalar_one()
    )


async def upsert_staff(
    session: AsyncSession,
    actor: StaffMember,
    *,
    email: str,
    role: str,
    active: bool = True,
) -> StaffMember:
    """Add or change a staff member (Admin only; audited)."""
    if role not in ROLES:
        raise StaffError(f"unknown role {role!r}")
    wanted = normalise_email(email)
    if "@" not in wanted:
        raise StaffError("invalid e-mail")
    async with ops_role(session):
        row = (
            (await session.execute(select(OpsStaff).where(OpsStaff.email == wanted)))
            .scalars()
            .first()
        )
        before = None if row is None else {"role": row.role, "active": row.active}
        if row is None:
            row = OpsStaff(id=uuid.uuid4(), email=wanted, role=role, active=active)
            session.add(row)
        else:
            demoting_admin = row.role == ROLE_ADMIN and (role != ROLE_ADMIN or not active)
            if demoting_admin and await _active_admins(session) <= 1:
                raise StaffError("cannot remove the last active Admin")
            row.role = role
            row.active = active
            row.updated_at = _now()
    await audit.record(
        session,
        actor.actor,
        "staff_upsert",
        before=before,
        after={"email": wanted, "role": role, "active": active},
    )
    return _member(row)
