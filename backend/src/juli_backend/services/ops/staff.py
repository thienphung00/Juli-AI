"""Ops staff and roles (D25.2): Xem (viewer) < Vận hành (operator) < Admin."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

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
    #: True when this resolution bound ``user_id`` to an e-mail-seeded row: the
    #: caller must commit. Not part of the member's identity.
    newly_bound: bool = field(default=False, compare=False)

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


# -- the resolved-staff cache (P22) ----------------------------------------------
#
# Every ``/v1/ops/*`` request resolves its staff member; on the production VPS
# that lookup was five round trips (BEGIN, role switch, read, role restore,
# COMMIT), ~1.1 s, for a row that changes a few times a month. It is cached per
# process for STAFF_CACHE_TTL_SECONDS, keyed by (Supabase user id, verified
# e-mail) -- an e-mail change is a different key, so it re-resolves at once.
#
# Only ACTIVE members are cached; a non-staff or inactive caller is looked up
# every time, so nobody is locked out longer than one request after being added.
# Any staff change made through THIS process (``upsert_staff``) clears the cache.
#
# THE TRADE-OFF, stated: the API runs several workers, and a role change or a
# deactivation made on one worker reaches the OTHER workers' caches only when
# their entry expires -- up to 60 s during which a just-removed member keeps
# their old role there. The Cloudflare Access gate and the Supabase JWT are
# still checked on every request; only the ops_staff row is cached.

STAFF_CACHE_TTL_SECONDS = 60.0

_cache: dict[tuple[uuid.UUID, str | None], tuple[float, StaffMember]] = {}
_cache_lock = threading.Lock()


def _cache_key(user_id: uuid.UUID, email: str | None) -> tuple[uuid.UUID, str | None]:
    return (user_id, normalise_email(email) if email else None)


def cached_staff(user_id: uuid.UUID, email: str | None) -> StaffMember | None:
    """The cached active member for this user, if resolved in the last 60 s."""
    key = _cache_key(user_id, email)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        stored_at, member = hit
        if time.monotonic() - stored_at > STAFF_CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        return member


def remember_staff(user_id: uuid.UUID, email: str | None, member: StaffMember) -> None:
    """Cache an ACTIVE member (call only after any binding write has committed)."""
    if not member.active:
        return
    stored = StaffMember(
        id=member.id,
        email=member.email,
        role=member.role,
        active=member.active,
        user_id=member.user_id,
    )
    with _cache_lock:
        _cache[_cache_key(user_id, email)] = (time.monotonic(), stored)


def clear_staff_cache() -> None:
    """Forget every cached member and signed-in user (any staff change; tests)."""
    with _cache_lock:
        _cache.clear()
        _user_cache.clear()


# -- the signed-in user cache (P29) ------------------------------------------------
#
# With the staff row cached, the dearest part of an Ops request was the users
# read in front of it: BEGIN, the user GUC, the users row, COMMIT -- four round
# trips, ~1.6 s from the VPS to the us-west-2 pooler, before the route touched
# its own data. The Ops console needs only two facts from that row: the id and
# the e-mail the staff cache is keyed by. Both are cached here, per process,
# for the same STAFF_CACHE_TTL_SECONDS, keyed by the VERIFIED JWT ``sub``.
#
# What is NOT cached: the token. ``get_ops_user`` verifies the Supabase JWT
# (signature, audience, expiry) on every request before looking here, and the
# Cloudflare Access gate runs on every request too. An entry is written only
# after the request resolved to an ACTIVE staff member, from a users row read
# (and committed) on that same request -- so a seller, or anyone who is not
# staff, is never cached and is re-read every time. Entries are not refreshed
# by hits: a read older than the TTL is always re-done.
#
# Invalidation: TTL, and ``clear_staff_cache`` (every staff change made in
# this process). The trade-off is the staff cache's own: a users-row change
# (only the e-mail matters here) reaches this process within 60 s.


@dataclass(frozen=True)
class OpsUser:
    """What the Ops console needs from the signed-in ``users`` row."""

    id: uuid.UUID
    email: str | None
    #: True when this came from the cache rather than this request's read.
    cached: bool = field(default=False, compare=False)


_user_cache: dict[uuid.UUID, tuple[float, OpsUser]] = {}


def cached_user(user_id: uuid.UUID) -> OpsUser | None:
    """The signed-in user read for this verified ``sub`` in the last 60 s, if any."""
    with _cache_lock:
        hit = _user_cache.get(user_id)
        if hit is None:
            return None
        stored_at, user = hit
        if time.monotonic() - stored_at > STAFF_CACHE_TTL_SECONDS:
            del _user_cache[user_id]
            return None
        return user


def remember_user(user: OpsUser) -> None:
    """Cache a user read on THIS request (never re-store a cached one: no TTL refresh)."""
    if user.cached:
        return
    stored = OpsUser(id=user.id, email=user.email, cached=True)
    with _cache_lock:
        _user_cache[user.id] = (time.monotonic(), stored)


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
        newly_bound = row.user_id is None
        if newly_bound:
            row.user_id = user_id
            row.updated_at = _now()
    member = _member(row)
    if newly_bound:
        return StaffMember(
            id=member.id,
            email=member.email,
            role=member.role,
            active=member.active,
            user_id=member.user_id,
            newly_bound=True,
        )
    return member


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
    # Before the write, not after the commit: a cached member must never
    # outlive a change this process made, even if the caller's commit races a
    # concurrent request.
    clear_staff_cache()
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
