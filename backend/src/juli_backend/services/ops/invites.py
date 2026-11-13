"""P9-B handover (D25.7) and P93 shop team: "Mời seller" → the person signs in and joins the shop.

- Staff (Vận hành+) create an invite for an e-mail: the token (only its sha256
  is stored) is valid for 7 days until that person joins. An older pending invite
  of the SAME e-mail is revoked; invites to other people stay valid (one person
  per link). An e-mail that is already a member is refused (``already_member``).
- The person opens the link on the seller app, signs in with THAT e-mail
  (verified by Supabase; compared case-insensitively) and presses "Tham gia shop".
  Joining is membership, not a one-time login: the same link opened again by that
  person still returns the shop. P93: they are ADDED to the shop team
  (``shop_members``); nobody already on it loses the shop.
  Only a shop with no member yet (a contract shop's login-less owner, or every
  member removed) still does the P9-B handover for its first person: ``user_id``
  moves to them through ``ops_transfer_shop`` (SECURITY DEFINER, juli_ops only).
  Cards, runs, rules and history key on ``shop_id`` and are untouched.
- The seller's answer to "let the team keep Vận hành access" is stored on the
  invite (``seller_kept_ops_access``) and shown in Ops. Since D25.3 was amended
  (2026-10-10) nobody acts FOR a seller: Vận hành access means the team keeps
  managing the shop's Ops settings (overrides, stage) -- never seller writes.

Every step is audited.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsShopInvite
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services import shop_team
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import is_sqlite, ops_role
from juli_backend.services.ops.mailer import InviteMail, get_mailer
from juli_backend.services.ops.overview import ShopListing, find_shop

INVITE_TTL = timedelta(days=7)
DEFAULT_ACCEPT_BASE = "https://demo.app-juli.com"
ACCEPT_PATH = "/nhan-shop"


class InviteError(ValueError):
    """The invite cannot be used; ``code`` is stable for the client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def accept_url(token: str) -> str:
    base = os.environ.get("OPS_INVITE_ACCEPT_BASE_URL", "").strip() or DEFAULT_ACCEPT_BASE
    # The e-mailed link carries the invite token (only its sha256 is stored). It
    # works for the invited e-mail for 7 days, and still opens the shop after that
    # person has pressed "Tham gia shop". It never reaches an API URL: the seller
    # app posts it in a JSON body.
    return f"{base.rstrip('/')}{ACCEPT_PATH}#{token}"


def _clean_email(raw: Any) -> str:
    if not isinstance(raw, str):
        raise InviteError("invalid_email", "email is required")
    email = raw.strip().lower()
    local, _, domain = email.partition("@")
    if not local or "." not in domain or len(email) > 320:
        raise InviteError("invalid_email", "invalid e-mail")
    return email


def invite_json(row: OpsShopInvite) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "shop_id": str(row.shop_id),
        "email": row.email,
        "keep_ops_access": row.keep_ops_access,
        "expires_at": row.expires_at.isoformat(),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "seller_kept_ops_access": row.seller_kept_ops_access,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


@dataclass(frozen=True)
class CreatedInvite:
    invite: OpsShopInvite
    email_sent: bool
    #: Only when the e-mail could not be sent: staff forward it themselves.
    accept_url: str | None


async def list_invites(session: AsyncSession, shop_id: uuid.UUID) -> list[OpsShopInvite]:
    async with ops_role(session):
        return list(
            (
                await session.execute(
                    select(OpsShopInvite)
                    .where(OpsShopInvite.shop_id == shop_id)
                    .order_by(OpsShopInvite.created_at.desc())
                )
            )
            .scalars()
            .all()
        )


async def create_invite(
    session: AsyncSession,
    actor: audit.Actor,
    shop: ShopListing,
    *,
    email: Any,
    keep_ops_access: bool,
    now: datetime | None = None,
) -> CreatedInvite:
    address = _clean_email(email)
    moment = now or utc_now_naive()
    token = secrets.token_urlsafe(32)
    if await shop_team.is_active_member_email(session, shop, address):
        raise InviteError("already_member", "this e-mail is already a member of the shop")
    async with ops_role(session):
        await session.execute(
            update(OpsShopInvite)
            .where(
                OpsShopInvite.shop_id == shop.shop_id,
                OpsShopInvite.email == address,
                OpsShopInvite.accepted_at.is_(None),
                OpsShopInvite.revoked_at.is_(None),
            )
            .values(revoked_at=moment)
        )
        row = OpsShopInvite(
            id=uuid.uuid4(),
            shop_id=shop.shop_id,
            email=address,
            token_hash=hash_token(token),
            expires_at=moment + INVITE_TTL,
            keep_ops_access=keep_ops_access,
            created_by=actor.staff_id,
            created_at=moment,
        )
        session.add(row)
    await audit.record(
        session,
        actor,
        "invite_create",
        shop_id=shop.shop_id,
        after={"email": address, "keep_ops_access": keep_ops_access},
    )
    link = accept_url(token)
    sent = await get_mailer().send_invite(
        InviteMail(
            to=address, shop_name=shop.shop_name, accept_url=link, keep_ops_access=keep_ops_access
        )
    )
    return CreatedInvite(invite=row, email_sent=sent, accept_url=None if sent else link)


