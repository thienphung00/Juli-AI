import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.claims import (
    VerifiedIdentity,
    reviewer_platform,
    session_id,
    verified_identity,
)
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.identity_cache import IdentityCache
from juli_backend.core.security.jwt import verify_supabase_jwt
from juli_backend.database import NotFound, User, UsersRepo
from juli_backend.database.database import get_session

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)
#: The same bearer scheme object, for a dependency outside this module (P29).
bearer_scheme = _bearer


@dataclass(frozen=True)
class VerifiedToken:
    """A Supabase JWT that passed verification: its ``sub`` and identity claims.

    Holding one proves the signature, audience and expiry were checked on THIS
    request; it says nothing about the ``users`` row yet.
    """

    user_id: uuid.UUID
    identity: VerifiedIdentity
    #: P32-A (D42): the partner platform when the token carries the reviewer
    #: ``app_metadata`` mark, else None (every seller and staff token).
    reviewer_platform: str | None = None
    #: Supabase's per-sign-in ``session_id`` claim, when present.
    session_id: str | None = None

    @property
    def is_reviewer(self) -> bool:
        return self.reviewer_platform is not None


async def verify_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> VerifiedToken:
    """The JWT half of authentication: no database. 401 on anything wrong.

    Split out of :func:`get_current_user` (P29) so a caller that caches the
    ``users`` read (the Ops console, ``api/routes/ops.get_ops_user``) still
    verifies the token on every request through exactly this code.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    secret = require_env("SUPABASE_JWT_SECRET")
    try:
        payload = await verify_supabase_jwt(credentials.credentials, secret)
    except Unauthorized as exc:
        # The reason goes to the log, not to the caller. `str(exc)` here echoed the JWT
        # library's own parser text ("Signature has expired", "Invalid crypto padding",
        # ...), which tells an attacker precisely which part of a forged token to fix
        # next. #902 / ADR-061.
        logger.warning("jwt_rejected", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        logger.warning("jwt_payload_invalid", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
        )

    # #1973: the same verified payload `sub` came from also carries the
    # seller's Google email, whether Google verified it, and their name. Until
    # now this function read one field and threw the rest away, leaving Juli
    # with no way to contact a seller it had promised 1:1 support to. The
    # translation lives in `claims.py` rather than here -- ADR-085 decision 2
    # keeps this module to the auth decision, and a repository must not learn
    # the shape of a Supabase payload -- so what crosses into the repository is
    # two optional strings and no vendor shape.
    return VerifiedToken(
        user_id=user_id,
        identity=verified_identity(payload),
        reviewer_platform=reviewer_platform(payload),
        session_id=session_id(payload),
    )


#: P32-A (D42): the reviewer gate, bound by the API (``api/reviewer.py``) when
#: the app is built. ``core`` may not import the API or services, so the gate is
#: a port. It runs for every reviewer token before the ``users`` read and before
#: any route code; it raises an HTTPException to refuse, or returns to allow.
ReviewerGate = Callable[[Request, AsyncSession, VerifiedToken], Awaitable[None]]
_reviewer_gate: ReviewerGate | None = None

#: Header naming why a reviewer request was refused (the demo maps it to copy).
REVIEWER_DENIED_HEADER = "X-Juli-Reviewer-Denied"


def bind_reviewer_gate(gate: ReviewerGate | None) -> None:
    global _reviewer_gate
    _reviewer_gate = gate


async def enforce_reviewer_gate(
    request: Request, session: AsyncSession, token: VerifiedToken
) -> None:
    """Run the bound gate for a reviewer token; refuse when none is bound (fail closed)."""
    if not token.is_reviewer:
        return
    gate = _reviewer_gate
    if gate is None:
        logger.error("reviewer_gate_unbound", extra={"path": request.url.path})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản dùng thử tạm thời không dùng được",
            headers={REVIEWER_DENIED_HEADER: "unavailable"},
        )
    await gate(request, session, token)


async def load_authenticated_user(session: AsyncSession, token: VerifiedToken) -> User:
    """The database half: read (or provision) the ``users`` row, then COMMIT.

    Exactly what :func:`get_current_user` does after the token is verified --
    including the unconditional commit, which also ends the user GUC's
    transaction (see below). Callers must not hold other work in the session's
    transaction when calling this.
    """
    user_id, identity = token.user_id, token.identity
    try:
        # The scoped read (#1691): `users` is policy-gated on a GUC that
        # authentication has not set yet, and the repository owns knowing that.
        # ADR-085 decision 2 keeps the tenant seam out of this module, so the
        # scope lives in UsersRepo, not here.
        #
        # `transaction_ends_after=True` (P22): the commit below ends this
        # transaction immediately, and with it the `SET LOCAL` user GUC, so the
        # scope need not read and restore the prior pair -- two round trips
        # (~440 ms in production) off every authenticated request.
        user = await UsersRepo(session).get_for_authentication(
            user_id,
            email=identity.email,
            display_name=identity.display_name,
            transaction_ends_after=True,
        )
    except NotFound:
        # Defensive backstop only (#1906): `get_for_authentication` now
        # provisions a first-time `sub` itself rather than raising this, so
        # in practice this branch is not reachable from that path anymore.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # #1906: the ONLY commit in this module, and deliberately so. A
    # first-time `sub` was just INSERTed by `get_for_authentication` above,
    # and nothing downstream is guaranteed to commit it -- `GET /v1/shops`,
    # the first route a newly signed-in seller reaches, never does (it is a
    # pure read). Without this, the session's `close()` at request end rolls
    # the insert back and the caller 401s again on their very next request.
    # It also does the concurrency work: the loser's blocked INSERT (holding
    # on the `users.id` unique-index lock) only unblocks -- into the
    # `IntegrityError` `_provision_first_sighting` catches -- once the winner
    # commits, and only after that is the winner's row visible to the
    # loser's re-read. Committing unconditionally (not just on the
    # first-sighting branch) is deliberate too: it is a no-op for the
    # ordinary "row already existed" read and keeps this call site the one
    # place that decides the auth read/provision is its own atomic unit,
    # never entangled with whatever the route does next.
    #
    # #1973 gives the unconditional commit a second job it now genuinely does:
    # a RETURNING seller whose row predates migration 065 has their verified
    # email filled in during `get_for_authentication`, and that write is
    # persisted here. Without this commit the backfill would be rolled back at
    # request end and re-attempted on every single request, forever.
    #
    # P22 gives it a third: it is what clears the user GUC. The scope above
    # skipped its own restore (`transaction_ends_after=True`) because this
    # commit ends the transaction, and `SET LOCAL` with it. On the ordinary
    # read-only request it costs one round trip -- the same as the restore it
    # replaces, and a rollback would cost the same again -- so "commit only
    # when something was written" would save nothing while giving up the
    # atomic-unit guarantee above. Do not move or drop it without restoring
    # the scope's own restore.
    await session.commit()
    return user


# -- the reviewer's users row, cached (P69) ---------------------------------------------
#
# A reviewer request's users read (BEGIN, user GUC, users row, COMMIT) is four round
# trips, ~0.8 s from the VPS, in front of every route the demo page fires on load. For a
# REVIEWER token only, the row is cached per verified ``sub`` for the reviewer identity
# TTL (``identity_cache.reviewer_identity_ttl_seconds``, 30 s). Tenant-safe because:
#
# - the key is the verified JWT ``sub`` of THIS request; a hit is a copy of exactly that
#   user's own row (no other user's row can be stored under it);
# - the lookup happens only AFTER the reviewer gate admitted this request (account
#   active, not revoked within its own TTL, route allowlisted) -- the gate runs first,
#   on every request, whatever the cache holds;
# - each hit is a FRESH detached ``User`` built from plain column values, so no ORM
#   instance is shared between requests or sessions;
# - only rows read (or provisioned) and COMMITTED by ``load_authenticated_user`` are
#   stored, so a hit never stands in for an uncommitted first sighting.
#
# Seller and staff tokens are untouched: they read (and commit) the row every request.
_reviewer_users: IdentityCache[uuid.UUID, dict[str, object]] = IdentityCache()


def forget_cached_reviewer_users() -> None:
    """Drop every cached reviewer users row (tests)."""
    _reviewer_users.clear()


def _user_values(user: User) -> dict[str, object]:
    mapper = sa_inspect(User)
    return {attr.key: getattr(user, attr.key) for attr in mapper.column_attrs}


def _detached_user(values: dict[str, object]) -> User:
    user = User(**values)
    make_transient_to_detached(user)
    return user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: validates Supabase JWT → returns authenticated User.

    P32-A (D42): a partner reviewer's token goes through the reviewer gate
    first -- route allowlist, account expiry / revocation, sign-in audit --
    so a refused reviewer request never reaches the ``users`` read or the route.
    P69: an admitted reviewer's ``users`` row is then served from a 30 s cache
    keyed by the verified ``sub`` (see ``_reviewer_users`` above).
    """
    token = await verify_bearer_token(credentials)
    await enforce_reviewer_gate(request, session, token)
    if not token.is_reviewer:
        return await load_authenticated_user(session, token)
    cached = _reviewer_users.get(token.user_id)
    if cached is not None and cached.get("id") == token.user_id:
        return _detached_user(cached)
    user = await load_authenticated_user(session, token)
    if user.id == token.user_id:
        _reviewer_users.put(token.user_id, _user_values(user))
    return user
