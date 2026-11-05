"""P93 shop team: who may act on a shop, and Ops' add / remove of members.

ACCESS RULE (one place; the ``shops`` RLS policies of migration 121 say the same in SQL).
A user may act on a shop iff they are an ACTIVE member (``shop_members.removed_at`` NULL), or they
are ``shops.user_id`` and have no ``shop_members`` row of their own on it ("owner without a row": a
shop made before the backfill ran). A removed member keeps a row, so they are never re-admitted by
the second branch: removal is immediate. ``shops.user_id`` itself is kept as the shop's primary
contact (Ops and the workers scope by it); nothing about it grants access to a removed member.

All members have the same role. Only Ops (Vận hành+) adds (by invite, ``invites.accept_invite``) and
removes (:func:`remove_member`); there is no seller endpoint for either. Nothing commits here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop, ShopMember
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


def shops_of_user_clause(user_id: uuid.UUID) -> Any:
    """``WHERE`` clause on ``Shop``: the shops ``user_id`` may act on."""
    own_row = exists().where(ShopMember.shop_id == Shop.id, ShopMember.user_id == user_id)
    active = exists().where(
        ShopMember.shop_id == Shop.id,
        ShopMember.user_id == user_id,
        ShopMember.removed_at.is_(None),
    )
    return or_(active, and_(Shop.user_id == user_id, ~own_row))


async def is_member(session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Whether ``user_id`` may act on ``shop_id`` (the access rule in the module docstring)."""
    found = (
        await session.execute(
            select(Shop.id).where(Shop.id == shop_id, shops_of_user_clause(user_id))
        )
    ).first()
    return found is not None


def member_json(row: ShopMember) -> dict[str, Any]:
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


def _implicit_owner(listing: ShopListing, rows: list[ShopMember]) -> dict[str, Any] | None:
    """The owner of a shop that has no row of its own for them yet (pre-backfill), if a person."""
    if listing.owner_email is None:
        return None  # a login-less contract-shop owner: nobody signs in as them
    if any(r.user_id == listing.owner_user_id for r in rows):
        return None
    return {
        "user_id": str(listing.owner_user_id),
        "email": listing.owner_email.lower(),
        "added_at": None,
        "added_via": VIA_OWNER,
        "implicit": True,
    }


async def list_members(session: AsyncSession, listing: ShopListing) -> list[dict[str, Any]]:
    """The shop's active members (Ops view), the pre-backfill owner included."""
    rows = await _rows(session, listing.shop_id)
    members = [member_json(r) for r in rows if r.removed_at is None]
    implicit = _implicit_owner(listing, rows)
    if implicit is not None:
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
    email: str | None
    if target is not None:
        async with ops_role(session):
            target.removed_at = now
            target.removed_by_staff = actor.staff_id
        email = target.email
    else:
        implicit = _implicit_owner(listing, rows)
        if implicit is None or implicit["user_id"] != str(user_id):
            raise MemberError("not_a_member", "this person is not a member of the shop")
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
