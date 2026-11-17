"""Businesses and their members (P101 W1, migration 130).

Every read and write of ``businesses`` / ``business_members`` / ``business_invites`` goes through
:func:`~juli_backend.services.ops.access.ops_role`, after the caller's right is checked here from
the verified user id -- the shape ``shop_team`` and ``ops.invites`` already use. ``juli_app`` itself
may only SELECT its own member rows (what the ``shops`` policies read).

Rules:

- Owner-only: invite, remove a member. An owner cannot remove themselves (a business keeps an
  owner); removal is a soft delete (``removed_at``) and takes the shops away at once.
- Invites are e-mail bound, 7 days, one pending per (business, e-mail); the link is the same
  ``/nhan-shop#<token>`` page as the shop invite (only the token's sha256 is stored).
- A new shop joins the business the caller picked (they must be an active member), else the
  caller's only business, else a new business named after the shop with the caller as owner.

Member changes are audited in ``ops_audit_log`` (actor = the seller's e-mail).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Uuid, func, literal, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.businesses import Business, BusinessInvite, BusinessMember
from juli_backend.models.models import Shop, User
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import is_sqlite, ops_role

ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
VIA_OWNER = "owner"
VIA_INVITE = "invite"
VIA_BACKFILL = "backfill"

ACTION_BUSINESS_INVITE_CREATE = "business_invite_create"
ACTION_BUSINESS_INVITE_ACCEPT = "business_invite_accept"
ACTION_BUSINESS_MEMBER_REMOVE = "business_member_remove"

_NAME_MAX = 200


class BusinessError(ValueError):
    """The business action is refused; ``code`` is stable for the client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _actor(user: User) -> audit.Actor:
    return audit.Actor(staff_id=None, email=user.email or "seller")


def _email(user: User) -> str | None:
    return (user.email or "").strip().lower() or None


# --------------------------------------------------------------------------- membership reads


async def active_memberships(session: AsyncSession, user_id: uuid.UUID) -> list[BusinessMember]:
    """The user's active business member rows, oldest first."""
    async with ops_role(session):
        return list(
            (
                await session.execute(
                    select(BusinessMember)
                    .where(BusinessMember.user_id == user_id, BusinessMember.removed_at.is_(None))
                    .order_by(BusinessMember.added_at, BusinessMember.id)
                )
            )
            .scalars()
            .all()
        )


