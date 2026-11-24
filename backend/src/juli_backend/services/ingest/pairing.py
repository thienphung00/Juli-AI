"""Juli Connector pairing (D31.4): a short code for a scoped, rotating ingest token.

The extension never holds the seller's Juli password or session:

1. The seller, signed in on demo.app-juli.com, creates a pairing code for one
   shop (``create_pairing_code``): 10 characters, valid 10 minutes, single use,
   only its hash stored.
2. The extension exchanges it at ``POST /v1/ingest/pair``
   (``redeem_pairing_code``) for an ingest token: ingest endpoints only (it is
   not a Supabase JWT, so no other route accepts it), one shop, stored hashed,
   90-day expiry, revocable by the seller.
3. The extension rotates it (``rotate_token``) -- the old token keeps working
   for ``ROTATION_GRACE`` so a lost response does not unpair the browser.

TENANCY. A token is ``jci_<shop id hex>_<secret>``: the shop id is not secret,
the 256-bit secret is. It is resolved under THAT shop's scope (RLS narrows the
lookup to the shop's own tokens), so a forged prefix finds nothing. A pairing
code carries no shop, so the redeem sets ``app.pairing_code_hash`` to the hash
of the code it was given; ``ingest_pairing_codes``' SELECT policy admits the one
row with that hash, and everything after that runs under the code's shop.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import IngestPairingCode, IngestToken
from juli_backend.models.models import Shop
from juli_backend.services.ingest import min_version

logger = logging.getLogger(__name__)

PAIRING_CODE_TTL = timedelta(minutes=10)
TOKEN_TTL = timedelta(days=90)
ROTATION_GRACE = timedelta(minutes=10)
#: The extension is told to rotate once a token is this old.
ROTATE_AFTER = timedelta(days=30)
#: At most this many live (unused, unexpired) codes per shop.
MAX_LIVE_CODES = 5
#: ``last_used_at`` is written at most this often per token.
LAST_USED_RESOLUTION = timedelta(minutes=5)

#: No 0/O, 1/I/L, U: read aloud and typed without ambiguity.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 10
TOKEN_PREFIX = "jci_"
PAIRING_GUC = "app.pairing_code_hash"


class PairingError(Exception):
    """A refused pairing step; ``code`` is stable for the client, never more detail."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class IssuedCode:
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedToken:
    token: str
    token_id: uuid.UUID
    shop_id: uuid.UUID
    platform: str
    expires_at: datetime
    rotate_after: datetime


@dataclass(frozen=True)
class IngestPrincipal:
    token_id: uuid.UUID
    shop_id: uuid.UUID
    platform: str
    platform_shop_id: str | None
    expires_at: datetime
    created_at: datetime
    #: The token was paired by a Juli Connector (``min_version.made_by_connector``), not made for
    #: a loader script: a request on it must name its Connector version (C5a).
    from_connector: bool = False

    @property
    def rotate_after(self) -> datetime:
        return self.created_at + ROTATE_AFTER


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def code_hash(code: str) -> str:
    return hashlib.sha256(f"pair:{normalize_code(code)}".encode()).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def _new_token(shop_id: uuid.UUID) -> str:
    return f"{TOKEN_PREFIX}{shop_id.hex}_{secrets.token_urlsafe(32)}"


def parse_token_shop(token: str) -> uuid.UUID | None:
    """The shop a token names, or ``None`` for anything not shaped like one."""
    if not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    shop_hex, sep, secret = token[len(TOKEN_PREFIX) :].partition("_")
    if not sep or len(shop_hex) != 32 or len(secret) < 32:
        return None
    try:
        return uuid.UUID(hex=shop_hex)
    except ValueError:
        return None


def _rowcount(result: object) -> int:
    """Rows an UPDATE touched (``CursorResult.rowcount``; ``Result`` does not type it)."""
    return int(getattr(result, "rowcount", 0) or 0)