def _email_matches(row: OpsShopInvite, user: User) -> bool:
    return (user.email or "").strip().lower() == row.email


def _joined_by(row: OpsShopInvite, user: User) -> bool:
    """This person already pressed "Tham gia shop" on this link."""
    return (
        row.accepted_at is not None
        and row.accepted_user_id == user.id
        and _email_matches(row, user)
    )


async def _usable(session: AsyncSession, token: str, user: User, now: datetime) -> OpsShopInvite:
    if not isinstance(token, str) or len(token) < 20:
        raise InviteError("invalid_token", "invalid invite")
    async with ops_role(session):
        row = (
            (
                await session.execute(
                    select(OpsShopInvite).where(OpsShopInvite.token_hash == hash_token(token))
                )
            )
            .scalars()
            .first()
        )
    if row is None or row.revoked_at is not None:
        raise InviteError("invalid_token", "invalid invite")
    if not _email_matches(row, user):
        raise InviteError("wrong_account", "sign in with the invited e-mail")
    # The member who joined can open the link again. Expiry and "already used"
    # apply only before that person has joined.
    if _joined_by(row, user):
        return row
    if row.accepted_at is not None:
        raise InviteError("already_accepted", "this invite was already used")
    if row.expires_at <= now:
        raise InviteError("expired", "this invite has expired")
    return row


async def preview_invite(
    session: AsyncSession, token: str, user: User, *, now: datetime | None = None
) -> dict[str, Any]:
    row = await _usable(session, token, user, now or utc_now_naive())
    shop = await find_shop(session, row.shop_id)
    return {
        "shop_name": shop.shop_name if shop else "",
        "keep_ops_access_asked": row.keep_ops_access,
        "expires_at": row.expires_at.isoformat(),
        "already_joined": _joined_by(row, user),
        "shop_id": str(row.shop_id),
    }


async def _transfer(session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    if is_sqlite(session):
        shop = await session.get(Shop, shop_id)
        if shop is None:
            raise InviteError("invalid_token", "invalid invite")
        previous = shop.user_id
        shop.user_id = user_id
        await session.flush()
        return previous
    async with ops_role(session):
        result = (
            (
                await session.execute(
                    text("SELECT * FROM public.ops_transfer_shop(:shop, :user)"),
                    {"shop": shop_id, "user": user_id},
                )
            )
            .mappings()
            .first()
        )
    if result is None:
        raise InviteError("invalid_token", "invalid invite")
    return result["out_previous_user_id"]


async def accept_invite(
    session: AsyncSession,
    token: str,
    user: User,
    *,
    keep_ops_access: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Join the shop team (P93); the first person of a shop with no member also takes it.

    Caller commits.
    """
    moment = now or utc_now_naive()
    row = await _usable(session, token, user, moment)
    if _joined_by(row, user):
        return {
            "shop_id": str(row.shop_id),
            "kept_ops_access": bool(row.seller_kept_ops_access),
            "joined_team": True,
            "took_shop": False,
            "already_joined": True,
        }
    kept = bool(keep_ops_access and row.keep_ops_access)
    listing = await find_shop(session, row.shop_id)
    if listing is None:
        raise InviteError("invalid_token", "invalid invite")
    members = await shop_team.list_members(session, listing)
    # The Juli team account that connected the shop is not a seller member.
    handover = not [m for m in members if not shop_team.is_team_email(m["email"])]
    previous_owner = listing.owner_user_id
    if handover:
        previous_owner = await _transfer(session, row.shop_id, user.id)
        await shop_team.release_team_accounts(session, row.shop_id, now=moment)
    elif members[0]["implicit"]:
        # Give a pre-backfill owner their real row before someone else joins, so the team
        # list and a later removal do not depend on the "owner without a row" fallback.
        await shop_team.add_member(
            session,
            row.shop_id,
            listing.owner_user_id,
            listing.owner_email,
            via=shop_team.VIA_BACKFILL,
            now=moment,
        )
    await shop_team.add_member(
        session,
        row.shop_id,
        user.id,
        user.email,
        via=shop_team.VIA_INVITE,
        invite_id=row.id,
        staff_id=row.created_by,
        now=moment,
    )
    async with ops_role(session):
        row.accepted_at = moment
        row.accepted_user_id = user.id
        row.seller_kept_ops_access = kept
    actor = audit.Actor(staff_id=None, email=user.email or "seller")
    await audit.record(
        session,
        actor,
        "invite_accept",
        shop_id=row.shop_id,
        before={"owner_user_id": str(previous_owner)},
        after={
            "owner_user_id": str(user.id) if handover else str(previous_owner),
            "seller_kept_ops_access": kept,
            "handover": handover,
        },
        at=moment,
    )
    await audit.record(
        session,
        actor,
        shop_team.ACTION_MEMBER_ADD,
        shop_id=row.shop_id,
        after={"member": str(user.id), "email": (user.email or "").lower(), "via": "invite"},
        at=moment,
    )
    return {
        "shop_id": str(row.shop_id),
        "kept_ops_access": kept,
        "joined_team": True,
        "took_shop": handover,
        "already_joined": False,
    }
