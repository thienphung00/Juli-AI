"""P93 shop team: who may act on a shop, and Ops' add / remove of members.

ACCESS RULE (one place: ``repositories.identity.shops_of_user_clause``; the ``shops`` RLS policies
of migration 130 say the same in SQL). P101 W1: a user may act on a shop iff they are an ACTIVE
member of the shop's BUSINESS (``business_members``), or an ACTIVE ``shop_members`` row of that
shop (staff of one shop). P93's "owner without a row" stays only for ``shops.user_id`` with NO row
of their own at all (none in ``shop_members`` for the shop, none in ``business_members`` for its
business): pre-backfill shops. A removed member keeps a row, so they are never re-admitted: removal
is immediate. ``shops.user_id`` is kept as the shop's primary contact (Ops and the workers scope by
it); once its person has any row it is no access rule by itself.

All members have the same role. Only Ops (Vận hành+) adds (by invite, ``invites.accept_invite``) and
removes (:func:`remove_member`); there is no seller endpoint for either. Nothing commits here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, cast, literal_column, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.businesses import BusinessMember
from juli_backend.models.models import Shop, ShopMember
from juli_backend.repositories.identity import shops_of_user_clause
from juli_backend.services import businesses
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import ops_role
from juli_backend.services.ops.overview import ShopListing

VIA_OWNER = "owner"
VIA_INVITE = "invite"
VIA_BACKFILL = "backfill"

#: Accounts of the Juli team that connect a shop before its seller exists (``ops.py``'s
#: ``owned_by_team``). They are not seller members: the first invite hands the shop over.
TEAM_EMAIL_SUFFIX = "@app-juli.com"

ACTION_MEMBER_ADD = "member_add"
ACTION_MEMBER_REMOVE = "member_remove"


class MemberError(ValueError):
    """The member cannot be removed; ``code`` is stable for the client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_team_email(email: str | None) -> bool:
    return (email or "").strip().lower().endswith(TEAM_EMAIL_SUFFIX)