def _is_postgres(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


# -- seller side ----------------------------------------------------------------------


async def create_pairing_code(
    session: AsyncSession, *, shop: Shop, user_id: uuid.UUID | None, now: datetime
) -> IssuedCode:
    """A new code for ``shop`` (the caller's tenant scope is already the shop's)."""
    live = (
        await session.execute(
            select(func.count())
            .select_from(IngestPairingCode)
            .where(
                IngestPairingCode.shop_id == shop.id,
                IngestPairingCode.used_at.is_(None),
                IngestPairingCode.expires_at > now,
            )
        )
    ).scalar_one()
    if live >= MAX_LIVE_CODES:
        raise PairingError("too_many_codes", status=429)
    code = _new_code()
    row = IngestPairingCode(
        id=uuid.uuid4(),
        shop_id=shop.id,
        code_hash=code_hash(code),
        created_by_user_id=user_id,
        created_at=now,
        expires_at=now + PAIRING_CODE_TTL,
    )
    session.add(row)
    await session.flush()
    logger.info(
        "ingest_pairing_code_created",
        extra={"shop_id": str(shop.id), "user_id": str(user_id) if user_id else None},
    )
    return IssuedCode(code=code, expires_at=row.expires_at)


async def list_tokens(session: AsyncSession, shop_id: uuid.UUID) -> list[IngestToken]:
    rows = await session.execute(
        select(IngestToken)
        .where(IngestToken.shop_id == shop_id)
        .order_by(IngestToken.created_at.desc())
    )
    return list(rows.scalars())


async def revoke_token(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    token_id: uuid.UUID,
    reason: str,
    now: datetime,
) -> bool:
    """Revoke one of the shop's tokens (and any token rotated from it); False if unknown."""
    token = await session.get(IngestToken, token_id)
    if token is None or token.shop_id != shop_id:
        return False
    ids = {token.id}
    # A token rotated from this one is the same browser: revoke the chain forward.
    frontier = [token.id]
    while frontier:
        children = (
            await session.execute(
                select(IngestToken.id).where(
                    IngestToken.shop_id == shop_id, IngestToken.rotated_from_id.in_(frontier)
                )
            )
        ).scalars()
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    await session.execute(
        update(IngestToken)
        .where(IngestToken.id.in_(ids), IngestToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason[:64])
    )
    await _release_leases(session, shop_id, ids)
    logger.info(
        "ingest_token_revoked",
        extra={"shop_id": str(shop_id), "token_ids": sorted(str(i) for i in ids), "reason": reason},
    )
    return True


INACTIVE_AFTER = timedelta(days=14)


async def last_seen_by_token(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[uuid.UUID, datetime | None]:
    """Per token of the shop: when that computer was last seen (its heartbeat, else its last
    use, else when it was paired)."""
    from juli_backend.models.shopee_connector import ShopeeConnectorTokenState

    beats = {
        s.token_id: s.heartbeat_at
        for s in (
            await session.execute(
                select(ShopeeConnectorTokenState).where(
                    ShopeeConnectorTokenState.shop_id == shop_id
                )
            )
        ).scalars()
    }
    out: dict[uuid.UUID, datetime | None] = {}
    for t in await list_tokens(session, shop_id):
        seen = [d for d in (beats.get(t.id), t.last_used_at, t.created_at) if d is not None]
        out[t.id] = max(seen) if seen else None
    return out


async def revoke_inactive(
    session: AsyncSession, *, shop_id: uuid.UUID, reason: str, now: datetime
) -> int:
    """F6.5: revoke the shop's live tokens whose computer was not seen for 14 days (never
    another shop's, never a recently seen one). Returns how many were revoked."""
    seen = await last_seen_by_token(session, shop_id)
    old = []
    for t in await list_tokens(session, shop_id):
        last = seen.get(t.id)
        if t.revoked_at is None and (last is None or now - last > INACTIVE_AFTER):
            old.append(t.id)
    if not old:
        return 0
    await session.execute(
        update(IngestToken)
        .where(
            IngestToken.shop_id == shop_id,
            IngestToken.id.in_(old),
            IngestToken.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_reason=reason[:64])
    )
    await _release_leases(session, shop_id, old)
    logger.info(
        "ingest_tokens_revoked_inactive",
        extra={"shop_id": str(shop_id), "count": len(old), "reason": reason},
    )
    return len(old)


# -- extension side -------------------------------------------------------------------


async def _issue(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    platform_shop_id: str | None,
    client_label: str | None,
    now: datetime,
    rotated_from: uuid.UUID | None = None,
    install_id: str | None = None,
) -> IssuedToken:
    token = _new_token(shop_id)
    row = IngestToken(
        id=uuid.uuid4(),
        shop_id=shop_id,
        token_hash=token_hash(token),
        platform=platform,
        platform_shop_id=platform_shop_id,
        client_label=client_label,
        install_id=install_id,
        created_at=now,
        expires_at=now + TOKEN_TTL,
        rotated_from_id=rotated_from,
    )
    session.add(row)
    await session.flush()
    return IssuedToken(
        token=token,
        token_id=row.id,
        shop_id=shop_id,
        platform=platform,
        expires_at=row.expires_at,
        rotate_after=now + ROTATE_AFTER,
    )


async def _supersede_install(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    install_id: str,
    keep: uuid.UUID,
    now: datetime,
) -> None:
    """A re-pair from the same install (same shop + platform + install id) retires that install's
    older live tokens -- the whole chain, rotated children included (batch-1124-a C2: a child
    rotated before 0.3.35's server carries no install id; it is given its chain's here) -- with
    the rotation grace so a lost response does not strand the browser. Their fill-job leases are
    released at once (C3)."""
    chain = await _install_chain(
        session, shop_id=shop_id, platform=platform, install_id=install_id, keep=keep
    )
    if not chain:
        return
    await session.execute(
        update(IngestToken)
        .where(
            IngestToken.shop_id == shop_id,
            IngestToken.id.in_(chain),
            IngestToken.install_id.is_(None),
        )
        .values(install_id=install_id)
    )
    retired = (
        await session.execute(
            update(IngestToken)
            .where(
                IngestToken.shop_id == shop_id,
                IngestToken.id.in_(chain),
                IngestToken.revoked_at.is_(None),
                IngestToken.superseded_at.is_(None),
            )
            .values(superseded_at=now)
            .returning(IngestToken.id)
        )
    ).scalars()
    await _release_leases(session, shop_id, chain)
    logger.info(
        "ingest_install_superseded",
        extra={
            "shop_id": str(shop_id),
            "kept": str(keep),
            "token_ids": sorted(str(i) for i in retired),
        },
    )


async def _install_chain(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    install_id: str,
    keep: uuid.UUID,
) -> set[uuid.UUID]:
    """The install's tokens other than ``keep``: those carrying its install id and every token
    rotated from one of them (forward through ``rotated_from_id``)."""
    roots = (
        await session.execute(
            select(IngestToken.id).where(
                IngestToken.shop_id == shop_id,
                IngestToken.platform == platform,
                IngestToken.install_id == install_id,
                IngestToken.id != keep,
            )
        )
    ).scalars()
    ids = set(roots)
    frontier = list(ids)
    while frontier:
        children = (
            await session.execute(
                select(IngestToken.id).where(
                    IngestToken.shop_id == shop_id,
                    IngestToken.rotated_from_id.in_(frontier),
                    IngestToken.id != keep,
                )
            )
        ).scalars()
        frontier = [c for c in children if c not in ids]
        ids.update(frontier)
    return ids


async def _release_leases(
    session: AsyncSession,
    shop_id: uuid.UUID,
    token_ids: Iterable[uuid.UUID],
    *,
    to_token: uuid.UUID | None = None,
) -> None:
    """C3: a dead token's fill-job leases go at once (another computer may take the job on its
    next poll); with ``to_token`` (a rotation: the same browser) they move to the new token."""
    from juli_backend.services.shopee_recommendations import fill_queue

    await fill_queue.release_token_leases(
        session, shop_id=shop_id, token_ids=set(token_ids), to_token=to_token
    )


async def _find_code(session: AsyncSession, hashed: str) -> IngestPairingCode | None:
    """The code row by its hash, visible through the pairing GUC only."""
    if _is_postgres(session):
        await session.execute(
            text("SELECT set_config(:k, :v, true)").bindparams(k=PAIRING_GUC, v=hashed)
        )
    try:
        return (
            await session.execute(
                select(IngestPairingCode).where(IngestPairingCode.code_hash == hashed)
            )
        ).scalar_one_or_none()
    finally:
        if _is_postgres(session):
            await session.execute(text("SELECT set_config(:k, '', true)").bindparams(k=PAIRING_GUC))


async def redeem_pairing_code(
    session: AsyncSession,
    *,
    code: str,
    platform: str,
    platform_shop_id: str | None,
    client_label: str | None,
    now: datetime,
    install_id: str | None = None,
) -> IssuedToken:
    """Exchange a live code for an ingest token. Every refusal is ``invalid_code``
    except a platform / shop mismatch, which the seller must be told about."""
    if len(normalize_code(code)) != CODE_LENGTH:
        raise PairingError("invalid_code")
    hashed = code_hash(code)
    row = await _find_code(session, hashed)
    if row is None or row.used_at is not None or row.expires_at <= now:
        logger.info("ingest_pairing_refused", extra={"reason": "invalid_code"})
        raise PairingError("invalid_code")
    shop_id = row.shop_id
    async with with_shop_scope(session, shop_id):
        shop = await session.get(Shop, shop_id)
        if shop is None or not shop.is_active:
            raise PairingError("invalid_code")
        if shop.platform != platform:
            logger.info(
                "ingest_pairing_refused",
                extra={"shop_id": str(shop_id), "reason": "platform_mismatch"},
            )
            raise PairingError("platform_mismatch", status=409)
        if shop.shopee_shop_id and platform_shop_id and shop.shopee_shop_id != platform_shop_id:
            logger.info(
                "ingest_pairing_refused", extra={"shop_id": str(shop_id), "reason": "shop_mismatch"}
            )
            raise PairingError("shop_mismatch", status=409)
        claimed = await session.execute(
            update(IngestPairingCode)
            .where(
                IngestPairingCode.id == row.id,
                IngestPairingCode.used_at.is_(None),
                IngestPairingCode.expires_at > now,
            )
            .values(used_at=now)
        )
        if _rowcount(claimed) != 1:
            raise PairingError("invalid_code")
        issued = await _issue(
            session,
            shop_id=shop_id,
            platform=platform,
            platform_shop_id=platform_shop_id or shop.shopee_shop_id,
            client_label=client_label,
            now=now,
            install_id=install_id,
        )
        if install_id:
            await _supersede_install(
                session,
                shop_id=shop_id,
                platform=platform,
                install_id=install_id,
                keep=issued.token_id,
                now=now,
            )
        await session.execute(
            update(IngestPairingCode)
            .where(IngestPairingCode.id == row.id)
            .values(token_id=issued.token_id)
        )
    logger.info(
        "ingest_paired",
        extra={
            "shop_id": str(shop_id),
            "token_id": str(issued.token_id),
            "platform": platform,
            "client_label": client_label,
        },
    )
    return issued


def _token_live(token: IngestToken, now: datetime) -> bool:
    if token.revoked_at is not None or token.expires_at <= now:
        return False
    return token.superseded_at is None or now < token.superseded_at + ROTATION_GRACE


async def resolve_token(session: AsyncSession, token: str, now: datetime) -> IngestPrincipal | None:
    """The principal for a live token, or ``None`` (unknown, expired, revoked, rotated)."""
    shop_id = parse_token_shop(token)
    if shop_id is None:
        return None
    async with with_shop_scope(session, shop_id):
        row = (
            await session.execute(
                select(IngestToken).where(IngestToken.token_hash == token_hash(token))
            )
        ).scalar_one_or_none()
        if row is None or row.shop_id != shop_id or not _token_live(row, now):
            return None
        shop = await session.get(Shop, shop_id)
        if shop is None or not shop.is_active:
            return None
        if row.last_used_at is None or now - row.last_used_at >= LAST_USED_RESOLUTION:
            row.last_used_at = now
            await session.flush()
        return IngestPrincipal(
            token_id=row.id,
            shop_id=row.shop_id,
            platform=row.platform,
            platform_shop_id=row.platform_shop_id,
            expires_at=row.expires_at,
            created_at=row.created_at,
            from_connector=min_version.made_by_connector(row.install_id, row.client_label),
        )


async def rotate_token(
    session: AsyncSession, principal: IngestPrincipal, *, now: datetime
) -> IssuedToken:
    """A fresh token for the same shop; the presented one stops after the grace."""
    async with with_shop_scope(session, principal.shop_id):
        superseded = await session.execute(
            update(IngestToken)
            .where(IngestToken.id == principal.token_id, IngestToken.superseded_at.is_(None))
            .values(superseded_at=now)
        )
        if _rowcount(superseded) != 1:
            # Rotating a token twice would fork one browser into two live tokens.
            raise PairingError("already_rotated", status=409)
        current = await session.get(IngestToken, principal.token_id)
        issued = await _issue(
            session,
            shop_id=principal.shop_id,
            platform=principal.platform,
            platform_shop_id=principal.platform_shop_id,
            client_label=current.client_label if current else None,
            now=now,
            rotated_from=principal.token_id,
            # batch-1124-a C2: the child is the same install, so a later re-pair supersedes it
            install_id=current.install_id if current else None,
        )
        await _release_leases(
            session, principal.shop_id, {principal.token_id}, to_token=issued.token_id
        )
    logger.info(
        "ingest_token_rotated",
        extra={
            "shop_id": str(principal.shop_id),
            "token_id": str(issued.token_id),
            "rotated_from": str(principal.token_id),
        },
    )
    return issued
