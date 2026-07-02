# Module: identity/infrastructure/auth

## Responsibility
Handles authentication: JWT verification, TikTok OAuth lifecycle, and FastAPI auth dependencies.

## Public Interface
- `verify_supabase_jwt(token, secret) -> dict` — decodes and validates a Supabase JWT
- `get_current_user` — FastAPI dependency: validates JWT → returns authenticated `User`
- `TikTokOAuthService` — TikTok Shop OAuth token exchange and lifecycle
- `Unauthorized` — raised when auth fails

## Dependencies
- `shared.utils.data` — `UsersRepo`, `User` model
- Supabase JWT secret (env `SUPABASE_JWT_SECRET`) for protected route validation

## Notes
- Frontend demo login (`NEXT_PUBLIC_UI_ONLY=1`) uses a local session token; no OTP endpoints.
- TikTok OAuth callback is served at `/v1/auth/tiktok/callback` (see issue #259).
