# Module: auth

## Responsibility
Handles authentication: Supabase phone-OTP login, JWT verification,
FastAPI dependency injection for extracting authenticated user context,
and TikTok OAuth lifecycle (authorization, shop provisioning, token refresh).

## Public Interface
- `SupabaseAuth(supabase_url, anon_key, client?) -> SupabaseAuth` — Supabase Auth API client
- `SupabaseAuth.send_otp(phone) -> None` — sends OTP to Vietnamese phone number
- `SupabaseAuth.verify_otp(phone, token) -> dict` — verifies OTP, returns session with `access_token`
- `verify_supabase_jwt(token, secret) -> dict` — decodes and validates a Supabase JWT
- `get_current_user` — FastAPI dependency: validates JWT, returns `User` with shops
- `TikTokOAuthService(tiktok_auth, session, redirect_uri, app_secret)` — TikTok OAuth lifecycle manager
- `TikTokOAuthService.initiate_oauth(user_id) -> str` — returns TikTok authorization URL with signed state
- `TikTokOAuthService.handle_callback(code, state) -> Shop` — exchanges code, provisions shop + credential
- `TikTokOAuthService.refresh_tokens(shop_id) -> TikTokCredential` — proactively refreshes tokens before expiry
- `Unauthorized` — raised on auth failures (missing/expired/invalid JWT, invalid OAuth state)

## Dependencies
- `data` — `User`, `Shop`, `TikTokCredential`, `UsersRepo`, `ShopsRepo`, `TikTokCredentialRepo`, `NotFound`, `get_session`
- `integrations/tiktok` — `TikTokAuth` (OAuth URL generation, code exchange, token refresh)
- `pyjwt[crypto]` — JWT decoding
- `httpx` — Supabase Auth API calls

## Invariants
- `get_current_user` always raises HTTP 401 on auth failure — never returns None
- JWT verification checks both signature and expiry
- All Supabase API errors are wrapped in `Unauthorized`
- OAuth state parameter is HMAC-signed with `app_secret`; tampered states raise `Unauthorized`
- `TikTokOAuthService` does not persist tokens directly — delegates to `TikTokCredentialRepo`
- Token refresh is proactive: triggers when within `REFRESH_BUFFER` (30 min) of expiry
- Reconnecting the same TikTok shop (same `open_id`) reuses the existing `Shop` record

## Owners
- domain: auth
- code: src/auth/
