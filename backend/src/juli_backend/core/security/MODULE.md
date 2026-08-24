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

- ``get_current_user`` — FastAPI dependency: validates JWT → returns authenticated ``User``
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
- ``JwksUnavailableError`` — raised when the JWKS key set cannot be fetched/parsed, or a
  `kid` is still absent after one refetch attempt; fails closed (401), logged under
  `jwt_jwks_unavailable`, distinguishable from a bad token's `jwt_invalid`/`jwt_expired`

## Dependencies
- `juli_backend.database` — `UsersRepo`, `User` model
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
