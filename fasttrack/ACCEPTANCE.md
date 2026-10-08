# Acceptance criteria

Tick with evidence: `- [x] AC-n … — evidence: <sha / test / query / log>`.

## P0 — setup

- [x] **AC-0.1** Branch `fasttrack/optimize-product` exists on origin, cut from
  `main` after #2079. — evidence: 86795725 pushed to origin
- [x] **AC-0.2** `fasttrack/` contains README, SPEC, ACCEPTANCE, PROGRESS,
  DECISIONS, LOG, DEBT. — evidence: 86795725
- [x] **AC-0.3** `.claude` edit hooks and the executor-cache pre-commit gate are
  disabled on this branch (D4); ruff pre-commit hooks stay. — evidence: 86795725 (owner-applied)
- [x] **AC-0.4** `fasttrack/check.sh` runs, in order: migration check on a
  throwaway Postgres, shop-isolation tests, gitleaks, ruff, pytest on files
  touched since a given ref. Exits non-zero on any failure. — evidence: 596f9d0b; local full run on throwaway PG16: migrations to head, isolation proof 12 passed
- [x] **AC-0.5** A manual (`workflow_dispatch`) deploy workflow for this branch:
  takes a commit SHA; **backs up the production database first and aborts
  before any migration if the backup fails or is empty**; runs `check.sh`;
  then deploys using the existing VPS deploy path. Never triggers on push. — evidence: 596f9d0b; actionlint clean. plus tag-push trigger `fasttrack-deploy-*` (owner decision 2026-10-05) so it runs while main is frozen
- [x] **AC-0.6** Open Dependabot PRs closed with a comment pointing at D3. — evidence: 19 Dependabot PRs closed 2026-10-05

## P1 — data layer

- [x] **AC-1.1** OAuth callback enqueues `bootstrap_shop(shop_id)` after commit
  on a high-priority queue; an enqueue failure is logged and does not fail the
  callback. Test covers both. — evidence: 728f67d1 (P1-B add4abd1..ea0142ee); tests/unit/test_shop_ingestion.py
- [x] **AC-1.2** Fast phase: commerce cold start + last 30 days of analytics
  via date-range detail calls, then scoring + card persistence for that shop.
  Test with a fake TikTok resource shows rows written for 30 distinct days and
  a card persisted. — evidence: 728f67d1; test_shop_ingestion.py runs real ETL + real scoring, 30 distinct days + ≥1 card persisted
