# Module: ios

## Responsibility
Native SwiftUI iOS application providing Supabase phone-OTP authentication,
secure JWT-based API communication, shop selection, and a daily value loop
navigation shell for TikTok Shop sellers.

## Public Interface
- `AuthService` — Supabase phone-OTP login/verification, JWT lifecycle
  - `sendOTP(phone:)` — sends OTP to Vietnamese phone number via Supabase
  - `verifyOTP(phone:code:)` — verifies OTP, returns `AuthSession`, stores JWT in Keychain
  - `logout()` — clears session and Keychain
  - `restoreSession()` — attempts to restore JWT from Keychain on launch
- `KeychainService` — Secure storage for JWT and sensitive tokens
  - `save(key:data:)`, `load(key:)`, `delete(key:)`
- `APIClient` — URLSession-based HTTP client, auto-attaches Bearer JWT
  - `get(path:shopId:)` — GET request to `/v1/*` endpoints
- `OfflineCacheService` — Disk-backed cache with staleness tracking
  - `cache(key:value:)`, `retrieve(key:type:)`, `clear(key:)`
- `DailyLoopTab` — Enum defining the five daily loop screens
- App views: `LoginView`, `HomeView`, `DailyLoopView` (shell placeholders)

## Dependencies
- `api` (consumed, read-only) — REST endpoints: `GET /v1/shops`, `GET /v1/shops/me`
- `auth` (consumed, read-only) — Supabase phone-OTP contract, JWT format
- Apple frameworks: SwiftUI, Foundation, Security (Keychain)

## Invariants
- JWT is never stored in UserDefaults — always Keychain via `KeychainService`
- Every `/v1/*` request includes `Authorization: Bearer <jwt>` header
- Every shop-scoped request includes `X-Shop-Id` header
- Offline cache entries carry a `cachedAt` timestamp; UI shows stale indicator when >5 min old
- No push notification registration in this slice (deferred to #46)
- No UIKit storyboards — pure SwiftUI single-target app

## Owners
- domain: ios
- code: ios/
