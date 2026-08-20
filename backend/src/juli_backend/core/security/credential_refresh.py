"""One guarded door for refreshing a TikTok credential (ADR-081 decision 4).

Extracted from ``TikTokOAuthService._refresh_credential`` because the three
new callers this ADR introduces (beat, lazy trigger, reactive retry) have no
business constructing an OAuth service carrying ``redirect_uri`` -- an
authorization-flow concern a refresh does not have.

Returns a :class:`RefreshOutcome` and **never raises on refresh failure**
(ADR-081 gap 4): today's ``_refresh_credential`` raises, and because it sat
at the top of the poll cycle, one dead credential aborted ingestion for
every shop that cycle. Each caller now states its own policy against the
returned status instead.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from juli_backend.database.exceptions import NotFound
from juli_backend.database.token_crypto import decrypt_token
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import TikTokCredentialRepo

logger = logging.getLogger(__name__)

# Single value used by both this function's guard and W4-3's beat scan
# predicate (ADR-081 decision 2). Was 30 minutes: a beat scanning a 24h
# window would ask this function to refresh a row 20h from expiry and it
# would silently no-op (ADR-081 gap 6 / decision 9).
REFRESH_BUFFER = timedelta(hours=24)

_LOCK_POLL_INTERVAL_SECONDS = 0.1
_LOCK_POLL_TIMEOUT_SECONDS = 2.0

# Unix-epoch-vs-TTL heuristic shared with services/tiktok/token_expiry.py.
_EPOCH_SECONDS_THRESHOLD = 1_000_000_000

# Exception `.code` values that are safe to retry (ADR-081 decision 9).
# 0 is the network/5xx transport wrapper `TikTokAuth._token_request` raises
# (integrations/tiktok/auth.py) -- never a real vendor code, since TikTok's
# own success code is also 0 but that path returns normally instead of
# raising. 100005 is RateLimitError, 100006 is TikTokSystemError ("safe to
# retry" per its own docstring). Every other code -- including the unmapped
# 105002 "Expired" the vendor actually returns for a dead refresh token --
# falls through to needs_reauth.
_TRANSIENT_CODES = frozenset({0, 100005, 100006})

_NEEDS_REAUTH_MESSAGE = (
    "TikTok rejected the refresh token for this credential (invalid-grant "
    "class); the vendor session cannot self-heal. Re-run "
    "TikTokOAuthService.initiate_oauth for this shop (the re-OAuth runbook "
    "step) to restore access."
)


class RefreshStatus(str, Enum):
    """Every state :func:`refresh_credential` can return (ADR-081 decision 4)."""

    FRESH = "fresh"
    REFRESHED = "refreshed"
    LOCKED = "locked"
    TRANSIENT = "transient"
    NEEDS_REAUTH = "needs_reauth"


@dataclass(frozen=True)
class RefreshOutcome:
    """Result of :func:`refresh_credential`.

    ``error`` carries the exact exception the vendor call raised, for
    ``transient``/``needs_reauth`` only. It exists so a caller that still
    wants the pre-ADR-081 raise-on-failure contract (the thin wrappers in
    ``tiktok_oauth.py``) can re-raise the identical exception rather than a
    synthesized one -- "nothing outside this slice breaks."
    """

    credential: TikTokCredential
    status: RefreshStatus
    error: Exception | None = None


class RefreshAuth(Protocol):
    """Structural counterpart of ``integrations.tiktok.auth.TikTokAuth``.

    Defined here, in ``core``, rather than imported: ``core -> integrations``
    is a forbidden edge in ``.importlinter.toml`` and the checker is
    AST-based, so a ``TYPE_CHECKING`` guard would not exempt it either.
    Mirrors the ``BindingVerifier`` precedent in ``tiktok_oauth.py``: the
    real ``TikTokAuth`` satisfies this structurally without either module
    importing the other's concrete class, and callers pass a real
    ``TikTokAuth`` instance in at the call site exactly as
    ``TikTokOAuthService`` already does.
    """

    def refresh_access_token(self, refresh_token: str) -> dict: ...


def _utc_now() -> datetime:
    """Naive UTC timestamp (compatible with SQLite and PostgreSQL)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _dialect_name(session: AsyncSession) -> str:
    return session.get_bind().dialect.name


