import logging

import jwt as pyjwt

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwks import JwksClient, JwksUnavailableError, supabase_jwks_url

logger = logging.getLogger(__name__)

#: Issue #1282 -- the deployed Supabase project issues ES256 (asymmetric)
#: tokens; the legacy shared-secret HS256 flow is kept as a second,
#: independently-verified path rather than replaced, because the owner may
#: re-enable Supabase's legacy shared secret in the dashboard as a stopgap
#: (see the issue's "Whether to keep HS256" discussion). This is the *only*
#: place either algorithm name is accepted -- `verify_supabase_jwt` checks
#: membership here before dispatching to `_verify_hs256`/`_verify_es256`, so
#: an `alg` outside this set (including `"none"`) is rejected before either
#: verifier ever runs, and `alg: none` can never reach `pyjwt.decode` at all.
_SUPPORTED_ALGORITHMS = frozenset({"HS256", "ES256"})

#: Lazily-constructed, module-level singleton -- one JWKS cache per process,
#: reused across requests (this is *why* JwksClient caches: fetching per
#: request would be a network call in the auth path). Tests inject a stub
#: by setting this module attribute directly, matching the pattern already
#: used for `banned_patterns_module.BANNED_PATTERNS_JSON_PATH` elsewhere in
#: this codebase.
_default_jwks_client: JwksClient | None = None


def _get_jwks_client() -> JwksClient:
    global _default_jwks_client
    if _default_jwks_client is None:
        _default_jwks_client = JwksClient(supabase_jwks_url())
    return _default_jwks_client


async def verify_supabase_jwt(token: str, secret: str) -> dict:
    """Decode and validate a Supabase-issued JWT (HS256 or ES256, audience=authenticated).

    Dispatches on the token's own (unverified) `alg` header to decide which
    verifier to run -- HS256 against `secret`, ES256 against the project's
    JWKS, selected by the token's `kid`. Each branch still passes an
    explicit, single-entry `algorithms=[...]` to `pyjwt.decode`, so the
    dispatch itself never widens what either verifier will actually accept
    (no HS256-vs-ES256 key-confusion path). Any `alg` outside
    `_SUPPORTED_ALGORITHMS` -- including `"none"` -- is rejected before
    either verifier runs.

    Async because the ES256 path may need to fetch/refresh JWKS over the
    network (`core/security/jwks.py`); the HS256 path is synchronous
    underneath but the function stays async uniformly for one call
    signature at the single call site (`dependencies.py::get_current_user`,
    already async).
    """
    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", extra={"error": str(exc)})
        raise Unauthorized(f"Invalid token: {exc}")

    alg = header.get("alg")
    if alg not in _SUPPORTED_ALGORITHMS:
        logger.warning("jwt_unsupported_alg", extra={"alg": alg})
        raise Unauthorized(f"Unsupported algorithm: {alg}")

    if alg == "HS256":
        return _verify_hs256(token, secret)
    return await _verify_es256(token, header)


def _verify_hs256(token: str, secret: str) -> dict:
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except pyjwt.ExpiredSignatureError:
        logger.warning("jwt_expired")
        raise Unauthorized("Token has expired")
    except pyjwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", extra={"error": str(exc)})
        raise Unauthorized(f"Invalid token: {exc}")


async def _verify_es256(token: str, header: dict) -> dict:
    kid = header.get("kid")
    if not kid:
        logger.warning("jwt_invalid", extra={"error": "ES256 token has no kid"})
        raise Unauthorized("Invalid token: missing kid")

    try:
        signing_key = await _get_jwks_client().get_signing_key(kid)
    except JwksUnavailableError as exc:
        # Distinct log event from jwt_invalid/jwt_expired below and from
        # dependencies.py's own jwt_rejected wrapper -- a JWKS outage must
        # be distinguishable in the logs from a bad/forged token, not just
        # collapse into the same "auth failed" line (issue #1282 AC). The
        # caller-facing body stays the same opaque 401 either way (#902 /
        # ADR-061) -- this is a fail-closed outcome, not fail-open.
        logger.warning("jwt_jwks_unavailable", extra={"error": str(exc)})
        raise Unauthorized("Authentication verification unavailable") from exc

    try:
        return pyjwt.decode(token, signing_key.key, algorithms=["ES256"], audience="authenticated")
    except pyjwt.ExpiredSignatureError:
        logger.warning("jwt_expired")
        raise Unauthorized("Token has expired")
    except pyjwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", extra={"error": str(exc)})
        raise Unauthorized(f"Invalid token: {exc}")
