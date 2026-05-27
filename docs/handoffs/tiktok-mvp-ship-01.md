# Objective
Ship TikTok MVP foundation: data layer, auth, and API bootstrap (Issues #24, #28, #29, #30, #33).

# Completed
- PR #48: `feature/24-data-core-schema` → `main` — Data core schema + repository layer
- PR #49: `feature/28-commerce-analytics` → `feature/24` — Commerce + analytics tables
- PR #50: `feature/29-auth-phone-otp` → `feature/24` — Phone-OTP login + JWT middleware
- PR #51: `feature/30-tiktok-oauth` → `feature/29` — TikTok OAuth + shop provisioning
- PR #52: `feature/33-api-bootstrap` → `feature/29` — API bootstrap + shop endpoints
- Issues closed: #24, #28, #29, #30, #31, #33, #41, #42
- CI: all 172 tests green (validated pre-ship)

# PR Dependency Graph
```
main
└── PR #48 (#24 data core)  [base]
    ├── PR #49 (#28 commerce)
    └── PR #50 (#29 auth)
        ├── PR #51 (#30 tiktok-oauth)
        └── PR #52 (#33 api)
```
Merge order: #48 → (#49 + #50 in parallel) → (#51 + #52 in parallel)

# Decisions
- Stacked PRs to keep each under 400 lines and reviewable in isolation
- Core data models split from commerce/analytics to match issue boundaries
- TikTok integration's `auth.py` included in #30 PR (consumed dependency)
- Requirements.txt dependencies added incrementally per PR

# Modules
- `data` (created in #24, extended in #28)
- `auth` (created in #29, extended in #30)
- `api` (created in #33)
- `integrations/tiktok` (auth.py added in #30)

# Interfaces Changed
- `src/data`: User, Shop, TikTokCredential, UsersRepo, ShopsRepo, TikTokCredentialRepo
- `src/data` (#28): Order, Product, InventoryItem, Settlement, Creator, Livestream, AlertConfig, AlertHistory, Recommendation, ShopScopedRepo[T]
- `src/auth`: SupabaseAuth, verify_supabase_jwt, get_current_user, Unauthorized
- `src/auth` (#30): TikTokOAuthService
- `src/api`: create_app(), GET /v1/shops, GET /v1/shops/me, X-Shop-Id header scoping

# Remaining Work
- Review and merge PRs in dependency order
- Post-merge: retarget #49, #50 to main after #48 merges; retarget #51, #52 to main after #50 merges

# Risks
- Stacked PRs require merge-order discipline
- TikTok OAuth requires sandbox credentials for E2E validation

# Tests
- 172 total tests passing (15 core data + 19 commerce + 9 auth + 10 OAuth + 4 API + 115 tiktok integration)

# Required Context Next Session
- Merge PRs in order: #48 first, then #49 + #50, then #51 + #52
- After merge, remaining unshipped issues from the MVP backlog

# Bootstrap Prompt
"TikTok MVP foundation shipped. See docs/handoffs/tiktok-mvp-ship-01.md for
PR dependency graph and merge order."
