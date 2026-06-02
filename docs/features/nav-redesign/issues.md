# Nav redesign — GitHub issue pack

This file contains **ready-to-paste** GitHub issue titles + bodies for:
- 1 parent **PRD issue**
- a dependency-ordered set of **implementation issues** (vertical slices)

Important scope note:
- This pack is intentionally scoped to **Phase 1 (MVP)** in [`migration_path.md`](../../migration_path.md): web navigation redesign + **UI-only mode** + mock data. No TikTok API, ML jobs, or Scrapy work in Issues 1–8.
- Cross-shop Trends intel (Creator/Shop tabs) is a **v1.5** concern per [`data-sources.md`](../../architecture/data-sources.md) (#10). Until `src/jobs/scraping/` and daily batch pipelines exist, the UI must use mock data and label those panels **“Đang cập nhật dữ liệu thị trường”**.
- Canonical architecture: [`migration_path.md`](../../migration_path.md) · [`map.md`](../../architecture/map.md) · [`branch-runtime-strategy.md`](../../architecture/branch-runtime-strategy.md).

### GitHub issue mapping (live)

| Slice | GitHub | Title (after sync) |
|-------|--------|-------------------|
| Parent PRD | [#75](https://github.com/thienphung00/Juli-AI/issues/75) | Nav redesign: Mode Selection + 5-tab OS navigation |
| 1 | [#76](https://github.com/thienphung00/Juli-AI/issues/76) | 1/8 Mode selection gate |
| 2+3 | [#77](https://github.com/thienphung00/Juli-AI/issues/77) | 2/8 Header + 5-tab nav + redirects |
| 4 | [#79](https://github.com/thienphung00/Juli-AI/issues/79) | 4/8 Home control center |
| 5 | [#80](https://github.com/thienphung00/Juli-AI/issues/80) | 5/8 Trends discovery |
| 6 | [#81](https://github.com/thienphung00/Juli-AI/issues/81) | 6/8 Operations hub |
| 7 | [#82](https://github.com/thienphung00/Juli-AI/issues/82) | 7/8 Juli AI chat |
| 8 | [#78](https://github.com/thienphung00/Juli-AI/issues/78) | 8/8 UI-only hardening (run last) |
| v1.5 contracts | [#83](https://github.com/thienphung00/Juli-AI/issues/83) | Market intelligence feed contracts |
| v1.5 Scrapy | [#84](https://github.com/thienphung00/Juli-AI/issues/84) | `src/jobs/scraping/` smoke test |
| v1.5 wire API | [#85](https://github.com/thienphung00/Juli-AI/issues/85) | Frontend services → real API |

Parent URL for child issues: `https://github.com/thienphung00/Juli-AI/issues/75`

### Sync issues to GitHub

Bodies are pre-rendered under `.gh-issue-bodies/`. From repo root:

```bash
gh auth login -h github.com   # if token expired
chmod +x docs/features/nav-redesign/sync-github-issues.sh
./docs/features/nav-redesign/sync-github-issues.sh
```

This updates #75–#82 and creates v1.5 backlog issues if they do not exist yet.

---

## PRD issue (parent)

### Title
Nav redesign: Mode Selection + 5-tab OS navigation (Seller/Affiliate)

### Body
## Problem Statement
Juli’s current navigation (6 tabs) doesn’t match the “Seller OS” mental model: Trends is misrouted to `/products` without discovery, Recommendations are isolated in their own tab instead of guiding action on Home, Alerts are a dead-end, Operations is too narrow (orders-only), and there’s no conversational AI entry point. Users land on Home after login without choosing whether they’re operating as a Seller or an Affiliate, so KPIs, intelligence, and navigation intent cannot be tailored from the first moment.

## Solution
After OTP login, gate the experience behind a Mode Selection step (Seller vs Affiliate). Consolidate navigation into **5 purposeful tabs**:
- Trang chủ (Home control center, with AI recommendations embedded)
- Trực tiếp (Livestream intelligence)
- Xu hướng (Trends discovery: search + 3 entity tabs)
- Vận hành (Operations hub with role-appropriate sub-sections)
- Juli (AI chat)

Mode drives both **data perspective** (seller vs affiliate KPIs) and **theme** (Seller = dark; Affiliate = light) and can be switched mid-session from a consistent header.

## User Stories
1. As a seller, I want to choose Seller mode after login so my KPIs and theme are correct from the first screen.
2. As an affiliate, I want to choose Affiliate mode after login so I see commission-centric data and light theme.
3. As a hybrid user, I want to switch modes mid-session without logging out or losing context.
4. As any user, I want a consistent header on all authenticated screens with a mode switcher and alert bell.
5. As any user, I want bottom navigation to be 5 tabs with clear intent and no redundant mode label.
6. As a seller, I want Home to show today’s GMV, livestream status, top recommendation, and a single next action within one screen.
7. As an affiliate, I want Home to emphasize commission opportunities and audience-fit recommendations.
8. As a seller, I want Trends to help me find best-fit creators and analyze competitor shops.
9. As an affiliate, I want Trends to surface trending products, rising shops, and competitor creators in my niche.
10. As any user, I want Trends search to filter results quickly within the active tab.
11. As a seller, I want Operations to include products, creators, orders, and returns in one place.
12. As an affiliate, I want Operations to focus on products (commission), orders (status), and returns (impact).
13. As any user, I want a Juli tab that opens a chat UI with role-aware suggested prompts.
14. As any user, I want deprecated routes to redirect to their new homes without breaking deep links.
15. As a developer/designer, I want a UI-only mode to render all screens with mock data without backend wiring.

## Implementation Decisions
- **Mode selection gate**:
  - First login after OTP verification: redirect to `/mode-select`.
  - Returning user with mode persisted: skip `/mode-select` and go directly to `/`.
  - Mode switch must be available in the top-right header on every authenticated screen.
- **Theme behavior**:
  - Seller mode renders in dark theme; Affiliate mode in light theme.
  - Theme must apply immediately (avoid flash on load).
- **Navigation**:
  - 5 tabs: Trang chủ, Trực tiếp, Xu hướng, Vận hành, Juli
  - Deprecated routes redirect:
    - `/alerts` → `/` (alerts surfaced in Home context)
    - `/recommendations` → `/` (recommendations embedded)
    - `/products` → `/trends` (discovery moved)
    - `/orders`, `/inventory`, `/creators` → `/operation` (operations hub)
- **Trends**:
  - Search bar + 3 tabs (Product / Creator / Shop).
  - Product tab shared; Creator/Shop intent differs by mode (seller vs affiliate).
- **Operations**:
  - Seller: Products (GMV/ROI), Creators, Orders, Returns.
  - Affiliate: Products (Commission), Orders, Returns.
- **Juli**:
  - AI chat UI is available as a dedicated tab.
  - MVP can be UI-only with mock conversation and suggested prompts (backend wiring can follow).
- **UI-only mode**:
  - When `NEXT_PUBLIC_UI_ONLY=1`, all 5 tabs render with mock data and **must not require API calls**.
- **Vietnamese labels** throughout; chat input accepts Vietnamese and English.

## Testing Decisions
- Prefer **integration-style UI tests** for the critical flows:
  - First login → mode select → home renders correct theme
  - Returning user skips mode select
  - Mode switch flips theme and role-specific content without reload
  - Navigation shows 5 tabs and redirects work
  - UI-only mode renders without API calls
- Keep tests focused on **public behavior** (rendered UI + navigation), not internal component structure.

## Out of Scope (MVP — Issues 1–8)
- TikTok Shop Partner API wiring, ETL ingest, daily ML compute, Scrapy jobs (all **v1.5** per `migration_path.md`).
- Redis, Celery, near-realtime dashboards (all **v2.0**).
- Real market intel feeds for cross-shop creator/shop signals — mock + “Đang cập nhật dữ liệu thị trường” in MVP.
- Backend schema changes or new frameworks.

## Architecture alignment
| Phase | This issue pack | Data |
|-------|-----------------|------|
| **MVP** | Issues 1–8 | `NEXT_PUBLIC_UI_ONLY=1` + `web/src/lib/mock-data/*` + `web/src/lib/services/*` |
| **v1.5** | Optional backlog 9–11 | TikTok API (#1), `src/jobs/scraping/` vendor feeds (#10), daily `src/pipelines/daily.py` |
| **v2.0** | Not in this pack | Celery workers, Redis pub/sub, WebSocket live updates |

## Dependency note: Market Intelligence (v1.5, not in Issues 1–8)
- v1.5 ingestion lives in the Juli-AI monorepo: **`src/jobs/scraping/`** (Scrapy) + **`src/orchestration/`** (APScheduler nightly), per [`map.md`](../../architecture/map.md).
- Vendor feeds: **FastMoss, Kalodata, Shoplus** (`data-sources.md` #10). TikTok shop data uses the **official Partner API only** — Seller Center browser scraping is **forbidden** (#9).
- `large-scale-scraper/` is a reference architecture for Scrapy patterns; implement inside `src/jobs/scraping/`, not as a separate runtime for MVP.
- **MVP expectation**: mock Trends Creator/Shop panels; do not block UI redesign on ingestion.

## Further Notes
- Performance goal: navigation/tab switch should feel instant; avoid spinners for simple tab changes.
- Reliability: deep-links to deprecated routes must be safe and predictable via permanent redirects.

---

## Implementation issues (dependency order)

> Parent link for new issues: https://github.com/thienphung00/Juli-AI/issues/75 — use `sync-github-issues.sh` to push bodies to GitHub.

### 1) Auth onboarding gate: `/mode-select` + persisted mode + no theme flash
- **Type**: AFK
- **Blocked by**: None
- **User stories covered**: 1, 2, 3, 15

#### Title
Nav redesign: Mode selection gate after OTP login (persisted Seller/Affiliate + theme init)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Implement the post-login Mode Selection gate:
- First login after OTP success routes to `/mode-select`.
- If a mode is already persisted, skip `/mode-select` and route to `/`.
- Persist mode immediately on selection (and support switching later).
- Ensure theme applies without flash on initial load (Seller=dark, Affiliate=light).
- Must work in `NEXT_PUBLIC_UI_ONLY=1`.

## Acceptance criteria
- After OTP success with no saved mode, user lands on `/mode-select` (not `/`).
- Selecting Seller persists mode and routes to `/` in dark theme.
- Selecting Affiliate persists mode and routes to `/` in light theme.
- Returning user with saved mode never sees `/mode-select` and theme is correct immediately.
- With `NEXT_PUBLIC_UI_ONLY=1`, flow works without requiring backend calls.

## Blocked by
None - can start immediately

---

### 2) Global layout: header (mode switcher + alert bell) on all authenticated pages
- **Type**: AFK
- **Blocked by**: Issue 1
- **User stories covered**: 3, 4

#### Title
Nav redesign: shared authenticated header with mode switcher + alert bell

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Add a consistent header layout to all authenticated pages:
- Left: logo / page title
- Right: mode switcher then alert bell
- Mode switcher changes active mode instantly (no logout, no reload).
- Alert bell shows a badge count and opens a simple drawer/sheet with placeholder alerts (mock in UI-only mode).

## Acceptance criteria
- Header is present on all authenticated screens and matches layout: left title, right controls.
- Mode switcher is accessible from the header on every screen and flips mode + theme instantly.
- Alert bell is rightmost and opens a drawer/sheet; badge count renders (mock ok).
- Works in `NEXT_PUBLIC_UI_ONLY=1`.

## Blocked by
Blocked by Issue 1 (mode persistence + theme init)

---

### 3) Bottom navigation: 5 tabs + route redirects for deprecated surfaces
- **Type**: AFK
- **Blocked by**: Issue 2
- **User stories covered**: 5, 14

#### Title
Nav redesign: 5-tab bottom nav + permanent redirects for deprecated routes

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Update bottom navigation to exactly 5 tabs:
- Trang chủ (`/`)
- Trực tiếp (`/livestreams`)
- Xu hướng (`/trends`)
- Vận hành (`/operation`)
- Juli (`/ai-chat`)

Add permanent redirects for legacy routes:
- `/alerts` → `/`
- `/recommendations` → `/`
- `/products` → `/trends`
- `/orders` → `/operation`
- `/inventory` → `/operation`
- `/creators` → `/operation`

## Acceptance criteria
- Bottom nav shows exactly 5 tabs with Vietnamese labels; no mode label in nav.
- Tapping each tab navigates correctly and feels instant.
- Navigating directly to each deprecated route permanently redirects to the new destination.

## Blocked by
Blocked by Issue 2 (shared header wiring)

---

### 4) Home control center: embed AI recommendations + alerts as cards (mode-aware)
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: 6, 7, 14, 15

#### Title
Nav redesign: Home as control center (mode-aware KPIs + inline AI recommendation + alerts)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Restructure Home into a control-center screen:
- Seller: GMV today, livestream status, top creator/product highlights, inline AI recommendation card, and alert banner card.
- Affiliate: commission-centric KPIs, trending opportunities, inline AI recommendation card for commission opportunity.
- Alerts are surfaced in Home context (not a standalone tab).
- Recommendations are embedded (no separate recommendations tab).
- Must render with mock data in UI-only mode.

## Acceptance criteria
- Seller Home renders in dark theme and shows AI recommendation card without scrolling.
- Affiliate Home renders in light theme and shows a commission opportunity recommendation card.
- Alerts appear as cards on Home; there is no need for a dedicated `/alerts` tab.
- With `NEXT_PUBLIC_UI_ONLY=1`, Home renders with mock data and no API calls are required.

## Blocked by
Blocked by Issue 3 (nav + redirects)

---

### 5) Trends discovery: search + 3 entity tabs with role-differentiated intent
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: 8, 9, 10, 15

#### Title
Nav redesign: Trends discovery page (search + Product/Creator/Shop tabs, role-aware)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Create a Trends discovery surface:
- Search bar with ~300ms debounce filtering within the active tab.
- 3 tabs: Product / Creator / Shop.
- Product tab is shared across modes.
- Creator and Shop tabs render different intent depending on mode:
  - Seller: best-fit creators + competitor shop analysis
  - Affiliate: competitor creators + best-fit partnership shops
- For any cross-shop intel not available in MVP, render mock data and clearly label as “Đang cập nhật dữ liệu thị trường”.

## Acceptance criteria
- `/trends` renders with search input and 3 tabs within 1 interaction.
- Typing in the search bar filters results after debounce within the active tab.
- Seller-mode Creator and Shop tabs show seller-intent fields; affiliate-mode shows affiliate-intent fields.
- With `NEXT_PUBLIC_UI_ONLY=1`, renders with mock data (and “Đang cập nhật dữ liệu thị trường” where applicable).

## Blocked by
Blocked by Issue 3 (nav + redirects)

---

### 6) Operations hub: role-appropriate sub-tabs under one tab
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: 11, 12, 15

#### Title
Nav redesign: Operations hub (role-based sub-tabs: Seller vs Affiliate)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Create an Operations hub under `/operation`:
- Seller: sub-tabs Products (GMV/ROI), Creators, Orders, Returns.
- Affiliate: sub-tabs Products (Commission), Orders, Returns (no Creators tab).
- Seller views can include full actions; affiliate views are read-only / impact-only where specified.
- Must render with mock data in UI-only mode.

## Acceptance criteria
- Seller mode shows 4 sub-tabs: Sản phẩm, Creator, Đơn hàng, Hoàn trả.
- Affiliate mode shows 3 sub-tabs: Sản phẩm, Đơn hàng, Hoàn trả (no Creator tab).
- Each sub-tab renders mode-appropriate fields and affordances.
- With `NEXT_PUBLIC_UI_ONLY=1`, operations renders with mock data without API calls.

## Blocked by
Blocked by Issue 3 (nav + redirects)

---

### 7) Juli tab: AI chat UI (mode-aware prompts + mock conversation)
- **Type**: AFK
- **Blocked by**: Issue 3
- **User stories covered**: 13, 15

#### Title
Nav redesign: Juli AI chat tab (mode-aware prompts + UI-only mock conversation)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Add a Juli tab at `/ai-chat`:
- Chat UI with message list + input
- Mode-aware welcome copy and suggested prompts
- UI-only mode uses a mock conversation and does not require backend wiring
- (Optional) Placeholder for future streaming behavior (not required for MVP UI-only)

## Acceptance criteria
- Juli tab opens a chat interface within 1 tap from bottom navigation.
- Suggested prompts differ between Seller and Affiliate mode.
- With `NEXT_PUBLIC_UI_ONLY=1`, chat renders and sends mock replies without API calls.

## Blocked by
Blocked by Issue 3 (nav + redirects)

---

### 8) UI-only mode guarantees: one switch, zero API calls, mock data coverage
- **Type**: AFK
- **Blocked by**: Issues 1–7 (can be worked in parallel as a hardening pass)
- **User stories covered**: 15

#### Title
Nav redesign: UI-only mode hardening (mock data coverage + no API calls)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Ensure `NEXT_PUBLIC_UI_ONLY=1` is a reliable design-iteration mode across the redesign:
- All 5 tabs render with representative mock data via **`web/src/lib/services/*`** (not direct `api.*` calls from components — see `branch-runtime-strategy.md`)
- No API calls are required to render core UI
- Any missing backend surfaces are clearly labeled as placeholder/mocked
- Add service adapters per screen: `home.ts`, `trends.ts`, `livestreams.ts`, `operation.ts`, `ai-chat.ts` (each branches on `isUiOnly`)

## Acceptance criteria
- With `NEXT_PUBLIC_UI_ONLY=1`, user can navigate all 5 tabs and see meaningful mock content.
- No component imports `@/lib/api-client` directly; data flows through `@/lib/services/*`.
- No runtime errors occur due to missing backend data.
- Any market-intel panels not backed by v1.5 data are labeled “Đang cập nhật dữ liệu thị trường”.

## Blocked by
Blocked by Issues 1–7 (hardening pass)

---

## Optional backlog (v1.5) — Wire real data + Market Intelligence

> **Phase 2** per [`migration_path.md`](../../migration_path.md). Not part of MVP Issues 1–8. Trigger: UX validated, ready for TikTok API + daily batch jobs.

### 9) Market intel ingestion: define feed contracts for Trends (Product/Creator/Shop)
- **Type**: ENG
- **Blocked by**: None
- **Why**: Prevents UI/backend mismatch by locking the output shapes the web app will consume.

#### Title
Market intelligence: define scraper-backed feed contracts for Trends surfaces

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Define versioned, documented “feed contracts” for the cross-shop intel used by:
- Trends → Product feed (rank, velocity windows, category, confidence flags)
- Trends → Creator momentum feed (growth signals, audience overlap hints, last-seen)
- Trends → Shop competitive feed (commission ranges/deltas, creator network size, top products)

## Acceptance criteria
- A single doc captures request/response shapes (even if initially mocked) for the 3 feeds.
- Fields align with the PRD’s UI intent (Seller vs Affiliate differences).
- Each feed has a freshness SLA target (daily batch for v1.5) and pagination expectations.
- Contracts documented under `docs/` and referenced from `data-sources.md` #10.

### 10) Market intel: `src/jobs/scraping/` — Scrapy smoke test (vendor feeds)
- **Type**: ENG
- **Blocked by**: Issue 9

#### Title
Market intelligence: Scrapy job smoke test in `src/jobs/scraping/`

#### Body
## Parent
(PRD ISSUE URL)

## What to build
Implement (or extend) Scrapy spiders under `src/jobs/scraping/` and prove one vendor feed end-to-end:
- Run one spider for **Kalodata, FastMoss, or Shoplus** (per `data-sources.md` #10)
- Archive raw payloads to Cloudflare R2 before transform
- Persist normalized records via `src/data` repos
- Orchestrate via `src/pipelines/daily.py` + APScheduler (`src/orchestration/`) — **not** Celery (v2.0)

## Acceptance criteria
- One spider completes and writes non-empty shop/creator intel rows.
- No Seller Center DOM scraping (#9 forbidden).
- Logs do not leak secrets/tokens.

### 11) Web: wire `web/src/lib/services/*` to real Trends/Home APIs (v1.5)
- **Type**: ENG
- **Blocked by**: Issues 9–10

#### Title
Nav redesign v1.5: wire frontend services to real API (unset `NEXT_PUBLIC_UI_ONLY`)

#### Body
## Parent
(PRD ISSUE URL)

## What to build
- Add/extend FastAPI endpoints for Trends feeds (contracts from Issue 9) and existing `/v1/*` surfaces
- Update `web/src/lib/services/*` so `isUiOnly === false` calls `api-client.ts` with typed responses
- TikTok shop-scoped data via official API (#1); cross-shop intel via ingestion output (#10)
- Components remain unchanged — only the service layer switches mock → real

## Acceptance criteria
- Unsetting `NEXT_PUBLIC_UI_ONLY` renders all 5 tabs from real APIs without component refactors.
- Endpoints are paginated (no unbounded lists).
- Trends Creator/Shop tabs show real intel when ingestion is available; otherwise graceful fallback + label.
- Daily freshness acceptable for v1.5 (no Celery/WebSocket required).

### 12) v2.0 (future) — Near-realtime Trends + live dashboard
- **Type**: ENG
- **Blocked by**: Issue 11 + v1.5 stable in production
- **Not detailed here** — see `migration_path.md` Phase 3 (Redis, Celery Beat, WebSocket).