def _access_token_expires_at(raw: int | None) -> datetime:
    """Vendor-authoritative access-token expiry (ADR-081 decision 3).

    Duplicated from ``services.tiktok.token_expiry.access_token_expires_at``
    rather than imported: ``core -> services`` is a forbidden edge in
    ``.importlinter.toml``, and importing it here would be a *new*
    AST-detected violation (that module's own forbidden edge from
    ``tiktok_oauth.py`` is pre-existing debt, grandfathered in
    ``docs/architecture/import-boundary-baseline.json`` for that file only).
    Same rule as the function it mirrors: a missing value is refused rather
    than synthesized, because a wrong expiry *suppresses* the refresh that
    would have corrected it -- exactly what happened to the sandbox
    credential (seeded ``now + 7d``) while the API answered `105002 Expired`.
    """
    if not raw:
        raise ValueError(
            "TikTok refresh response omitted access_token_expire_in; "
            "refusing to synthesize an expiry (ADR-081 decision 3)"
        )
    if raw >= _EPOCH_SECONDS_THRESHOLD:
        return datetime.fromtimestamp(raw, tz=UTC).replace(tzinfo=None)
    return _utc_now() + timedelta(seconds=raw)


def _refresh_token_expires_at(raw: int | None) -> datetime | None:
    """Opportunistic capture only (ADR-081 decision 7).

    ``None`` when the vendor omits ``refresh_token_expire_in`` -- the common
    case today; nothing may assume this column is non-null.
    """
    if not raw:
        return None
    if raw >= _EPOCH_SECONDS_THRESHOLD:
        return datetime.fromtimestamp(raw, tz=UTC).replace(tzinfo=None)
    return _utc_now() + timedelta(seconds=raw)


def _hydrate(credential: TikTokCredential) -> TikTokCredential:
    """Expose plaintext tokens on a freshly-fetched row.

    Mirrors ``repositories/repos.py``'s private ``_hydrate_decrypted_tokens``
    (duplicated because that helper is module-private): ``set_committed_value``
    swaps in the decrypted string without marking the ORM attribute dirty, so
    a later flush never re-encrypts plaintext back over ciphertext.

    Must only be called on an object no *later* repo write in this same call
    will touch: a repo write method fetches the row itself and decrypts
    assuming the stored column is still ciphertext -- calling this first
    would hand it plaintext to "decrypt" and corrupt the value.
    """
    set_committed_value(credential, "access_token", decrypt_token(credential.access_token))
    set_committed_value(credential, "refresh_token", decrypt_token(credential.refresh_token))
    return credential


def _log_extra(credential: TikTokCredential) -> dict[str, str]:
    """Shop/merchant/capability only -- matches the existing
    ``tiktok_token_refreshed`` convention. Never token material."""
    extra: dict[str, str] = {"shop_id": str(credential.shop_id)}
    if credential.merchant_authorization_id is not None:
        extra["merchant_authorization_id"] = credential.merchant_authorization_id
    if credential.capability is not None:
        extra["capability"] = credential.capability
    return extra


async def _fetch(session: AsyncSession, credential_id: uuid.UUID) -> TikTokCredential:
    """Force a real DB round-trip (``populate_existing``) rather than an
    identity-map hit -- both session factories in this codebase configure
    ``expire_on_commit=False``, so a bare ``session.get`` after a commit
    would silently return stale, pre-commit attribute values."""
    credential = await session.get(TikTokCredential, credential_id, populate_existing=True)
    if credential is None:
        raise NotFound(f"Credential {credential_id} not found")
    return credential


