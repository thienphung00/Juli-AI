# Module: core/security

## Responsibility
Handles authentication: JWT verification, TikTok OAuth lifecycle, and FastAPI auth dependencies.

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
- ``verify_supabase_jwt`` — decodes and validates a Supabase JWT

## Dependencies
- `juli_backend.database` — `UsersRepo`, `User` model
- `juli_backend.integrations.tiktok` — `TikTokAuth`, merchant context helpers
- Supabase JWT secret (env `SUPABASE_JWT_SECRET`) for protected route validation

## Notes
- Frontend demo login (`NEXT_PUBLIC_UI_ONLY=1`) uses a local session token; no OTP endpoints.
- TikTok OAuth callback is served at `/v1/auth/tiktok/callback` (see issue #259).
