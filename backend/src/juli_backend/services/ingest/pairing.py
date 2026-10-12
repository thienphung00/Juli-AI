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
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import IngestPairingCode, IngestToken
from juli_backend.models.models import Shop

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
    logger.info(
        "ingest_token_revoked",
        extra={"shop_id": str(shop_id), "token_ids": sorted(str(i) for i in ids), "reason": reason},
    )
    return True


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
) -> IssuedToken:
    token = _new_token(shop_id)
    row = IngestToken(
        id=uuid.uuid4(),
        shop_id=shop_id,
        token_hash=token_hash(token),
        platform=platform,
        platform_shop_id=platform_shop_id,
        client_label=client_label,
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