async def _try_advisory_lock(
    session: AsyncSession, credential_id: uuid.UUID
) -> tuple[bool, AsyncConnection | None]:
    """Session-level, non-transactional advisory lock (ADR-081 decision 5).

    Returns ``(acquired, conn)``. When ``acquired`` is ``True``, ``conn`` is
    the **dedicated** connection holding the lock -- the caller must pass it
    to :func:`_release_advisory_lock` in a ``finally`` once done. When
    ``acquired`` is ``False`` (lock already held elsewhere, or SQLite),
    ``conn`` is ``None`` and there is nothing to release; the attempt's own
    connection, if any, is already closed before this returns.

    Deliberately ``pg_try_advisory_lock``, not the transaction-scoped
    ``pg_try_advisory_xact_lock``: a session-level lock is tied to a
    *connection*, not a transaction, so it survives a ``COMMIT`` -- which is
    the entire point, since the caller needs the lock held across the
    "commit -> re-read -> vendor HTTP call" sequence with no open
    transaction.

    That is also exactly why this uses a connection **dedicated** to the
    lock (``session.bind.connect()`` -- the ``AsyncEngine``, not
    ``session.get_bind()``'s internal sync-facing proxy, which cannot be
    connected to outside the ORM's own greenlet bridge) rather than
    ``session``'s own: this codebase's session factories run with
    ``NullPool`` (#871), and under ``NullPool`` an ``AsyncSession.commit()``
    does not merely end the SQL transaction -- it checks the physical
    connection back in, and ``NullPool`` *closes* connections on checkin.
    Verified empirically against a real Postgres instance while building
    this: the backend PID visible through ``session`` changes on every
    ``session.commit()``. A lock acquired via ``session``'s own connection
    would therefore already be gone (Postgres releases all session-level
    advisory locks when the connection closes) by the time this function
    tried to use it -- which is precisely how the first version of this code
    shipped 2 vendor calls for 2 concurrent callers instead of 1, caught by
    the real-Postgres concurrency suite
    (``tests/integration/test_credential_refresh_concurrency.py``), not by
    SQLite.

    A **failed** attempt closes its connection immediately rather than
    holding it open for the loser's subsequent poll loop -- the two-
    connections-per-refresh cost (this one plus ``session``'s own) is only
    worth paying while a lock is actually held.

    Postgres-only; SQLite (the unit-test matrix) has no such primitive and,
    being a single in-process connection per test, no real cross-connection
    contention to guard against -- it always "acquires", no connection
    involved.
    """
    if _dialect_name(session) != "postgresql":
        return True, None

    # `Session.bind` is typed `AsyncEngine | AsyncConnection`, and only an
    # engine can hand out the *separate* connection this lock depends on.
    # Fail closed rather than cast: if the session were ever bound to a single
    # connection, `.connect()` would not exist and -- worse than a type error
    # -- there would be no second connection to hold the lock on, silently
    # reintroducing the NullPool release this function exists to prevent.
    engine = session.bind
    if not isinstance(engine, AsyncEngine):
        raise RuntimeError(
            "refresh_credential requires a session bound to an AsyncEngine; "
            f"got {type(engine).__name__}. The advisory lock must be held on a "
            "connection independent of the caller's session."
        )
    conn = await engine.connect()
    try:
        result = await conn.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": str(credential_id)}
        )
        acquired = bool(result.scalar())
        await conn.commit()
    except BaseException:
        await conn.close()
        raise

    if not acquired:
        await conn.close()
        return False, None
    return True, conn


async def _release_advisory_lock(conn: AsyncConnection | None, credential_id: uuid.UUID) -> None:
    """Release + close the dedicated lock connection from
    :func:`_try_advisory_lock`. A no-op when ``conn`` is ``None`` (lock was
    never acquired, or dialect is not Postgres)."""
    if conn is None:
        return
    try:
        await conn.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": str(credential_id)}
        )
        await conn.commit()
    finally:
        await conn.close()


async def _poll_for_refresh(
    session: AsyncSession, credential_id: uuid.UUID, baseline_expiry: datetime
) -> TikTokCredential | None:
    """Lock loser: poll the row for a bounded couple of seconds (ADR-081
    decision 5) rather than queueing behind the winner -- so N simultaneous
    callers for the same row produce one vendor call, not N."""
    deadline = time.monotonic() + _LOCK_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        current = await _fetch(session, credential_id)
        await session.commit()
        if current.token_expires_at != baseline_expiry:
            return current
    return None


