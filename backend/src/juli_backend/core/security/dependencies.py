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
    """FastAPI dependency: validates Supabase JWT → returns authenticated User.

    For anonymous users (whose sub is not yet in the Users table), creates
    a user record with is_anonymous=True. This allows Supabase anonymous
    sign-in to mint real JWTs for distinct anonymous identities, each with
    their own audit trail.
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

    try:
        return await UsersRepo(session).get(user_id)
    except NotFound:
        # If user doesn't exist, only auto-create if the JWT claims is_anonymous=true.
        # This prevents unrecognized tokens (deleted users, replayed tokens, other projects'
        # JWTs sharing the issuer) from being silently converted into new account creation.
        # Issue #1313: each anonymous JWT gets a distinct user identity for audit purposes.
        if not payload.get("is_anonymous"):
            logger.warning(
                "jwt_unrecognized_subject",
                extra={"sub": str(user_id), "is_anonymous": payload.get("is_anonymous")},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired credentials",
            )

        # Anonymous users are identified by phone == "anonymous" (no real phone number).
        user = User(
            id=user_id,
            phone="anonymous",
            display_name="Anonymous User",
        )
        session.add(user)
        await session.flush()
        return user
