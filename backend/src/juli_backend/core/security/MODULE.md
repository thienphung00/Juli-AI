# Module: core/security

## Responsibility
Handles authentication: JWT verification (HS256 shared-secret and ES256 via Supabase
JWKS), TikTok OAuth lifecycle, and FastAPI auth dependencies.

## Public Interface

Import from the package root only:

```python
from juli_backend.core.security import get_current_user, TikTokOAuthService, ...
```

Deep imports of ``credential_resolver``, ``jwt``, ``dependencies``, etc. are internal
unless re-exported below.

### Package facade (`__init__.py`)

Matches ``__all__`` — re-exports only:

- ``get_current_user`` — FastAPI dependency: validates JWT → returns authenticated ``User``.
  A verified JWT for a `sub` with no `users` row provisions one (#1906) via
  `UsersRepo.get_for_authentication` → `get_or_create` before returning — never before
  verification succeeds, and never a shop, capability, or credential alongside it.
- ``TikTokOAuthService`` — TikTok Shop OAuth token exchange and lifecycle
- ``Unauthorized`` — raised when auth fails
- ``verify_supabase_jwt`` — async; decodes and validates a Supabase JWT (HS256 or ES256,
  dispatched on the token's own `alg` header — see `jwt.py`'s module-level
  `_SUPPORTED_ALGORITHMS`; any other `alg`, including `none`, is rejected before either
  verifier runs)
- ``supabase_jwks_url`` — derives the JWKS endpoint from `SUPABASE_URL`, failing closed
  (``JwksUnavailableError``) when it is missing a scheme or shaped like the Postgres
  `db.*.supabase.co` host rather than the project API URL (issue #1282 — that exact
  misconfiguration is why the deployed host's auth broke while `SUPABASE_JWT_SECRET` was
  present and boot was green)
- ``resolve_read_credential_for_shop(session, shop_id)`` — the credential **that shop
  owns** which may serve a read (#1365). Keyed on the owning shop AND the row's
  capability: a ``SELLER_CONNECT`` credential reads for its own shop and nothing else,
  is returned exactly as stored (never promoted to ``PRODUCTION_READ``), and a
  ``SANDBOX_WRITE`` row is unreachable through it. A row carrying a merchant id that a ``sandbox_write`` row also carries is skipped (read from the DB, P61-G). There is **no fallback** to any
  merchant — that fallback is how one merchant's data would be
  read under another merchant's shop. Holds no state between calls
- ``NoReadCredentialForShop`` — raised when the shop owns nothing read-capable. Subclasses
  ``database.exceptions.NotFound`` so existing route boundaries answer 404, making a
  nonexistent shop and a cross-tenant one indistinguishable (never 403, no existence
  oracle). It replaces the silent ``None`` the read path used to return, which let a newly
  connected seller be scored over an empty database with no error anywhere
- ``resolve_write_credential_for_shop(session, shop_id)`` — fast track P61-B (D71.2): the
  credential **that shop owns** its production writes are signed with. The capabilities it
  considers are ``PRODUCTION_WRITE_CREDENTIAL_CAPABILITIES`` (the shop's own OAuth rows,
  ``READ_CAPABILITIES``); it refuses a row without a merchant id and a row holding a merchant a ``sandbox_write`` row carries, and has no fallback. ``NoWriteCredentialForShop`` (a ``NotFound``) when nothing
  qualifies. Being resolvable never makes a write possible: the ADR-085 gates in
  ``services/execution/production_write_resolver.py`` decide that
- ``NoWriteCredentialForShop`` — the shop owns nothing write-capable (a ``NotFound``, P61-B)
- ``PRODUCTION_WRITE_CREDENTIAL_CAPABILITIES`` — the capabilities a shop's own production
  write may be signed with (P61-B); ``SANDBOX_WRITE`` deliberately absent
- ``resolve_sandbox_write_credential(session)`` — the sandbox write-validation credential,
  found by its **capability** (``sandbox_write``), never a configured merchant id (P61-G,
  D71.6). The cross-tenant lookup is migration 099's ``enumerate_sandbox_write_credentials()``
  (``SECURITY DEFINER``: shop id, merchant id, one ``collides`` boolean); the token is
  re-read under the owning shop's scope. Raises ``NotFound`` when none exists, and
  ``SandboxCredentialRefused`` when the row has no merchant id or *collides* with a
  non-sandbox credential (same merchant id or shop cipher) — the 2026-08-18 defect caught
  at resolve time from the credentials alone. Never falls back to a production credential
- ``sandbox_write_merchant_ids(session)`` — merchant ids carried by ``sandbox_write`` rows
  (from the DB); production resolvers and factories refuse them
- ``TikTokOAuthService.provision_shop_and_credentials(..., capability=None)`` — the merchant
  id is the OAuth ``open_id``; the capability is the caller's, else the one this shop's
  existing credential for that merchant already has, else ``seller_connect``
- ``mint_oauth_state(user_id, *, secret, flow, now=None) -> str`` — the signed OAuth
  ``state`` (#1970). Wire format unchanged from what this package already produced:
  ``base64url(json) "." hex(HMAC-SHA256(secret, base64url))``. The payload gains
  ``flow`` and ``iat``, so a state is accepted only by the handshake it was minted for
  and only inside its TTL. Exported at this package root, not deep-imported:
  ``services/tiktok/oauth.py`` is capped at cross-package depth 2 by
  ``.importlinter.toml``
- ``verify_oauth_state(state, *, secret, expected_flow, ttl_seconds=…, now=None) -> OAuthState``
  — signature first, then payload, then flow, then freshness. Raises ``Unauthorized``
  for every rejection; never returns a partially-trusted value. There is no single-use
  nonce ledger (it would need storage this slice has no migration authority for), so a
  state can be presented twice inside its TTL — bounded by TikTok's single-use
  authorization code and by ``provision_shop_and_credentials`` refusing to rebind a shop
  owned by someone else. See the module docstring for the full residual
- ``OAuthState`` — the verified payload (``user_id``, ``flow``, ``nonce``, ``issued_at``);
  only ever constructed after the HMAC checked out
- ``SELLER_CONNECT_FLOW`` — flow label for the seller-initiated "connect my TikTok Shop"
  handshake, minted by ``GET /v1/auth/tiktok/start`` and required at the callback
- ``DEFAULT_STATE_TTL_SECONDS`` — 600. Long enough to read TikTok's consent screen,
  short enough that a state in a log or browser history is stale before anyone reads it
- ``CLOCK_SKEW_TOLERANCE_SECONDS`` — 60. Tolerance for a forward-dated ``iat``; beyond
  it the state is refused rather than trusted, so skew cannot extend the window
- ``JwksUnavailableError`` — raised when the JWKS key set cannot be fetched/parsed, or a
  `kid` is still absent after one refetch attempt; fails closed (401), logged under
  `jwt_jwks_unavailable`, distinguishable from a bad token's `jwt_invalid`/`jwt_expired`

### Verified identity claims (`claims.py`)

Not on the package facade: the only caller is `dependencies.py`, one module over, and
widening `__all__` for it would invite a repository or a service to reach for a Supabase
payload directly — which is exactly what this seam exists to prevent.

- ``VerifiedIdentity`` — frozen value carrying ``email`` and ``display_name``, both
  optional, with no vendor shape left in it. What crosses from `core/security` into
  `repositories/` (#1973), so `UsersRepo` never learns what a Supabase payload looks like
- ``verified_identity(payload)`` — reads the seller's claims out of a payload
  ``verify_supabase_jwt`` has ALREADY checked; it re-validates nothing and must never be
  handed an unverified decode. The email is taken **only** alongside a true
  ``email_verified`` (top-level claim wins over the ``user_metadata`` copy; both the
  boolean and the string ``"true"`` count, anything else does not) — storing an address
  no provider verified would repeat #1972's fabricated-phone mistake in a new column.
  The display name is taken regardless: it is a label shown back to the seller, not a
  channel anyone can be reached on. Values are trimmed to the columns that hold them
  (320 / 100), so a long name cannot fail the INSERT inside the auth path

### Partner reviewer gate port (fast track P32-A, D42)

- ``VerifiedToken`` — also carries ``reviewer_platform`` (from ``app_metadata`` ``juli_role`` /
  ``juli_platform``, read by ``claims.reviewer_platform``; ``REVIEWER_ROLE``,
  ``REVIEWER_ROLE_CLAIM``, ``REVIEWER_PLATFORM_CLAIM``, ``UNKNOWN_PLATFORM``) and ``session_id``
  (``claims.session_id``).
- ``ReviewerGate`` / ``bind_reviewer_gate`` / ``enforce_reviewer_gate`` — ``get_current_user``
  runs the bound gate for a reviewer token before the ``users`` read; with no gate bound a
  reviewer is refused (403). ``REVIEWER_DENIED_HEADER`` names the refusal.

## Dependencies
- `juli_backend.database` — `UsersRepo`, `User` model, and `tenant_context.with_shop_scope`
  (#2019: `credential_resolver` enumerates the configured merchant's owning shop through
  migration 061's `SECURITY DEFINER` function, then does every actual credential read and the
  lazy refresh inside that shop's scope — ADR-089 decisions 2-4)
- `juli_backend.integrations.tiktok` — `TikTokAuth`, merchant context helpers
- Supabase JWT secret (env `SUPABASE_JWT_SECRET`) for the HS256 verification path
- Supabase project API URL (env `SUPABASE_URL`, e.g. `https://<project-ref>.supabase.co`)
  for the ES256/JWKS verification path — **not** the Postgres connection host
  `DATABASE_URL` uses

## JWKS caching (`jwks.py`)

`JwksClient` caches the fetched key set (`ttl_seconds`, default 300s) so the JWKS
endpoint is not hit on every authenticated request. An unknown `kid` triggers at most
one refetch per cooldown window (`min_refetch_interval_seconds`, default 10s) — an
`asyncio.Lock` alone stops a *concurrent* stampede, but only the cooldown timestamp
stops a *sequential* one (repeated lookups of the same still-missing `kid` over time). A
failed refetch never wipes previously-cached keys. One process-lifetime singleton lives
in `jwt.py::_get_jwks_client()`; tests override it by setting the module attribute
directly (`monkeypatch.setattr(jwt_module, "_default_jwks_client", ...)`).

## Notes
- Frontend demo login (`NEXT_PUBLIC_UI_ONLY=1`) uses a local session token; no OTP endpoints.
- TikTok OAuth callback is served at `/v1/auth/tiktok/callback` (see issue #259).
- `get_current_user` is the one place in this module that commits (#1906) — right after
  resolving/provisioning the user, before the route runs. A first-sighting insert has
  nothing downstream guaranteed to commit it (`GET /v1/shops` never does), and the
  concurrency proof in `tests/integration/test_google_identity_provisioning.py` depends
  on it: the losing concurrent request's blocked `INSERT` only unblocks, into a handled
  `IntegrityError`, once the winner commits.
