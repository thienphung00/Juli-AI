# Handoff: focus → tdd — Issue #123

## Issue

- **#123** — Retire legacy creator-matching routes
- **Parent:** #113 (MVP 1.0 PRD)
- **Blocked by:** #118–#121 (all closed)

### Acceptance criteria

- Legacy creator-matching routes redirect to seller home or return 301 to `/`
- Primary navigation no longer promotes creator-matching pages
- Existing auth and mode-select flows still work
- Integration test: `/recommendations` and `/creators` redirect without breaking session
- Integration test: seller home loads after redirect
- No removal of phone-OTP login

## Context loaded

- `web/MODULE.md` — route inventory, seller home as canonical entry (#118)
- `web/legacy-redirects.js` — shared redirect config for next.config.js
- `web/src/lib/nav-config.ts` — BOTTOM_NAV_TABS, LEGACY_ROUTE_REDIRECTS
- `web/src/app/creators/page.tsx`, `web/src/app/recommendations/page.tsx` — legacy pages
- `web/src/__tests__/test_seller_home_shell.test.tsx` — seller home verification
- `web/src/__tests__/test_nav_header_redirects.test.tsx`, `test_issue95_recommendation_nav.test.tsx` — nav tests to update

## Standards applied

- Reliability — redirect must not clear auth session
- Maintainability — reuse legacy-redirects.js pattern from #77/#95
- Security — no auth flow changes

## Plugin skills & MCP

- `/nextjs` — App Router redirects via next.config.js
- No Supabase, API, or backend changes

## Implementation approach

1. Add `/creators` and `/recommendations` → `/` to `legacy-redirects.js` (301)
2. Replace legacy page components with client-side `LegacyRouteRedirect` (belt-and-suspenders for tests)
3. Update `BOTTOM_NAV_TABS` to seller-only: Trang chủ + Juli (remove Creators, Gợi ý)
4. New tests in `test_legacy_creator_routes_retired.test.tsx`
5. Update nav redirect tests in `test_nav_header_redirects.test.tsx` and `test_issue95_recommendation_nav.test.tsx`
6. Update `web/MODULE.md` route docs

## DO NOT touch

- `web/src/components/CreatorsPage.tsx`, `RecommendationsPage.tsx` — keep for component-level tests; routes redirect away
- Phone-OTP login (`/login`, `LoginForm`, auth-context)
- Workflow panels (#119–#121)
- Backend `src/` Python modules
