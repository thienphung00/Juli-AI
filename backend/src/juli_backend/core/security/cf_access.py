"""Cloudflare Access JWT verification for the ops console (fast track P16, D25.1).

``ops.app-juli.com`` sits behind two gates: Cloudflare Access (Google IdP,
``@app-juli.com`` only) and a staff row in the database. This module is the
first gate's server-side half. Cloudflare Access forwards every request it lets
through with a signed JWT in the ``Cf-Access-Jwt-Assertion`` header; an
origin that only *trusts* the edge would be open to anyone who reaches it
directly, so ``/v1/ops/*`` verifies that JWT itself:

- signature (RS256) against the team's public keys at
  ``https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`` (a JWKS; the
  ``JwksClient`` that already caches Supabase's keys is reused),
- ``aud`` = the Access application's AUD tag (``CF_ACCESS_AUD``),
- ``iss`` = the team domain (``CF_ACCESS_TEAM_DOMAIN``),
- ``exp`` / ``nbf``,
- ``email`` present and in the allowed domain (``OPS_ALLOWED_EMAIL_DOMAIN``,
  default ``app-juli.com``) -- defence in depth behind the Access policy.

FAIL CLOSED. A missing header, a missing configuration value, an unreachable
key set and a bad token all deny. The ONLY bypass is ``OPS_CF_ACCESS_BYPASS=1``
and it is refused when ``ENVIRONMENT=production`` (tests and local dev only).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt as pyjwt

from juli_backend.core.config.runtime import is_production
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwks import JwksClient, JwksUnavailableError

logger = logging.getLogger(__name__)

CF_ACCESS_HEADER = "Cf-Access-Jwt-Assertion"
_CERTS_PATH = "/cdn-cgi/access/certs"
_DEFAULT_ALLOWED_DOMAIN = "app-juli.com"

#: one cached key set per team URL; tests replace it.
_clients: dict[str, JwksClient] = {}


@dataclass(frozen=True)
class AccessIdentity:
    """What the verified Access JWT says about the caller."""

    email: str | None
    bypassed: bool


@dataclass(frozen=True)
class AccessConfig:
    team_url: str
    audience: str
    allowed_domain: str


def bypass_enabled() -> bool:
    """``OPS_CF_ACCESS_BYPASS=1`` outside production only."""
    if os.environ.get("OPS_CF_ACCESS_BYPASS", "").strip() != "1":
        return False
    if is_production():
        logger.error("ops_cf_access_bypass_refused_in_production")
        return False
    return True


def team_url(raw: str) -> str:
    """``myteam`` / ``myteam.cloudflareaccess.com`` / ``https://…`` → ``https://host``."""
    value = raw.strip().rstrip("/")
    if not value:
        raise Unauthorized("CF_ACCESS_TEAM_DOMAIN is empty")
    if "://" not in value:
        if "." not in value:
            value = f"{value}.cloudflareaccess.com"
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
        raise Unauthorized("CF_ACCESS_TEAM_DOMAIN is not a bare https origin")
    return f"https://{parsed.hostname}"


def load_config() -> AccessConfig:
    team = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip()
    aud = os.environ.get("CF_ACCESS_AUD", "").strip()
    if not team or not aud:
        raise Unauthorized("Cloudflare Access is not configured")
    domain = (
        os.environ.get("OPS_ALLOWED_EMAIL_DOMAIN", "").strip().lower() or _DEFAULT_ALLOWED_DOMAIN
    )
    return AccessConfig(team_url=team_url(team), audience=aud, allowed_domain=domain)


def _client_for(team: str) -> JwksClient:
    client = _clients.get(team)
    if client is None:
        client = JwksClient(team + _CERTS_PATH)
        _clients[team] = client
    return client


async def verify_access_jwt(
    token: str | None, config: AccessConfig | None = None
) -> AccessIdentity:
    """Verify a ``Cf-Access-Jwt-Assertion`` value. Raises ``Unauthorized`` on any doubt."""
    if bypass_enabled():
        return AccessIdentity(email=None, bypassed=True)
    if not token:
        raise Unauthorized("Missing Cloudflare Access assertion")
    cfg = config or load_config()
    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.InvalidTokenError as exc:
        raise Unauthorized(f"Invalid Access token: {exc}") from exc
    if header.get("alg") != "RS256":
        raise Unauthorized(f"Unsupported Access token algorithm: {header.get('alg')}")
    kid = header.get("kid")
    if not kid:
        raise Unauthorized("Access token has no kid")
    try:
        key = await _client_for(cfg.team_url).get_signing_key(kid)
    except JwksUnavailableError as exc:
        logger.warning("ops_cf_access_certs_unavailable", extra={"error": str(exc)})
        raise Unauthorized("Access verification unavailable") from exc
    try:
        claims = pyjwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=cfg.audience,
            issuer=cfg.team_url,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except pyjwt.InvalidTokenError as exc:
        raise Unauthorized(f"Invalid Access token: {exc}") from exc
    email = str(claims.get("email") or "").strip().lower()
    if not email or not email.endswith("@" + cfg.allowed_domain):
        raise Unauthorized("Access token email is outside the allowed domain")
    return AccessIdentity(email=email, bypassed=False)