- [x] **AC-1.3** History phase runs on a low-priority queue after the fast
  phase, walks back in chunks until no data, records the earliest date, and is
  resumable (re-running doesn't refetch completed chunks). Tested. — evidence: 728f67d1; test_shop_ingestion.py (resume, empty-chunk stop, range-refusal halving)
- [x] **AC-1.4** Per-shop bootstrap state + timestamps persisted (migration). — evidence: 728f67d1; migration 074_shop_ingestion_state (RLS, juli_app grants)
- [x] **AC-1.5** One beat entry fans out one task per connected shop with a
  usable read credential (production merchant and `SELLER_CONNECT` shops);
  shops without a completed fast phase get `bootstrap_shop`; a per-shop mutex
  prevents overlap. Tested with ≥2 shops. — evidence: 728f67d1; beat shop-poll-fanout; two-shop tests in test_shop_ingestion.py
- [x] **AC-1.6** Commerce stays incremental every 15 min; analytics runs at
  most once per day per shop and fetches every missing day up to
  `latest_available_date`; a cycle with nothing new makes zero analytics
  detail calls. Tested. — evidence: 728f67d1; test_shop_ingestion.py (nothing new → 1 probe, 0 detail calls)
- [x] **AC-1.7** Product/SKU detail calls run concurrently (bounded) and still
  respect the rate limiter and cycle budget. Tested. — evidence: 728f67d1; tests/unit/test_analytics_range_parallel.py
- [x] **AC-1.8** Mapper: product-grain rows carry `impressions`, per-content-type
  breakdown, `ctr`, derived clicks, and `conversion_rate` (from
  `click_order_rate`); fixture built from the contract samples in
  `docs/integrations/tiktok_api/contract-collection.md`. — evidence: 4010fece; tests/unit/test_tiktok_mapping_product_analytics.py 15 passed
- [x] **AC-1.9** `products.price` filled from `tax_exclusive_price`;
  `products.category`/`category_id` filled from the `category_chains` leaf.
  Tested against `docs/integrations/tiktok_api/samples/`. — evidence: 4010fece; same test file (samples products-{search,detail}-response.json)
- [x] **AC-1.10** Latency events/timestamps exist for connect → bootstrap
  enqueued → fast done → first card → history done. — evidence: 728f67d1; shop_ingestion_state timestamps + shop_* log events with seconds_since_connect
- [x] **AC-1.11** All new/changed backend tests pass; `fasttrack/check.sh`
  passes locally (minus the production backup step). — evidence: 728f67d1; check.sh on fresh PG16: migrations/isolation/gitleaks/ruff/pytest all PASS (180 passed, 1 skipped). Full unit+harness: no new failures vs base after fixes (base pre-existing failures: node_modules contract tests et al.)
- [x] **AC-1.12** Shop isolation holds: new per-shop tasks run under the
  correct shop scope (sticky scope where ETL commits mid-cycle, as #1967).
  Tested with two shops.
 — evidence: 728f67d1; tests/integration/test_shop_ingestion_two_tenant.py as juli_app with real commits (fails if sticky scope removed)
## P7 — Quyết định + Phân tích on demo.app-juli.com (D21)

### P7-A Phân tích backend
- [ ] **AC-7.1** A daily per-shop job builds the ADR-108 report from TikTok
  reads (read-only, per-shop credential via `resolve_read_credential_for_shop`,
  429 backoff) and stores the report JSON + `as_of` per shop (new table,
  migration revision id ≤ 32 chars, RLS/two-tenant safe). Runs after the daily
  analytics pass and once after bootstrap fast phase. Buyer-level order data is
  never persisted beyond what the report needs (aggregates only).
- [ ] **AC-7.2** `GET /v1/demo/analysis` (auth + `X-Shop-Id`, same guards as
  `/v1/demo/decisions`) returns the latest report for the caller's shop, 404
  when none. Two-tenant test proves shop A never sees shop B's report.

### P7-B Quyết định backend
- [ ] **AC-7.3** Optimize Product cards come from the ADR-106 pipeline for every
  shop: top-10 ranked, ≤ 5 active, one card per product, scored after bootstrap
  fast phase and after the daily analytics pass (D11). Each card carries the
  diagnosed stage, the lever, and the product's funnel evidence (impressions,
  CTR, add-to-cart rate, CTOR, AOV — TikTok's definitions) in
  `/v1/demo/decisions`.
- [ ] **AC-7.4** Approve still creates a real run of the Optimize Product
  playbook with CONFIRM before any write (no change to write policy, D13).

### P7-C UI
- [x] **AC-7.5** apps/demo restyled to the index.html mock (tokens from
  `colors_and_type.css`, card/button/badge classes, nav "Trang chủ / Quyết định /
  Phân tích / Cài đặt"). Vietnamese only; KPI names as TikTok writes them.
  — evidence: 93a6b445 (label restored, `destination-naming.test.ts` now denies
  "Hành động"), 17002419 (kit tokens/classes + shell in `globals.css`);
  screenshots in the P7-C session scratchpad (desktop/mobile, no horizontal scroll).
- [x] **AC-7.6** Quyết định (signed in) renders real cards with the stage,
  lever and funnel evidence; approve → run view still works.
  — evidence: 24aca816; `signed-in-decisions.test.tsx` ("renders stage, lever
  and the funnel evidence block…", approve → `/decisions/in-progress/{run_id}`
  unchanged), `lib/__tests__/decision-evidence.test.ts`. Field names are
  ASSUMED (top of `apps/demo/src/lib/decision-evidence.ts`) until P7-B lands.
- [x] **AC-7.7** Phân tích (signed in) renders the report: 5-channel split with
  "GMV trung bình mỗi ngày" 30 vs 30, per-channel funnel, hero profiles,
  event timeline, promotions; Shop Tab shown as missing when absent; no
  backend/endpoint names in the UI. Anonymous visitors see a synthetic sample.
  — evidence: 65c9c856; `components/__tests__/shop-analysis-view.test.tsx`
  (sections in order, funnels, heroes × 5 channels, missing Tab Cửa hàng →
  "Chưa có dữ liệu", no snake_case//v1 in text, 404 → empty state, error never
  falls back to the sample, client sends bearer + X-Shop-Id + ?ranking).
- [x] **AC-7.8** `pnpm lint`, `type-check`, vitest green; guard tests updated
  only where the restyle intentionally changes them.
  — evidence: apps/demo lint 0 errors (14 pre-existing warnings), tsc clean,
  vitest 128 files / 1649 tests pass (Node 20); `pnpm build:demo` OK with dummy
  Supabase env (not committed). Guards changed: `destination-naming.test.ts`
  (D21 flips the retired name), `replay-module-graph.test.ts` (+1 entry:
  the anonymous sample). Others untouched and green.

### P7-D Deploy
- [ ] **AC-7.9** `fasttrack-deploy.yml` builds the demo artifact (Supabase env
  at build) and deploys the demo lane instead of refusing it; landing stays
  blocked. actionlint clean.
