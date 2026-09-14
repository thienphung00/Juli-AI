import logging
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwt import verify_supabase_jwt
from juli_backend.database import NotFound, User, UsersRepo
from juli_backend.database.database import get_session

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """FastAPI dependency: validates Supabase JWT → returns authenticated User."""
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

    try:
        # The scoped read (#1691): `users` is policy-gated on a GUC that
        # authentication has not set yet, and the repository owns knowing that.
        # ADR-085 decision 2 keeps the tenant seam out of this module, so the
        # scope lives in UsersRepo, not here.
        user = await UsersRepo(session).get_for_authentication(user_id)
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
    await session.commit()
    return user
