import logging

import jwt as pyjwt

from juli_backend.core.security.exceptions import Unauthorized

logger = logging.getLogger(__name__)


def verify_supabase_jwt(token: str, secret: str) -> dict:
    """Decode and validate a Supabase-issued JWT (HS256, audience=authenticated)."""
    try:
        return pyjwt.decode(
            token, secret, algorithms=["HS256"], audience="authenticated"
        )
    except pyjwt.ExpiredSignatureError:
        logger.warning("jwt_expired")
        raise Unauthorized("Token has expired")
    except pyjwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", extra={"error": str(exc)})
        raise Unauthorized(f"Invalid token: {exc}")