async def member_of(
    session: AsyncSession, business_id: uuid.UUID, user_id: uuid.UUID
) -> BusinessMember | None:
    """The user's ACTIVE row in that business, or None."""
    async with ops_role(session):
        return (
            (
                await session.execute(
                    select(BusinessMember).where(
                        BusinessMember.business_id == business_id,
                        BusinessMember.user_id == user_id,
                        BusinessMember.removed_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )


async def owns_shop(session: AsyncSession, shop: Shop, user_id: uuid.UUID) -> bool:
    """The shop's owner (``shops.user_id``) or an active ``owner`` of the shop's business: the
    people an owner-only shop action (the board reset, the outside-Juli import) is for."""
    if shop.user_id == user_id:
        return True
    if shop.business_id is None:
        return False
    row = await member_of(session, shop.business_id, user_id)
    return row is not None and row.role == ROLE_OWNER


async def in_shop_team(session: AsyncSession, shop: Shop, user_id: uuid.UUID) -> bool:
    """The shop's owner or any ACTIVE person (``owner`` or ``member``) of the shop's business: the
    people who run the shop's board -- reset it and import the cards done outside Juli (owner
    decision 2026-11-17: members may do both)."""
    if shop.user_id == user_id:
        return True
    if shop.business_id is None:
        return False
    return await member_of(session, shop.business_id, user_id) is not None


async def _require_owner(
    session: AsyncSession, business_id: uuid.UUID, user_id: uuid.UUID
) -> Business:
    row = await member_of(session, business_id, user_id)
    if row is None:
        # Not a member: the business is not named to them at all.
        raise BusinessError("not_found", "business not found")
    if row.role != ROLE_OWNER:
        raise BusinessError("not_owner", "only the business owner may do this")
    async with ops_role(session):
        business = await session.get(Business, business_id)
    if business is None:
        raise BusinessError("not_found", "business not found")
    return business


async def _members(session: AsyncSession, business_id: uuid.UUID) -> list[BusinessMember]:
    async with ops_role(session):
        return list(
            (
                await session.execute(
                    select(BusinessMember)
                    .where(
                        BusinessMember.business_id == business_id,
                        BusinessMember.removed_at.is_(None),
                    )
                    .order_by(BusinessMember.added_at, BusinessMember.id)
                )
            )
            .scalars()
            .all()
        )


def _member_json(row: BusinessMember) -> dict[str, Any]:
    return {
        "user_id": str(row.user_id),
        "email": row.email,
        "role": row.role,
        "added_at": row.added_at.isoformat() if row.added_at else None,
    }


# --------------------------------------------------------------------------- GET /v1/businesses


async def list_for_user(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """The caller's businesses with the shops they may open (id, name, platform, kind).

    The shops come from THE access rule (``list_for_authorization``), grouped by business, so the
    switcher never offers a shop ``get_active_shop`` would refuse. A business the caller belongs to
    with no shop yet is listed empty. A shop reached only through a ``shop_members`` row shows under
    its business with ``role`` None. A shop with no business yet (pre-backfill) is its own entry
    with ``id`` None. Owners also get the member list.
    """
    from juli_backend.repositories.identity import ShopsRepo

    shops = await ShopsRepo(session).list_for_authorization(user.id)
    shops.sort(key=lambda s: (s.created_at, str(s.id)))
    roles = {m.business_id: m.role for m in await active_memberships(session, user.id)}
    ids = set(roles) | {s.business_id for s in shops if s.business_id is not None}
    names: dict[uuid.UUID, Business] = {}
    if ids:
        async with ops_role(session):
            found = (await session.execute(select(Business).where(Business.id.in_(ids)))).scalars()
            names = {b.id: b for b in found}
    by_business: dict[uuid.UUID, list[Shop]] = {}
    out: list[dict[str, Any]] = []
    for shop in shops:
        if shop.business_id is None:
            out.append(
                {
                    "id": None,
                    "name": shop.shop_name,
                    "role": ROLE_OWNER if shop.user_id == user.id else None,
                    "shops": [_shop_json(shop)],
                    "created_at": None,
                }
            )
        else:
            by_business.setdefault(shop.business_id, []).append(shop)
    for business_id in ids:
        business = names.get(business_id)
        if business is None:
            continue
        role = roles.get(business_id)
        entry: dict[str, Any] = {
            "id": str(business_id),
            "name": business.name,
            "role": role,
            "shops": [_shop_json(s) for s in by_business.get(business_id, [])],
            "created_at": business.created_at.isoformat() if business.created_at else None,
        }
        if role == ROLE_OWNER:
            entry["members"] = [_member_json(m) for m in await _members(session, business_id)]
        out.append(entry)
    out.sort(key=lambda e: (e["created_at"] or "", e["name"]))
    return out


def _shop_json(shop: Shop) -> dict[str, Any]:
    return {
        "id": str(shop.id),
        "name": shop.shop_name,
        "platform": shop.platform or "tiktok",
        "kind": shop.kind or "real",
    }


# --------------------------------------------------------------------------- connect


async def _create_business(
    session: AsyncSession, name: str, owner_id: uuid.UUID, owner_email: str | None, now: datetime
) -> uuid.UUID:
    business_id = uuid.uuid4()
    async with ops_role(session):
        session.add(Business(id=business_id, name=(name.strip() or "Shop")[:_NAME_MAX]))
        await session.flush()
        session.add(
            BusinessMember(
                id=uuid.uuid4(),
                business_id=business_id,
                user_id=owner_id,
                role=ROLE_OWNER,
                email=owner_email,
                added_at=now,
                added_via=VIA_OWNER,
            )
        )
    return business_id


async def business_for_new_shop(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_email: str | None,
    shop_name: str,
    requested: uuid.UUID | None,
    now: datetime | None = None,
) -> uuid.UUID:
    """The business a shop the caller connects joins (contract §2.1).

    ``requested`` (the switcher's business): the caller must be an active member, else
    ``BusinessError("not_found")``. None: the caller's only business; with none (a first-time user)
    or several (no choice made), a new business named after the shop, owned by the caller.
    """
    chosen = await chosen_business(session, user_id=user_id, requested=requested)
    if chosen is not None:
        return chosen
    email = (user_email or "").strip().lower() or None
    return await _create_business(session, shop_name, user_id, email, now or utc_now_naive())


async def chosen_business(
    session: AsyncSession, *, user_id: uuid.UUID, requested: uuid.UUID | None
) -> uuid.UUID | None:
    """The requested business (caller must be an active member) or the caller's only one; None:
    no choice -- the new shop gets a business of its own (``_create_business``, or the
    ``shops_default_business`` trigger for a path that inserts with no business)."""
    if requested is not None:
        if await member_of(session, requested, user_id) is None:
            raise BusinessError("not_found", "business not found")
        return requested
    rows = await active_memberships(session, user_id)
    return rows[0].business_id if len(rows) == 1 else None


# --------------------------------------------------------------------------- invites


@dataclass(frozen=True)
class CreatedBusinessInvite:
    invite: BusinessInvite
    email_sent: bool
    #: Only when the e-mail could not be sent: the owner forwards the link themselves.
    accept_url: str | None


def _invite_body(business_name: str, inviter: str, link: str) -> str:
    return (
        f"Chào bạn,\n\n{inviter} mời bạn tham gia doanh nghiệp “{business_name}” trên Juli.\n\n"
        f"Tham gia: {link}\n\n"
        "Đăng nhập bằng đúng địa chỉ email này. Liên kết hết hạn sau 7 ngày.\n\n— Juli"
    )


async def create_invite(
    session: AsyncSession,
    business_id: uuid.UUID,
    inviter: User,
    *,
    email: Any,
    now: datetime | None = None,
) -> CreatedBusinessInvite:
    """Owner only. An older pending invite of the same e-mail is revoked; a member is refused."""
    from juli_backend.services.ops import invites as ops_invites
    from juli_backend.services.ops.mailer import get_mailer

    business = await _require_owner(session, business_id, inviter.id)
    try:
        address = ops_invites.clean_email(email)
    except ops_invites.InviteError as exc:
        raise BusinessError(exc.code, str(exc)) from None
    moment = now or utc_now_naive()
    if any((m.email or "").lower() == address for m in await _members(session, business_id)):
        raise BusinessError("already_member", "this e-mail is already a member")
    token = secrets.token_urlsafe(32)
    async with ops_role(session):
        await session.execute(
            update(BusinessInvite)
            .where(
                BusinessInvite.business_id == business_id,
                BusinessInvite.email == address,
                BusinessInvite.accepted_at.is_(None),
                BusinessInvite.revoked_at.is_(None),
            )
            .values(revoked_at=moment)
        )
        row = BusinessInvite(
            id=uuid.uuid4(),
            business_id=business_id,
            email=address,
            token_hash=ops_invites.hash_token(token),
            created_by=inviter.id,
            created_at=moment,
            expires_at=moment + ops_invites.INVITE_TTL,
        )
        session.add(row)
    await audit.record(
        session,
        _actor(inviter),
        ACTION_BUSINESS_INVITE_CREATE,
        after={"business_id": str(business_id), "email": address},
        at=moment,
    )
    link = ops_invites.accept_url(token)
    sent = await get_mailer().send_notice(
        to=address,
        subject=f"Tham gia {business.name} trên Juli",
        body=_invite_body(business.name, inviter.email or "Chủ doanh nghiệp", link),
    )
    return CreatedBusinessInvite(invite=row, email_sent=sent, accept_url=None if sent else link)


async def find_invite(session: AsyncSession, token: str) -> BusinessInvite | None:
    """The business invite this token names (None: not a business invite)."""
    from juli_backend.services.ops.invites import hash_token

    if not isinstance(token, str) or len(token) < 20:
        return None
    async with ops_role(session):
        return (
            (
                await session.execute(
                    select(BusinessInvite).where(BusinessInvite.token_hash == hash_token(token))
                )
            )
            .scalars()
            .first()
        )


def _joined_by(row: BusinessInvite, user: User) -> bool:
    return row.accepted_at is not None and row.accepted_user_id == user.id


def _usable(row: BusinessInvite | None, user: User, now: datetime) -> BusinessInvite:
    if row is None or row.revoked_at is not None:
        raise BusinessError("invalid_token", "invalid invite")
    if _email(user) != row.email:
        raise BusinessError("wrong_account", "sign in with the invited e-mail")
    if _joined_by(row, user):
        return row
    if row.accepted_at is not None:
        raise BusinessError("already_accepted", "this invite was already used")
    if row.expires_at <= now:
        raise BusinessError("expired", "this invite has expired")
    return row


def shop_business_id_expr(session: AsyncSession, shop_id: uuid.UUID) -> ColumnElement[Any]:
    """The shop's business id as an SQL expression, to fold into the read that needs it.

    Postgres: ``public.ops_shop_business`` (``juli_ops`` holds no grant on ``shops``; the caller
    runs the statement inside :func:`ops_role`). SQLite (unit tests): a subquery on the column.
    One statement instead of a lookup and then the read (the Ops round-trip budget).
    """
    if is_sqlite(session):
        return select(Shop.business_id).where(Shop.id == shop_id).scalar_subquery()
    return func.public.ops_shop_business(literal(shop_id, Uuid()), type_=Uuid())


async def _shop_business_id(session: AsyncSession, shop_id: uuid.UUID) -> uuid.UUID | None:
    """The shop's business, read as ``juli_ops``.

    ``juli_ops`` holds no grant on ``shops``: Ops reads shops only through reviewed SECURITY
    DEFINER functions (migrations 083 / 110 / 130). SQLite (unit tests) reads the column.
    """
    if is_sqlite(session):
        return (
            await session.execute(select(Shop.business_id).where(Shop.id == shop_id))
        ).scalar_one_or_none()
    async with ops_role(session):
        value = (
            await session.execute(text("SELECT public.ops_shop_business(:shop)"), {"shop": shop_id})
        ).scalar_one_or_none()
    return value if isinstance(value, uuid.UUID) or value is None else uuid.UUID(str(value))


async def _first_shop_id(session: AsyncSession, business_id: uuid.UUID) -> uuid.UUID | None:
    """The business's oldest shop (where an accepted invite lands), as ``juli_ops``."""
    if is_sqlite(session):
        return (
            await session.execute(
                select(Shop.id)
                .where(Shop.business_id == business_id)
                .order_by(Shop.created_at, Shop.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    async with ops_role(session):
        value = (
            await session.execute(
                text("SELECT public.ops_business_first_shop(:business)"),
                {"business": business_id},
            )
        ).scalar_one_or_none()
    return value if isinstance(value, uuid.UUID) or value is None else uuid.UUID(str(value))


async def preview_invite(
    session: AsyncSession, row: BusinessInvite | None, user: User, *, now: datetime | None = None
) -> dict[str, Any]:
    """The shape of the shop invite's preview, so ``/nhan-shop`` reads both."""
    invite = _usable(row, user, now or utc_now_naive())
    async with ops_role(session):
        business = await session.get(Business, invite.business_id)
    shop_id = await _first_shop_id(session, invite.business_id)
    return {
        "shop_name": business.name if business else "",
        "keep_ops_access_asked": False,
        "expires_at": invite.expires_at.isoformat(),
        "already_joined": _joined_by(invite, user),
        "shop_id": str(shop_id) if shop_id else None,
        "business_id": str(invite.business_id),
    }


async def accept_invite(
    session: AsyncSession, row: BusinessInvite | None, user: User, *, now: datetime | None = None
) -> dict[str, Any]:
    """Join the business as a member (idempotent for the person who joined). Caller commits."""
    moment = now or utc_now_naive()
    invite = _usable(row, user, moment)
    shop_id = await _first_shop_id(session, invite.business_id)
    result = {
        "shop_id": str(shop_id) if shop_id else None,
        "business_id": str(invite.business_id),
        "kept_ops_access": False,
        "joined_team": True,
        "took_shop": False,
        "already_joined": _joined_by(invite, user),
    }
    if result["already_joined"]:
        return result
    if await member_of(session, invite.business_id, user.id) is None:
        async with ops_role(session):
            session.add(
                BusinessMember(
                    id=uuid.uuid4(),
                    business_id=invite.business_id,
                    user_id=user.id,
                    role=ROLE_MEMBER,
                    email=_email(user),
                    added_at=moment,
                    added_via=VIA_INVITE,
                    invite_id=invite.id,
                )
            )
    async with ops_role(session):
        invite.accepted_at = moment
        invite.accepted_user_id = user.id
    await audit.record(
        session,
        _actor(user),
        ACTION_BUSINESS_INVITE_ACCEPT,
        after={
            "business_id": str(invite.business_id),
            "member": str(user.id),
            "email": _email(user),
            "via": VIA_INVITE,
        },
        at=moment,
    )
    return result


# --------------------------------------------------------------------------- removal


async def remove_member(
    session: AsyncSession,
    business_id: uuid.UUID,
    owner: User,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Owner only; soft delete. The owner cannot remove themselves."""
    await _require_owner(session, business_id, owner.id)
    if user_id == owner.id:
        raise BusinessError("cannot_remove_self", "the owner cannot remove themselves")
    target = await member_of(session, business_id, user_id)
    if target is None:
        raise BusinessError("not_a_member", "this person is not a member of the business")
    moment = now or utc_now_naive()
    async with ops_role(session):
        target.removed_at = moment
    await audit.record(
        session,
        _actor(owner),
        ACTION_BUSINESS_MEMBER_REMOVE,
        before={"business_id": str(business_id), "member": str(user_id), "email": target.email},
        after=None,
        at=moment,
    )
    return {"user_id": str(user_id), "email": target.email}


async def members_of_shop_business(
    session: AsyncSession, shop_id: uuid.UUID
) -> list[BusinessMember]:
    """The active members of the shop's business (empty for a shop with no business yet).

    One statement: the shop's business is looked up inside the read.
    """
    async with ops_role(session):
        return list(
            (
                await session.execute(
                    select(BusinessMember)
                    .where(
                        BusinessMember.business_id == shop_business_id_expr(session, shop_id),
                        BusinessMember.removed_at.is_(None),
                    )
                    .order_by(BusinessMember.added_at, BusinessMember.id)
                )
            )
            .scalars()
            .all()
        )


async def remove_person_from_shop_business(
    session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime
) -> bool:
    """Ops removed a person from a shop (P93): their membership of its business goes too.

    Without this a business member would keep the shop through the business branch of the access
    rule. True when a row was removed. Ops access itself is unchanged.
    """
    business_id = await _shop_business_id(session, shop_id)
    if business_id is None:
        return False
    row = await member_of(session, business_id, user_id)
    if row is None:
        return False
    async with ops_role(session):
        row.removed_at = now
    return True


async def transfer_shop_business_owner(
    session: AsyncSession,
    shop_id: uuid.UUID,
    new_owner: User,
    *,
    release: list[uuid.UUID],
    now: datetime,
) -> None:
    """The P9-B handover of an Ops invite: the new person owns the shop's business.

    ``release`` are the accounts that lose the business with the handover (the Juli team account
    that connected it, a login-less contract owner). A no-op for a shop with no business yet.
    """
    business_id = await _shop_business_id(session, shop_id)
    if business_id is None:
        return
    for previous in release:
        if previous == new_owner.id:
            continue
        row = await member_of(session, business_id, previous)
        if row is not None:
            async with ops_role(session):
                row.removed_at = now
    current = await member_of(session, business_id, new_owner.id)
    async with ops_role(session):
        if current is None:
            session.add(
                BusinessMember(
                    id=uuid.uuid4(),
                    business_id=business_id,
                    user_id=new_owner.id,
                    role=ROLE_OWNER,
                    email=_email(new_owner),
                    added_at=now,
                    added_via=VIA_INVITE,
                )
            )
        elif current.role != ROLE_OWNER:
            current.role = ROLE_OWNER
