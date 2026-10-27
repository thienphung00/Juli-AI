"""The reviewer's identity, loaded once per cold burst in as few round trips as possible (P69b).

Production pays ~197 ms per round trip (VPS Singapore -> Supabase us-west). After P69 a
WARM reviewer request was 3-6 round trips, but the COLD path (identity caches expired
after 30 s idle) was 17 for ``GET /v1/reviewer/me``, and the demo page fires 4-7 requests
at once: each one missed the cache and ran the full cold path itself (6-7 s each, measured
live 2026-10-26, contending for the 5 + 5 pool). Two fixes, both here:

**Single flight** (``core.security.SingleFlight``). Concurrent cold requests for the same
``(verified sub, pinned shop id)`` share ONE load: the first does the database work on its
own session, the others await its plain snapshots and do none. Tenant-safe because the
key is the verified JWT ``sub`` (plus the configured pin): two reviewers never share a
flight, and every value is checked against its own key again before use. A loader error
reaches every waiter and is not kept; the next request loads again.

**Fused statements** (Postgres). The cold load was: ops role switch, account read, role
restore, COMMIT, BEGIN, user GUC, users read, COMMIT, BEGIN, ops role switch, ops shop
read (+ GUCs), ``shops`` row, sandbox owners, the shop's credential capabilities, its
``production_write_shops`` row. It is now three statements inside the request's own
transaction:

1. ``ops_role`` switch to ``juli_ops`` (unchanged; it learns the role to come back to);
2. the account row, and in the SAME statement the role restore and the tenant GUCs for
   the reads below -- ``app.current_user_id`` = the verified ``sub`` (the reviewer's own
   ``users`` row) and ``app.current_shop_id`` = the configured pin (the pinned shop's
   rows). RLS still does every narrowing: ``users_select_public`` shows only the ``sub``'s
   row, ``shops_shop_scope_select`` / the credential and ``production_write_shops``
   policies only the pin's rows; the sandbox owner comes from the reviewed SECURITY
   DEFINER ``enumerate_sandbox_write_credentials()`` as before;
3. the ``users`` row, the ``shops`` row, the pin's capabilities, its
   ``production_write_shops`` flag and the newest sandbox owner, in one statement.

No COMMIT: nothing was written. The route's shop entry (``api/reviewer``) then sets the
shop's tenant scope (shop + owner GUCs) exactly as on a warm request; until then the
transaction can see only the reviewer's own ``users`` row and the pinned shop it is
entitled to. Writes are never cached or skipped: a missing ``users`` row or one this
token backfills goes through ``load_authenticated_user`` (``core/security``); the
once-per-session sign-in claim and every audit stay in ``api/reviewer.reviewer_gate``.

SQLite (unit tests) has no roles or GUCs: the same pieces are read with plain statements.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Uuid, column, exists, func, literal, select, true
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import (
    SandboxWriteOwner,
    SingleFlight,
    cached_reviewer_user,
    remember_reviewer_user,
)
from juli_backend.models.models import ProductionWriteShop, Shop, TikTokCredential, User
from juli_backend.models.ops import OpsReviewerAccount
from juli_backend.services.ops.access import ops_role
from juli_backend.services.reviewer import accounts, pin_cache, sandbox
from juli_backend.services.reviewer.accounts import ReviewerAccount
from juli_backend.services.reviewer.pin_cache import PinnedShop

_SHOP_GUC = "app.current_shop_id"
_USER_GUC = "app.current_user_id"


@dataclass(frozen=True)
class ReviewerIdentity:
    """Plain snapshots of one reviewer's identity facts (never an ORM instance).

    ``user_values`` is None when the ``users`` row was not read (account refused) or does
    not exist yet; ``pinned`` is None with no pin, when the account is refused, or when the
    pinned shop does not exist (the shop entry then refuses with 503).
    """

    account: ReviewerAccount | None
    user_values: dict[str, Any] | None = None
    pinned: PinnedShop | None = None


_FlightKey = tuple[uuid.UUID, uuid.UUID | None]
_flight: SingleFlight[_FlightKey, ReviewerIdentity] = SingleFlight()


async def load_identity(
    session: AsyncSession, user_id: uuid.UUID, pin_shop_id: uuid.UUID | None
) -> ReviewerIdentity:
    """This verified ``sub``'s account, ``users`` row and pinned shop: cached, else loaded once.

    Concurrent misses for the same ``(user_id, pin_shop_id)`` share one load (the first
    caller's session does it); see the module docstring.
    """
    hit = _from_caches(user_id, pin_shop_id)
    if hit is not None:
        return hit
    loaded = await _flight.run((user_id, pin_shop_id), lambda: _load(session, user_id, pin_shop_id))
    return _checked(loaded, user_id, pin_shop_id)


def _active(account: ReviewerAccount | None) -> bool:
    return account is not None and account.status() == accounts.STATUS_ACTIVE


def _from_caches(user_id: uuid.UUID, pin_shop_id: uuid.UUID | None) -> ReviewerIdentity | None:
    hit = accounts.cached_account(user_id)
    if hit is None:
        return None
    account = hit[0]
    if not _active(account):
        return ReviewerIdentity(account)  # the gate refuses it; nothing else is needed
    user_values = cached_reviewer_user(user_id)
    pinned = pin_cache.cached(pin_shop_id) if pin_shop_id is not None else None
    if user_values is None or (pin_shop_id is not None and pinned is None):
        return None
    return ReviewerIdentity(account, user_values, pinned)


def _checked(
    identity: ReviewerIdentity, user_id: uuid.UUID, pin_shop_id: uuid.UUID | None
) -> ReviewerIdentity:
    """Defence in depth: every piece must describe THIS key, or it is dropped (fail closed)."""
    account = identity.account
    if account is not None and account.user_id != user_id:
        return ReviewerIdentity(None)
    user_values = identity.user_values
    if user_values is not None and user_values.get("id") != user_id:
        user_values = None
    pinned = identity.pinned
    if pinned is not None and pinned.shop_id != pin_shop_id:
        pinned = None
    return ReviewerIdentity(account, user_values, pinned)


async def _load(
    session: AsyncSession, user_id: uuid.UUID, pin_shop_id: uuid.UUID | None
) -> ReviewerIdentity:
    postgres = session.get_bind().dialect.name == "postgresql"
    hit = accounts.cached_account(user_id)
    scoped = False
    if hit is not None:
        account = hit[0]
    elif postgres:
        account, scoped = await _read_account_setting_scope(session, user_id, pin_shop_id)
        accounts.remember(user_id, account)
    else:
        account = await accounts.read_account(session, user_id)
        accounts.remember(user_id, account)
    if not _active(account):
        return ReviewerIdentity(account)

    user_values = cached_reviewer_user(user_id)
    pinned = pin_cache.cached(pin_shop_id) if pin_shop_id is not None else None
    read_user = user_values is None
    read_pin = pin_shop_id if pinned is None else None
    if read_user or read_pin is not None:
        if postgres:
            if not scoped:
                await session.execute(select(*_scope_gucs(user_id, pin_shop_id)))
            fresh_user, shop_values, pin = await _read_user_and_pin_fused(
                session, user_id if read_user else None, read_pin
            )
        else:
            fresh_user, shop_values, pin = await _read_user_and_pin_plain(
                session, user_id if read_user else None, read_pin
            )
        if read_user and fresh_user is not None:
            user_values = fresh_user
            remember_reviewer_user(fresh_user)
        if shop_values is not None and pin is not None:
            pinned = pin_cache.remember_values(shop_values, pin)
    return ReviewerIdentity(account, user_values, pinned)


def _scope_gucs(user_id: uuid.UUID, pin_shop_id: uuid.UUID | None) -> list[Any]:
    """``SET LOCAL`` of the user GUC (the ``sub``) and the shop GUC (the pin, or none)."""
    return [
        func.set_config(_USER_GUC, str(user_id), True),
        func.set_config(_SHOP_GUC, str(pin_shop_id) if pin_shop_id is not None else "", True),
    ]


def _columns(model: Any) -> list[tuple[str, Any]]:
    return [(attr.key, attr.columns[0]) for attr in sa_inspect(model).column_attrs]


_ACCOUNT_COLUMNS = (
    "id",
    "user_id",
    "email",
    "platform",
    "expires_at",
    "revoked_at",
    "last_session_id",
    "created_at",
)


async def _read_account_setting_scope(
    session: AsyncSession, user_id: uuid.UUID, pin_shop_id: uuid.UUID | None
) -> tuple[ReviewerAccount | None, bool]:
    """Read the account as ``juli_ops``; the same statement restores the role and sets the GUCs.

    Returns ``(account, scoped)``; ``scoped`` is False when no role switch happened here
    (an outer ``ops_role`` block owns it), and the GUCs were then not set either.
    """
    async with ops_role(session) as block:
        previous_role = block.hand_over()
        if previous_role is None:
            return await accounts.read_account(session, user_id), False
        found = (
            select(*(getattr(OpsReviewerAccount, name) for name in _ACCOUNT_COLUMNS))
            .where(OpsReviewerAccount.user_id == user_id)
            .subquery("account")
        )
        one = select(literal(1).label("one")).subquery("one")
        # The role restore and the GUCs are in the projection, evaluated for the one
        # result row AFTER the account scan produced it (the plan, the RLS policy and the
        # privilege check were all fixed as juli_ops when the statement started) -- the
        # same shape as ``overview.find_shop_entering_seller_scope``.
        row = (
            await session.execute(
                select(
                    *(found.c[name] for name in _ACCOUNT_COLUMNS),
                    func.set_config("role", previous_role, True),
                    *_scope_gucs(user_id, pin_shop_id),
                ).select_from(one.outerjoin(found, true()))
            )
        ).one()
    values = {name: row[index] for index, name in enumerate(_ACCOUNT_COLUMNS)}
    if values["id"] is None:
        return None, True
    return accounts.snapshot_from_values(values), True


async def _read_user_and_pin_fused(
    session: AsyncSession, user_id: uuid.UUID | None, pin_shop_id: uuid.UUID | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, sandbox.PinMode | None]:
    """One statement under the GUCs ``_scope_gucs`` set: users row, shops row, pin facts."""
    one = select(literal(1).label("one")).subquery("one")
    source: Any = one
    selected: list[Any] = []
    user_cols = _columns(User) if user_id is not None else []
    shop_cols = _columns(Shop) if pin_shop_id is not None else []
    if user_id is not None:
        users = User.__table__
        source = source.outerjoin(users, users.c.id == user_id)
        selected += [col for _, col in user_cols]
    if pin_shop_id is not None:
        shops = Shop.__table__
        source = source.outerjoin(shops, shops.c.id == pin_shop_id)
        selected += [col for _, col in shop_cols]
        owners = func.enumerate_sandbox_write_credentials().table_valued(
            column("out_shop_id", Uuid),
            "out_merchant",
            "out_collides",
            with_ordinality="ordinality",
        )
        newest = (
            select(owners.c.out_shop_id, owners.c.out_merchant, owners.c.out_collides)
            .order_by(owners.c.ordinality)
            .limit(1)
            .lateral("sandbox_owner")
        )
        source = source.outerjoin(newest, true())
        selected += [
            select(func.array_agg(TikTokCredential.capability))
            .where(TikTokCredential.shop_id == pin_shop_id)
            .scalar_subquery(),
            exists().where(ProductionWriteShop.shop_id == pin_shop_id),
            newest.c.out_shop_id,
            newest.c.out_merchant,
            newest.c.out_collides,
        ]
    row = (await session.execute(select(*selected).select_from(source))).one()
    index = 0
    user_values: dict[str, Any] | None = None
    if user_id is not None:
        user_values = {key: row[index + i] for i, (key, _) in enumerate(user_cols)}
        index += len(user_cols)
        if user_values.get("id") != user_id:
            user_values = None
    if pin_shop_id is None:
        return user_values, None, None
    shop_values = {key: row[index + i] for i, (key, _) in enumerate(shop_cols)}
    index += len(shop_cols)
    if shop_values.get("id") != pin_shop_id:
        return user_values, None, None
    capabilities, production_write_row, owner_shop, owner_merchant, owner_collides = row[index:]
    owner = (
        SandboxWriteOwner(owner_shop, owner_merchant, bool(owner_collides))
        if owner_shop is not None
        else None
    )
    pin = sandbox.pin_mode(
        pin_shop_id,
        sandbox_owner=owner,
        capabilities={c for c in (capabilities or []) if c is not None},
        production_write_row=bool(production_write_row),
    )
    return user_values, shop_values, pin


async def _read_user_and_pin_plain(
    session: AsyncSession, user_id: uuid.UUID | None, pin_shop_id: uuid.UUID | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, sandbox.PinMode | None]:
    """The same facts with plain statements (SQLite: no roles, GUCs or SQL functions)."""
    user_values: dict[str, Any] | None = None
    if user_id is not None:
        user_cols = _columns(User)
        found = (
            await session.execute(
                select(*(col for _, col in user_cols)).where(User.__table__.c.id == user_id)
            )
        ).first()
        if found is not None:
            user_values = {key: found[i] for i, (key, _) in enumerate(user_cols)}
    if pin_shop_id is None:
        return user_values, None, None
    shop_cols = _columns(Shop)
    shop_row = (
        await session.execute(
            select(*(col for _, col in shop_cols)).where(Shop.__table__.c.id == pin_shop_id)
        )
    ).first()
    if shop_row is None:
        return user_values, None, None
    shop_values = {key: shop_row[i] for i, (key, _) in enumerate(shop_cols)}
    return user_values, shop_values, await sandbox.classify_pin(session, pin_shop_id)


__all__ = ["ReviewerIdentity", "load_identity"]
