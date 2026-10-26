"""Partner reviewer accounts: read, sign-in mark, create / renew / revoke (P32-A, D42).

``ops_reviewer_accounts`` is an ops table (migration 090): every read or write
goes through :func:`services.ops.access.ops_role` (``juli_ops``), never the
seller role. The API gate reads an account per reviewer request through a
short in-process cache (:data:`CACHE_SECONDS`), so a revoke reaches every API
worker within that window; the provisioning command also bans the Supabase
user, so no new token is minted after a revoke.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ops import REVIEWER_ROLE, OpsReviewerAccount
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import ops_role

#: D42.5: a reviewer account lives 30 days unless the command says otherwise.
DEFAULT_LIFETIME_DAYS = 30
MAX_LIFETIME_DAYS = 90

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_REVOKED = "revoked"
STATUS_UNKNOWN = "unknown"


def cache_seconds() -> float:
    raw = os.getenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "").strip()
    try:
        return max(0.0, float(raw)) if raw else 15.0
    except ValueError:
        return 15.0


@dataclass(frozen=True)
class ReviewerAccount:
    """A plain snapshot of one row (safe to cache; no ORM state)."""

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    platform: str
    expires_at: datetime
    revoked_at: datetime | None
    last_session_id: str | None
    #: P66: when the account was created -- a sandbox reviewer sees only the shop's runs
    #: from then on (and its own), never the team's older verification runs.
    created_at: datetime | None = None

    def status(self, now: datetime | None = None) -> str:
        if self.revoked_at is not None:
            return STATUS_REVOKED
        if self.expires_at <= (now or utc_now_naive()):
            return STATUS_EXPIRED
        return STATUS_ACTIVE

    @property
    def actor(self) -> audit.Actor:
        """The audit actor: no staff id, ``reviewer:<platform>:<email>``."""
        return audit.Actor(staff_id=None, email=f"reviewer:{self.platform}:{self.email}")


def _snapshot(row: OpsReviewerAccount) -> ReviewerAccount:
    return ReviewerAccount(
        id=row.id,
        user_id=row.user_id,
        email=row.email,
        platform=row.platform,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        last_session_id=row.last_session_id,
        created_at=row.created_at,
    )


_lock = threading.Lock()
_cache: dict[uuid.UUID, tuple[float, ReviewerAccount | None]] = {}


def forget_cached(user_id: uuid.UUID | None = None) -> None:
    """Drop one cached account (or all): tests, and after a write in this process."""
    with _lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


async def load_account(session: AsyncSession, user_id: uuid.UUID) -> ReviewerAccount | None:
    """The account of this Supabase user (cached ``cache_seconds()``), or None."""
    ttl = cache_seconds()
    with _lock:
        hit = _cache.get(user_id)
    if hit is not None and time.monotonic() - hit[0] <= ttl:
        return hit[1]
    async with ops_role(session):
        row = (
            await session.execute(
                select(OpsReviewerAccount).where(OpsReviewerAccount.user_id == user_id)
            )
        ).scalar_one_or_none()
        account = _snapshot(row) if row is not None else None
    with _lock:
        _cache[user_id] = (time.monotonic(), account)
    return account


async def claim_sign_in(
    session: AsyncSession, account: ReviewerAccount, session_id: str, *, at: datetime | None = None
) -> bool:
    """Mark ``session_id`` as this account's latest sign-in; True for the one caller that did.

    A conditional UPDATE (``last_session_id IS DISTINCT FROM :sid``), so two API
    workers seeing the same new session record ONE sign-in. No commit.
    """
    moment = at or utc_now_naive()
    async with ops_role(session):
        result = await session.execute(
            update(OpsReviewerAccount)
            .where(
                OpsReviewerAccount.id == account.id,
                or_(
                    OpsReviewerAccount.last_session_id.is_(None),
                    OpsReviewerAccount.last_session_id != session_id,
                ),
            )
            .values(last_session_id=session_id, last_sign_in_at=moment)
            .execution_options(synchronize_session=False)
        )
    claimed = int(getattr(result, "rowcount", 0) or 0) == 1
    forget_cached(account.user_id)
    return claimed


# -- provisioning (the CLI) -----------------------------------------------------------


def _lifetime(days: int) -> timedelta:
    if not 1 <= days <= MAX_LIFETIME_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_LIFETIME_DAYS}")
    return timedelta(days=days)


def normalise_platform(platform: str) -> str:
    value = platform.strip().lower()
    if not value or len(value) > 32 or not value.replace("_", "").replace("-", "").isalnum():
        raise ValueError("platform must be a short lower-case label, e.g. 'shopee'")
    return value


async def find_by_email(session: AsyncSession, email: str) -> ReviewerAccount | None:
    async with ops_role(session):
        row = (
            await session.execute(
                select(OpsReviewerAccount).where(OpsReviewerAccount.email == email.strip().lower())
            )
        ).scalar_one_or_none()
        return _snapshot(row) if row is not None else None


async def upsert_account(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
    platform: str,
    days: int = DEFAULT_LIFETIME_DAYS,
    by: str,
    now: datetime | None = None,
) -> ReviewerAccount:
    """Create the account, or reactivate it (new expiry, not revoked). Audited; no commit."""
    moment = now or utc_now_naive()
    email = email.strip().lower()
    platform = normalise_platform(platform)
    expires_at = moment + _lifetime(days)
    async with ops_role(session):
        row = (
            await session.execute(
                select(OpsReviewerAccount).where(
                    or_(OpsReviewerAccount.email == email, OpsReviewerAccount.user_id == user_id)
                )
            )
        ).scalar_one_or_none()
        before = None
        if row is None:
            row = OpsReviewerAccount(
                id=uuid.uuid4(),
                user_id=user_id,
                email=email,
                role=REVIEWER_ROLE,
                platform=platform,
                expires_at=expires_at,
                created_by=by,
                created_at=moment,
                updated_at=moment,
            )
            session.add(row)
        else:
            before = {"expires_at": row.expires_at, "revoked_at": row.revoked_at}
            row.user_id = user_id
            row.email = email
            row.platform = platform
            row.expires_at = expires_at
            row.revoked_at = None
            row.updated_at = moment
        snapshot = _snapshot(row)
    await audit.record(
        session,
        audit.Actor(staff_id=None, email=by),
        audit.ACTION_REVIEWER_ACCOUNT_CREATE,
        before=before,
        after={"email": email, "platform": platform, "expires_at": expires_at},
        at=moment,
    )
    forget_cached(user_id)
    return snapshot


async def renew_account(
    session: AsyncSession,
    email: str,
    *,
    days: int = DEFAULT_LIFETIME_DAYS,
    by: str,
    now: datetime | None = None,
) -> ReviewerAccount | None:
    """New ``expires_at = now + days``, ``revoked_at`` cleared. Audited; no commit."""
    moment = now or utc_now_naive()
    async with ops_role(session):
        row = (
            await session.execute(
                select(OpsReviewerAccount).where(OpsReviewerAccount.email == email.strip().lower())
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        before = {"expires_at": row.expires_at, "revoked_at": row.revoked_at}
        row.expires_at = moment + _lifetime(days)
        row.revoked_at = None
        row.updated_at = moment
        snapshot = _snapshot(row)
    await audit.record(
        session,
        audit.Actor(staff_id=None, email=by),
        audit.ACTION_REVIEWER_ACCOUNT_RENEW,
        before=before,
        after={
            "email": snapshot.email,
            "platform": snapshot.platform,
            "expires_at": snapshot.expires_at,
        },
        at=moment,
    )
    forget_cached(snapshot.user_id)
    return snapshot


def retired_email(email: str, at: datetime) -> str:
    """The address a retired account keeps: ``local+retired-<UTC stamp>@domain`` (P67)."""
    local, _, domain = email.strip().lower().partition("@")
    return f"{local}+retired-{at.strftime('%Y%m%d%H%M%S')}@{domain}"


async def retire_account(
    session: AsyncSession, email: str, *, by: str, now: datetime | None = None
) -> ReviewerAccount | None:
    """Revoke the account and free its e-mail for a fresh one (P67, D75 Q4). Audited; no commit.

    The row is kept (history, audit) under :func:`retired_email`; a new account for the
    same address then gets a NEW row -- new Supabase user id, new ``created_at`` -- so the
    sandbox reviewer's run history (P66: its own runs and the shop's runs since its
    account was created) starts empty.
    """
    moment = now or utc_now_naive()
    async with ops_role(session):
        row = (
            await session.execute(
                select(OpsReviewerAccount).where(OpsReviewerAccount.email == email.strip().lower())
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        before = {"email": row.email, "revoked_at": row.revoked_at}
        row.email = retired_email(row.email, moment)
        row.revoked_at = row.revoked_at or moment
        row.updated_at = moment
        await session.flush()
        snapshot = _snapshot(row)
    await audit.record(
        session,
        audit.Actor(staff_id=None, email=by),
        audit.ACTION_REVIEWER_ACCOUNT_REVOKE,
        before=before,
        after={"email": snapshot.email, "platform": snapshot.platform, "revoked_at": moment},
        at=moment,
    )
    forget_cached(snapshot.user_id)
    return snapshot


async def revoke_account(
    session: AsyncSession, email: str, *, by: str, now: datetime | None = None
) -> ReviewerAccount | None:
    """``revoked_at = now`` (the row is kept). Audited; no commit."""
    moment = now or utc_now_naive()
    async with ops_role(session):
        row = (
            await session.execute(
                select(OpsReviewerAccount).where(OpsReviewerAccount.email == email.strip().lower())
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        before = {"revoked_at": row.revoked_at}
        row.revoked_at = moment
        row.updated_at = moment
        snapshot = _snapshot(row)
    await audit.record(
        session,
        audit.Actor(staff_id=None, email=by),
        audit.ACTION_REVIEWER_ACCOUNT_REVOKE,
        before=before,
        after={"email": snapshot.email, "platform": snapshot.platform, "revoked_at": moment},
        at=moment,
    )
    forget_cached(snapshot.user_id)
    return snapshot