async def _handle_vendor_failure(
    session: AsyncSession, credential: TikTokCredential, exc: Exception
) -> RefreshOutcome:
    code = getattr(exc, "code", None)
    if code in _TRANSIENT_CODES:
        logger.warning(
            "tiktok_credential_refresh_transient",
            extra={**_log_extra(credential), "error_type": type(exc).__name__},
        )
        return RefreshOutcome(
            credential=_hydrate(credential), status=RefreshStatus.TRANSIENT, error=exc
        )

    cred_repo = TikTokCredentialRepo(session)
    updated = await cred_repo.mark_needs_reauth(credential.id, _NEEDS_REAUTH_MESSAGE)
    await session.commit()
    logger.error(
        "tiktok_credential_refresh_needs_reauth",
        extra={**_log_extra(updated), "error_type": type(exc).__name__},
    )
    return RefreshOutcome(credential=updated, status=RefreshStatus.NEEDS_REAUTH, error=exc)


async def refresh_credential(
    session: AsyncSession,
    credential_id: uuid.UUID,
    *,
    auth: RefreshAuth,
    force: bool = False,
) -> RefreshOutcome:
    """Refresh one credential, guarded by a session-level advisory lock.

    Sequence (ADR-081 decision 5): fetch → guard (skip if ``force`` set) →
    acquire lock → commit → re-read the row (another refresher may have
    already renewed it) → vendor HTTP call with no transaction open → open a
    transaction → write via #1230's repo methods → release the lock (in a
    ``finally``).

    ``force=True`` ignores the ``token_expires_at`` column and always
    attempts a refresh, promoting the operator's manual ``FORCE_EXPIRED=1``
    flag to a typed argument (ADR-081 decision 1).
    """
    credential = await _fetch(session, credential_id)
    baseline_expiry = credential.token_expires_at
    is_fresh = not force and baseline_expiry > _utc_now() + REFRESH_BUFFER
    await session.commit()

    if is_fresh:
        return RefreshOutcome(credential=_hydrate(credential), status=RefreshStatus.FRESH)

    acquired, lock_conn = await _try_advisory_lock(session, credential_id)

    if not acquired:
        winner = await _poll_for_refresh(session, credential_id, baseline_expiry)
        if winner is not None:
            return RefreshOutcome(credential=_hydrate(winner), status=RefreshStatus.REFRESHED)
        current = await _fetch(session, credential_id)
        await session.commit()
        return RefreshOutcome(credential=_hydrate(current), status=RefreshStatus.LOCKED)

    try:
        current = await _fetch(session, credential_id)
        await session.commit()

        if current.token_expires_at != baseline_expiry:
            # Another refresher already renewed this row while we waited for
            # the lock -- no vendor call needed.
            return RefreshOutcome(credential=_hydrate(current), status=RefreshStatus.REFRESHED)

        decrypted_refresh_token = decrypt_token(current.refresh_token)

        # No transaction is open on `session` at this point (both fetches
        # above were immediately committed) -- the vendor HTTP call below
        # never holds a Supabase pooler slot on `session`'s connection
        # (ADR-081 decision 5). The advisory lock itself survives this call
        # because it lives on `lock_conn`, a connection dedicated to the
        # lock alone -- not on `session`'s own (churning) connection.
        try:
            token_data = await asyncio.to_thread(auth.refresh_access_token, decrypted_refresh_token)
        except Exception as exc:  # noqa: BLE001 -- classify without importing
            # integrations.tiktok.exceptions: core -> integrations is a
            # forbidden edge (.importlinter.toml). Classification is by
            # duck-typed `.code` attribute instead (see _TRANSIENT_CODES).
            return await _handle_vendor_failure(session, current, exc)

        new_access_token = token_data["access_token"]
        new_refresh_token = token_data.get("refresh_token", decrypted_refresh_token)
        new_expires_at = _access_token_expires_at(token_data.get("access_token_expire_in"))
        new_refresh_token_expires_at = _refresh_token_expires_at(
            token_data.get("refresh_token_expire_in")
        )

        cred_repo = TikTokCredentialRepo(session)
        updated = await cred_repo.mark_refreshed(
            credential_id,
            new_access_token,
            new_refresh_token,
            new_expires_at,
            refresh_token_expires_at=new_refresh_token_expires_at,
        )
        await session.commit()

        logger.info("tiktok_token_refreshed", extra=_log_extra(updated))
        return RefreshOutcome(credential=updated, status=RefreshStatus.REFRESHED)
    finally:
        await _release_advisory_lock(lock_conn, credential_id)
