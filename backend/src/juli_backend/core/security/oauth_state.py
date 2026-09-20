"""The signed OAuth ``state`` parameter: one mint, one verifier (issue #1970).

``state`` is the only thing that tells the callback *which signed-in seller*
authorized a shop. Everything about the owner binding rests on it, so it is a
security boundary rather than an opaque correlation token: it is HMAC-signed
with the app secret and verified before a single byte of the payload is
believed.

**The wire format is unchanged** from what ``core/security/tiktok_oauth.py``
already minted and three modules already verified::

    base64url( json payload ) "." hex( HMAC-SHA256(app_secret, base64url_part) )

Three near-identical copies of that verifier had drifted apart across
``core/security/tiktok_oauth.py``, ``services/tiktok/oauth.py`` and
``services/tiktok/business_advertiser_oauth.py``. This module is the primitive
the Shop flow now shares, so a hardening lands once instead of two-thirds of
the time. It deliberately does NOT invent new crypto: same construction, same
digest, same ``hmac.compare_digest``.

What #1970 adds to the payload, and why:

``flow``
    Which handshake the state was minted for. A state is only accepted by the
    flow it was issued for, so one flow's state cannot be replayed into
    another's callback even where the two share an app secret.

``iat``
    Unix seconds at mint. Verification refuses a state older than
    ``ttl_seconds`` (default 10 minutes, comfortably longer than a human
    consent screen). Before this, a signed state was valid **forever** — a
    state captured from a browser history, a proxy log or a referrer header
    stayed usable indefinitely.

**What this does NOT do, stated plainly.** There is no server-side single-use
nonce ledger, so a state *can* be presented twice inside its TTL. Adding one
needs durable storage this slice has no migration authority for. Two things
bound the consequence today and neither is this module's doing:

1. The vendor authorization ``code`` presented alongside it is single-use at
   TikTok, so the second presentation has no code left to exchange.
2. ``TikTokOAuthService.provision_shop_and_credentials`` refuses to rebind a
   shop that already belongs to a different user (``Unauthorized``,
   ``tiktok_shop_already_claimed``).

The residual is therefore a same-user re-provision inside a ten-minute window,
not a cross-tenant rebinding. A ``jti`` ledger remains the real fix.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass

from juli_backend.core.security.exceptions import Unauthorized

__all__ = [
    "DEFAULT_STATE_TTL_SECONDS",
    "SELLER_CONNECT_FLOW",
    "OAuthState",
    "mint_oauth_state",
    "verify_oauth_state",
]

#: Flow label for the seller-initiated "connect my TikTok Shop" handshake —
#: ``GET /v1/auth/tiktok/start`` mints it, ``GET /v1/auth/tiktok/callback``
#: requires it.
SELLER_CONNECT_FLOW = "seller_connect"

#: How long a minted state stays acceptable. Long enough for a seller to read
#: TikTok's consent screen and click through; short enough that a state leaked
#: into a log or a browser history is stale by the time anyone reads it.
DEFAULT_STATE_TTL_SECONDS = 600

#: Tolerance for a state whose ``iat`` is in the future. Clock skew between the
#: minting and verifying process is real (they need not be the same host); a
#: state from further ahead than this is refused rather than trusted.
CLOCK_SKEW_TOLERANCE_SECONDS = 60


@dataclass(frozen=True)
class OAuthState:
    """A verified state payload. Only ever constructed after the HMAC checked out."""

    user_id: uuid.UUID
    flow: str
    nonce: str
    issued_at: int


def _sign(encoded: str, secret: str) -> str:
    return hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()


def mint_oauth_state(
    user_id: uuid.UUID,
    *,
    secret: str,
    flow: str,
    now: int | None = None,
) -> str:
    """Return a signed state binding ``user_id`` to ``flow`` at this instant.

    ``secret`` must be the same secret the verifying side holds; for the TikTok
    Shop flow that is ``TIKTOK_APP_SECRET``. An empty secret is refused rather
    than used to produce a signature anyone can reproduce.
    """
    if not secret:
        raise ValueError("Refusing to sign OAuth state with an empty secret")

    payload = json.dumps(
        {
            "user_id": str(user_id),
            "flow": flow,
            "nonce": secrets.token_urlsafe(16),
            "iat": int(time.time()) if now is None else int(now),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{encoded}.{_sign(encoded, secret)}"


def verify_oauth_state(
    state: str,
    *,
    secret: str,
    expected_flow: str,
    ttl_seconds: int = DEFAULT_STATE_TTL_SECONDS,
    now: int | None = None,
) -> OAuthState:
    """Verify signature, flow and freshness, then return the payload.

    Raises :class:`Unauthorized` — never returns a partially-trusted value — on
    a malformed, unsigned, wrongly-signed, wrong-flow or expired state. The
    signature is checked **before** the payload is parsed, so an attacker
    controls no field this function has already acted on.
    """
    if not secret:
        raise Unauthorized("OAuth state cannot be verified: signing secret is unset")

    parts = state.split(".", 1)
    if len(parts) != 2:
        raise Unauthorized("Invalid OAuth state")

    encoded, signature = parts
    if not hmac.compare_digest(signature, _sign(encoded, secret)):
        raise Unauthorized("Invalid OAuth state signature")

    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded))
        if not isinstance(payload, dict):
            raise ValueError("state payload is not an object")
        user_id = uuid.UUID(payload["user_id"])
    except (binascii.Error, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise Unauthorized(f"Malformed OAuth state: {exc}") from exc

    flow = payload.get("flow")
    if flow != expected_flow:
        # Named generically on purpose: the caller learns the state is not
        # usable here, not which flow it was minted for.
        raise Unauthorized("OAuth state was not issued for this flow")

    issued_at = payload.get("iat")
    if not isinstance(issued_at, int) or isinstance(issued_at, bool):
        raise Unauthorized("OAuth state carries no usable issue time")

    current = int(time.time()) if now is None else int(now)
    if issued_at > current + CLOCK_SKEW_TOLERANCE_SECONDS:
        raise Unauthorized("OAuth state is not yet valid")
    if current - issued_at > ttl_seconds:
        raise Unauthorized("OAuth state has expired")

    nonce = payload.get("nonce")
    return OAuthState(
        user_id=user_id,
        flow=flow,
        nonce=nonce if isinstance(nonce, str) else "",
        issued_at=issued_at,
    )