async def is_member(session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether ``user_id`` may act on ``shop_id`` (the access rule in the module docstring)."""
    found = (
        await session.execute(
            select(Shop.id).where(Shop.id == shop_id, shops_of_user_clause(user_id))
        )
    ).first()
    return found is not None


def _uuid(value: Any) -> uuid.UUID:
    """A raw union column: SQLite hands back the uuid's text."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def member_json(row: Any) -> dict[str, Any]:
    """A ``shop_members`` row (the ORM object, or a row of :func:`list_members`' read)."""
    return {
        "user_id": str(row.user_id),
        "email": row.email,
        "added_at": row.added_at.isoformat() if row.added_at else None,
        "added_via": row.added_via,
        "implicit": False,
    }


async def _rows(session: AsyncSession, shop_id: uuid.UUID) -> list[ShopMember]:
    async with ops_role(session):
        return list(
            (
                await session.execute(
                    select(ShopMember)
                    .where(ShopMember.shop_id == shop_id)
                    .order_by(ShopMember.added_at, ShopMember.id)
                )
            )
            .scalars()
            .all()
        )


def _implicit_owner(listing: ShopListing, row_user_ids: set[uuid.UUID]) -> dict[str, Any] | None:
    """The owner of a shop that has no row of its own for them yet (pre-backfill), if a person.

    ``row_user_ids``: every ``shop_members`` row of the shop, removed ones included.
    """
    if listing.owner_email is None:
        return None  # a login-less contract-shop owner: nobody signs in as them
    if listing.owner_user_id in row_user_ids:
        return None
    return {
        "user_id": str(listing.owner_user_id),
        "email": listing.owner_email.lower(),
        "added_at": None,
        "added_via": VIA_OWNER,
        "implicit": True,
    }


async def list_members(session: AsyncSession, listing: ShopListing) -> list[dict[str, Any]]:
    """The shop's active members (Ops view): shop rows, then the business's people (P101 W1).

    The pre-backfill owner is included. A business member with no e-mail (a login-less contract
    owner) is not listed: nobody signs in as them. ONE statement for both tables (the Ops
    settings round-trip budget, ``tests/integration/test_ops_round_trips.py``).
    """
    shop_rows: Select[Any] = select(
        literal_column("0").label("src"),
        ShopMember.id,
        ShopMember.user_id,
        ShopMember.email,
        ShopMember.added_at,
        ShopMember.added_via,
        ShopMember.removed_at,
        cast(null(), String(16)).label("role"),
    ).where(ShopMember.shop_id == listing.shop_id)
    business_rows: Select[Any] = select(
        literal_column("1").label("src"),
        BusinessMember.id,
        BusinessMember.user_id,
        BusinessMember.email,
        BusinessMember.added_at,
        BusinessMember.added_via,
        BusinessMember.removed_at,
        BusinessMember.role,
    ).where(
        BusinessMember.business_id == businesses.shop_business_id_expr(session, listing.shop_id),
        BusinessMember.removed_at.is_(None),
    )
    team = union_all(shop_rows, business_rows).subquery()
    async with ops_role(session):
        rows = (
            await session.execute(select(team).order_by(team.c.src, team.c.added_at, team.c.id))
        ).all()
    shop_part = [r for r in rows if r.src == 0]
    members = [member_json(r) for r in shop_part if r.removed_at is None]
    seen = {m["user_id"] for m in members}
    for person in (r for r in rows if r.src == 1):
        if person.email is None or str(person.user_id) in seen:
            continue
        seen.add(str(person.user_id))
        members.append(
            {
                "user_id": str(person.user_id),
                "email": person.email,
                "added_at": person.added_at.isoformat() if person.added_at else None,
                "added_via": person.added_via,
                "implicit": False,
                "business_role": person.role,
            }
        )
    implicit = _implicit_owner(listing, {_uuid(r.user_id) for r in shop_part})
    if implicit is not None and implicit["user_id"] not in seen:
        members.insert(0, implicit)
    return members


async def release_team_accounts(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> None:
    """After a handover: the team account that connected the shop is no longer a member."""
    for row in await _rows(session, shop_id):
        if row.removed_at is None and is_team_email(row.email):
            async with ops_role(session):
                row.removed_at = now


async def is_active_member_email(session: AsyncSession, listing: ShopListing, email: str) -> bool:
    wanted = email.strip().lower()
    return any((m["email"] or "").lower() == wanted for m in await list_members(session, listing))


async def add_member(
    session: AsyncSession,
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    email: str | None,
    *,
    via: str,
    invite_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    now: datetime,
) -> ShopMember:
    """Make ``user_id`` an active member (idempotent: an existing active row is returned)."""
    async with ops_role(session):
        existing = (
            (
                await session.execute(
                    select(ShopMember).where(
                        ShopMember.shop_id == shop_id,
                        ShopMember.user_id == user_id,
                        ShopMember.removed_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return existing
        row = ShopMember(
            id=uuid.uuid4(),
            shop_id=shop_id,
            user_id=user_id,
            email=(email or "").strip().lower() or None,
            added_at=now,
            added_via=via,
            added_by_staff=staff_id,
            invite_id=invite_id,
        )
        session.add(row)
    return row


@dataclass(frozen=True)
class Removed:
    user_id: uuid.UUID
    email: str | None


async def remove_member(
    session: AsyncSession,
    actor: audit.Actor,
    listing: ShopListing,
    user_id: uuid.UUID,
    *,
    now: datetime,
) -> Removed:
    """Soft-delete one member (Ops only); audited. The shop and its data stay untouched.

    Removing the last member is allowed. An owner who has no row yet gets one written already
    removed, so the removal holds against the "owner without a row" branch too.
    """
    rows = await _rows(session, listing.shop_id)
    target = next((r for r in rows if r.user_id == user_id and r.removed_at is None), None)
    business_people = await businesses.members_of_shop_business(session, listing.shop_id)
    in_business = next((p for p in business_people if p.user_id == user_id), None)
    implicit = _implicit_owner(listing, {r.user_id for r in rows})
    is_implicit = implicit is not None and implicit["user_id"] == str(user_id)
    if target is None and in_business is None and not is_implicit:
        raise MemberError("not_a_member", "this person is not a member of the shop")
    # P101 W1: a business member keeps the shop through the business; Ops' removal takes that too.
    await businesses.remove_person_from_shop_business(session, listing.shop_id, user_id, now=now)
    email: str | None
    if target is not None:
        async with ops_role(session):
            target.removed_at = now
            target.removed_by_staff = actor.staff_id
        email = target.email
    elif implicit is None or not is_implicit:
        email = in_business.email if in_business is not None else None
    else:
        email = implicit["email"]
        async with ops_role(session):
            session.add(
                ShopMember(
                    id=uuid.uuid4(),
                    shop_id=listing.shop_id,
                    user_id=user_id,
                    email=email,
                    added_at=now,
                    added_via=VIA_OWNER,
                    removed_at=now,
                    removed_by_staff=actor.staff_id,
                )
            )
    await audit.record(
        session,
        actor,
        ACTION_MEMBER_REMOVE,
        shop_id=listing.shop_id,
        before={"member": str(user_id), "email": email},
        after=None,
        at=now,
    )
    return Removed(user_id=user_id, email=email)
