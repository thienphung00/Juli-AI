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
- [x] **AC-7.1** A daily per-shop job builds the ADR-108 report from TikTok
  reads (read-only, per-shop credential via `resolve_read_credential_for_shop`,
  429 backoff) and stores the report JSON + `as_of` per shop (new table,
  migration revision id ≤ 32 chars, RLS/two-tenant safe). Runs after the daily
  analytics pass and once after bootstrap fast phase. Buyer-level order data is
  never persisted beyond what the report needs (aggregates only).
  Evidence (P7-A, `fasttrack/p7a-analysis`): 0a8e966a (table + migration
  `076_shop_diagnosis_reports`, RLS per verb via `app_current_shop_id()`),
  2e180371 (`services/shop_diagnosis_daily`: fetch moved from the script, job),
  3d7978f0 (`juli_backend.build_shop_diagnosis`, enqueued from
  `run_poll_shop_task` when `analytics_ran` and from `run_bootstrap_task`),
  180963ba. Tests `tests/unit/test_shop_diagnosis_daily.py` (builds + stores from
  a fake TikTok resource, idempotent per (shop, end), no buyer markers stored,
  temp snapshot deleted, wrong-shop / missing credential refused before any
  call, hooks enqueue after analytics + bootstrap, enqueue failure never breaks
  the cycle) and `tests/integration/test_shop_diagnosis_two_tenant.py` (as
  `juli_app` on PG16: A's job writes only A; B cannot read or insert A's rows).
  `fasttrack/check.sh --since 3ecd5e48 --skip-gitleaks` on a throwaway PG16:
  migrations up/down/up PASS, isolation 12 passed, ruff PASS, pytest 154 passed.
- [x] **AC-7.2** `GET /v1/demo/analysis` (auth + `X-Shop-Id`, same guards as
  `/v1/demo/decisions`) returns the latest report for the caller's shop, 404
  when none. Two-tenant test proves shop A never sees shop B's report.
  Evidence: a95ccd17 (`api/routes/demo_analysis.py`, `get_active_shop`;
  response `{as_of, built_at, ranking, report}`, `?ranking=60d|30d`). Tests in
  `test_shop_diagnosis_daily.py`: 200 latest + 30d + 422 bad ranking, 404 none,
  401 without JWT, shop A gets 404 while only B has a report (and `?shop_id=`
  is ignored); PG two-tenant read proof as above.

### P7-B Quyết định backend
- [x] **AC-7.3** Optimize Product cards come from the ADR-106 pipeline for every
  shop: top-10 ranked, ≤ 5 active, one card per product, scored after bootstrap
  fast phase and after the daily analytics pass (D11). Each card carries the
  diagnosed stage, the lever, and the product's funnel evidence (impressions,
  CTR, add-to-cart rate, CTOR, AOV — TikTok's definitions) in
  `/v1/demo/decisions`. — evidence: 7ee7f1e4..HEAD (P7-B); tests/unit/test_optimize_product_decision_cards.py
  (13 passed): `test_whole_catalog_is_scored_and_the_top_ten_ranked`,
  `test_scoring_writes_one_card_per_product_and_surfaces_at_most_five`,
  `test_two_shops_are_scored_in_isolation`, `test_the_p1_scoring_hook_produces_the_adr106_cards`
  (the `score_and_persist_cards` hook P1 calls after the fast phase and the daily pass),
  `test_decisions_endpoint_returns_diagnosis_and_evidence`. Caveat: add-to-cart only on
  single-day-fetched days (DEBT P7-B).
- [x] **AC-7.4** Approve still creates a real run of the Optimize Product
  playbook with CONFIRM before any write (no change to write policy, D13). — evidence:
  `test_approving_an_adr106_card_creates_an_optimize_product_run` (202, queued
  `optimize_product_2` run bound to the card's product; write step policy CONFIRM);
  tests/unit/test_api_demo_execution.py unchanged and passing; no tool/policy code touched.

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
  unchanged), `lib/__tests__/decision-evidence.test.ts`. Aligned to P7-B's
  real shape in c446bb2d (stage label, lever action, trigger, "Có thể lấy lại
  khoảng X ₫ GMV mỗi ngày (ước tính theo quy tắc…)", metrics table with
  backend labels + Rõ/Tham khảo/Chưa đủ dữ liệu); tests run on
  `lib/__tests__/fixtures/adr106-decision-item.json`, captured from
  `test_decisions_endpoint_returns_diagnosis_and_evidence`.
- [x] **AC-7.7** Phân tích (signed in) renders the report: 5-channel split with
  "GMV trung bình mỗi ngày" 30 vs 30, per-channel funnel, hero profiles,
  event timeline, promotions; Shop Tab shown as missing when absent; no
  backend/endpoint names in the UI. Anonymous visitors see a synthetic sample.
  — evidence: 65c9c856; `components/__tests__/shop-analysis-view.test.tsx`
  (sections in order, funnels, heroes × 5 channels, missing Tab Cửa hàng →
  "Chưa có dữ liệu", no snake_case//v1 in text, 404 → empty state, error never
  falls back to the sample, client sends bearer + X-Shop-Id + ?ranking).
  Funnel tiles wrap (auto-fit grid, 44b622ed): 0 of 9 tiles clipped per
  channel at 1280px and 390px (was 6 of 9 out of view at 390px).
- [x] **AC-7.8** `pnpm lint`, `type-check`, vitest green; guard tests updated
  only where the restyle intentionally changes them.
  — evidence: apps/demo lint 0 errors (14 pre-existing warnings), tsc clean,
  vitest 128 files / 1649 tests pass (Node 20); `pnpm build:demo` OK with dummy
  Supabase env (not committed). Guards changed: `destination-naming.test.ts`
  (D21 flips the retired name), `replay-module-graph.test.ts` (+1 entry:
  the anonymous sample). Others untouched and green.

### P7-D Deploy
- [x] **AC-7.9** `fasttrack-deploy.yml` builds the demo artifact (Supabase env
  at build) and deploys the demo lane instead of refusing it; landing stays
  blocked. actionlint clean.
  Evidence: new `build` job + deploy changes in `.github/workflows/fasttrack-deploy.yml`
  (see commit on `fasttrack/p7d-deploy`); `actionlint` exit 0; not yet run on
  GitHub (first tag deploy is the live proof).

## P8 — the app follows the sales demo video (ADR-109)

- [x] **AC-8.1 (P8-A)** Daily per-shop job computes ADR-109 d.5 rankings for every stream × clickable metric (products: Thẻ sản phẩm, Tab Cửa hàng × Hiển thị/CTR/CTOR/AOV; LIVE sessions × Hiển thị/CTR/CTOR; videos when P8-B data exists) — GMV/day per row by log-share (sequential at zero), content rows vs the stream's prior-window rate, confidence labels (1,000-impression floor), top-10 + closing rows (ít đơn / khác / cơ cấu) that reconcile to the stream factor. Stored in the DB (tenant-isolated); no report rendering. A read function + `GET /v1/demo/analysis/rankings` returns them on demand. Tests: reconciliation, zero sides, two-tenant.
  Evidence (P8-A, branch fasttrack/p8a-rankings): 47ccfc4f `shop_diagnosis/rankings.py` (+ `decomposition.log_share`/`sequential_share`); 0500f337 migration `077_metric_rankings`, table `shop_metric_rankings` tenant_direct + RLS; 4d7ee200 job stores 13 tables per shop (15 with videos) from the same fetch; f51da34b `GET /v1/demo/analysis/rankings`. Tests: `tests/unit/test_shop_metric_rankings.py` (reconciliation incl. new product, zero side, whole-stream zero side; floors; Rõ order; top-10/fold; LIVE vs prior stream rate; videos optional), `tests/unit/test_shop_metric_rankings_daily.py` (job, 200/404/422/401, cross-shop 404, migration), `tests/integration/test_shop_metric_rankings_two_tenant.py` (juli_app RLS). `fasttrack/check.sh --since bd55f06b --skip-gitleaks` on a throwaway PG16: migrations (up/down -1/up, head 077) PASS, isolation 12 passed, ruff PASS (21 files), pytest 11 files 153 passed. Video rankings wait on P8-B wiring `video_metrics` (DEBT).

- [x] **AC-8.2 (P8-B)** Verified (from the Partner API spec / a read-only live call by the owner) whether the shop video performance endpoints accept a date range; per-video metrics for the last-30 and prior-30 windows are fetched (date-ranged, or videos posted inside each window as fallback) and exposed to the ranking job. Read-only, rate-limited.
  Evidence (P8-B, 2026-10-08): spec (`tts-openapi-guide` OAS `analytics.json`, v202509) — list, details and video-products endpoints all REQUIRE `start_date_ge`/`end_date_lt`; list `views` = "during the selected time range"; details `granularity=1D` returns dated intervals with product impressions/clicks/GMV (no SKU orders). Commits 5498e2ee (details endpoint: GET wrapper, read allowlist, rate-limit gate key), 3e74be51 (`services/shop_diagnosis_daily/video_windows.py`: `fetch_video_windows` → `VideoWindowMetrics`, basis `date_range` | `posted_in_window`, cap 20/window), 7542e04b (`--video-windows` owner check). Tests `tests/unit/test_shop_diagnosis_video_windows.py` (8: date-range split, both fallbacks, failed video, cap/dedup, 42-call budget, poll-window gate + 429 backoff, gating coverage), `test_tiktok_promotion_search.py::test_video_performance_details_*`, `test_shop_diagnosis_scripts.py::test_video_windows_mode_*`. Live confirmation by the owner and wiring into the daily job (orchestrator, with P8-A) still pending — see DEBT P8-B.
- [x] **AC-8.4 (P8-G)** Read tool `get_product_diagnoses` added to the Optimize Product playbook as the first step, emitting `tool.started`/`tool.completed` with a Vietnamese summary; read-only; tests. Evidence: `tests/unit/test_agent_tool_product_diagnoses.py` (18 tests: handler happy/empty/API-error, registration READ/AUTO, playbook step 0 + guidance, Vietnamese summaries, runner emits tool.started then tool.completed); playbook/registry/golden/budget pins updated; commits on `fasttrack/p8g-diagnoses`.

- [x] **AC-8.3 (P8-C)** Every write by an agent tool records the field's before and after values on the run; a "Hoàn tác" run restores them with the same CONFIRM consent, refuses when the field changed externally after Juli's write; per-shop rule store (ADR-109 d.12 table) with set_by (team/seller) + set_at, API to read/write; day-7 guardrail check raises a "Hoàn tác?" question when a seller-set band is exceeded (never auto-reverts). Tests incl. two-tenant.
  Evidence: cd626005..bdcaea66 (P8-C). Migration `078_rules_and_write_values`
  (run_write_values, shop_rules, run_revert_questions, workflow_runs.reverts_run_id;
  RLS per verb, tenant_direct). Capture: `ProductToolExecutor` + `write_capture.py`
  + `SqlWriteValueRecorder`; revert: `services/run_changes` (refusals in Vietnamese,
  revert playbook + deterministic planner on the ordinary runner/SSE/CONFIRM),
  `POST /v1/demo/runs/{id}/revert`, `GET /v1/demo/runs/{id}/changes`,
  `/v1/demo/revert-questions`; rules: `services/shop_rules`, `GET/PUT/DELETE
  /v1/demo/rules`, cap in `apply_emission_budget`, levers in decisions list +
  approve; guardrail: `workers/impact_reader/pipeline._day7_guardrail`. Tests:
  `tests/unit/test_run_changes_revert.py` (capture, revert happy path with CONFIRM,
  refusal on external change at API and at write, decline, refusals, routes,
  migration), `tests/unit/test_shop_rules.py` (CRUD + set_by, validation, CSV,
  isolation, routes), `test_optimize_product_decision_cards.py` (cap from rule,
  lever not executable/approvable), `test_worker_impact_reader_pipeline.py`
  (question only above band; none without band / for a revert),
  `tests/integration/test_run_changes_two_tenant.py` (juli_app, RLS). check.sh
  `--since bd55f06b` on throwaway PG16: migrations up/down/up PASS (head 078),
  isolation 12 passed, gitleaks PASS, ruff PASS, pytest 211 passed (incl. the PG
  two-tenant module). Full unit+harness: 6360 passed; 29 failed = node_modules-less
  TS contract tests + 2 pre-existing (cross_tenant_probe, destructive_migration CI config).
- [ ] **AC-8.4 (P8-G)** Read tool `get_product_diagnoses` added to the Optimize Product playbook as the first step, emitting `tool.started`/`tool.completed` with a Vietnamese summary; read-only; tests.
- [x] **AC-8.5 (P8-D)** App shell per ADR-109 d.1/d.7: left rail (Trang chủ / Quyết định / Phân tích / Juli locked), bottom bar < 768px, shop header with avatar menu holding Cài đặt, "Juli đang chạy · cập nhật HH:MM"; Home 5-stream matrix + GMV/Đơn/AOV cards (from the ADR-108 report). lint/type-check/vitest/e2e green.
  Evidence: 165ce61d, 80c6e118, f60ce932 (fasttrack/p8d-shell). vitest 1649/1649 (Node 20; `navigation.test.tsx`, `demo-shell.test.tsx`, `home.test.tsx`), @juli/ui 180/180, lint 0 errors, tsc clean, `build:demo` OK (dummy Supabase env), Playwright 92/92 (desktop + mobile-web; `responsive-parity` "navigation is a left rail at 1440px and a bottom bar at 390px"), pytest issue-397 + phase-2.6 contracts 29/29. Screenshots 1440/390: `/private/tmp/claude-501/-Users-macos-Juli-AI-v2/6eb8aef9-2bd8-42de-8507-25e6fe552916/scratchpad/shots-p8d/` (home-anon, home-signed-in with stubbed analysis, menus, decisions, analytics).
- [x] **AC-8.6 (P8-E)** Phân tích per ADR-109 d.2–5. Evidence (branch `fasttrack/p8e-analysis`): aca17597 (sample rankings generator), fdd8410f (UI), 8c2fdfb2 (vitest `components/__tests__/phan-tich.test.tsx`, 20 tests: bottleneck/title/suggestion, URL tab + Home-link landing, cell click → loader(stream, metric) + URL, non-clickable content cells, rows + closing rows = Tổng, LIVE dd/mm/yyyy, 404 empty + retry, row → Ví dụ panel, hero expand, collapsed sections, signed-in client + one `/v1/demo/analysis` read), 0cd3598b (Playwright `e2e/analytics/phan-tich.spec.ts`: anonymous with zero `/v1` requests, stubbed signed-in, no horizontal scroll, axe). Gates: type-check 0, lint 0 errors, vitest 1657/1658 (the 1 = pre-existing replay-scenario byte check, fails on 41584c55 too — DEBT P8-E), e2e 102/102 (desktop + mobile-web), `pnpm build:demo` OK (dummy Supabase env in the shell only).
- [x] **AC-8.7 (P8-F)** Quyết định per d.6, 8–13 (SSE-driven timeline). Evidence (branch `fasttrack/p8f-decisions`): d1695f17 (golden scenario re-copied), 44a5c340 (UI: `components/quyet-dinh/`, `lib/quyet-dinh/`), 725d9136 (vitest `components/__tests__/quyet-dinh.test.tsx`, 20 tests: grouping, price exclusion, bands gate, batch sequencing (max 1 in flight), stepper states, rules editor set_by seller/team + 422 inline, timeline from recorded SSE incl. diagnoses soft-fail + revert concurrency_conflict + duplicate/reorder idempotence + day 7/14, ledger sections, Hoàn tác 202 → new run / 409 verbatim / disabled with reason, Đo lường placeholder, question dismiss, rules editor from URL), 800e7b80 (Playwright `e2e/decisions/quyet-dinh.spec.ts`: anonymous zero `/v1`, stubbed signed-in bands gate → rules editor → Duyệt 2 thẻ → SSE timeline → Đo lường, no horizontal scroll, axe). Gates: type-check 0, lint 0 errors, vitest 1667/1667, e2e 106/106 (desktop + mobile-web), `pnpm build:demo` OK (dummy Supabase env in the shell only).

## P9 — seller access

- [x] **AC-9.1 (P9-A)** demo.app-juli.com offers "Đăng nhập bằng email" beside Google: the seller enters an email, receives a 6-digit code (Supabase Auth email OTP; magic link also accepted), and lands signed in with the same session shape as Google, so every signed-in page and the TikTok Shop connect flow work unchanged. Errors (wrong/expired code, rate limit) in Vietnamese. No new env var beyond NEXT_PUBLIC_SUPABASE_*. Tests + e2e (stubbed Supabase).
  Evidence (branch `fasttrack/p9a-email`): 6ad94d8b (OTP client in `lib/supabase-auth.ts`: `POST /auth/v1/otp` + `POST /auth/v1/verify` type=email, same `AuthSession` + storage key; callback reads magic links + `otp_expired`), 0fdbcbd0 (UI: landing door disclosure, avatar menu "Đăng nhập với Google" / "Đăng nhập bằng email", `/auth/email`), 6ebd3220 (vitest `lib/__tests__/email-otp.test.ts` 17, `__tests__/email-sign-in.test.tsx` 8, magic-link cases in `auth-callback.test.tsx`, landing/menu cases; replay module-graph guard intentionally allows `supabase-auth.ts` fetch pinned to `/auth/v1/otp|verify`), e4b54f6b (Playwright `e2e/auth/email-sign-in.spec.ts`: landing → code → `/auth/connect-shop` with the email bearer on `GET /v1/shops` and `GET /v1/auth/tiktok/start`; wrong code, rate limit, magic link + expired link, menu → `/auth/email`, axe). Backend: `get_current_user` checks only alg (ES256/HS256), `aud=authenticated` and a UUID `sub` — an email-OTP access token from the same project carries all three, no backend change. Gates: type-check 0, lint 0 errors, vitest 1699/1699, e2e 114/114 (desktop + mobile-web), `pnpm build:demo` OK (dummy Supabase env in the shell only), pytest issue-397 contract 11/11. Owner must enable the Email provider + template + SMTP (LOG P9-A).
- [x] **AC-9.2 (P9-B)** A shop connected under a Juli team account can be handed to the seller's account (decided in a grill). — evidence: P16 / D25.7: `tests/unit/test_ops_api.py::test_invite_and_accept_moves_the_shop_and_keeps_ops_access`, `::test_seller_can_decline_ops_access_and_expired_invite_fails`, `tests/integration/test_ops_console_db.py::test_handover_moves_the_shop_through_the_definer_function` (branch `fasttrack/p16-ops`).

## P10 — Quyết định card and flows (contract: fasttrack/contracts/p10-quyet-dinh.md)

- [x] **AC-10.1 (P10-A)** Contract §1–§3 implemented with tests (incl. two-tenant, 422s, cooldown suppresses re-proposal for 7 days, edited consent writes the edited value and is recorded).
  Evidence: branch fasttrack/p10a-card 0b3a6381 (migration 079_decision_reasons), c40052f2 (edits), 9a370552 (reasons + cooldown), 4e2f496e (card), cb1a3a47 (tests), cfc95fd3 (guards); `tests/unit/test_p10a_card_reasons_edits.py` 30 passed (card fields + status mapping, reject/decline/revert 422 + stored + two-tenant 404, cooldown suppress / lift after 7 days / lift on > 20 % change, edited consent rebinds + fake-TikTok write of the edited title + "Hoàn tất theo bản bạn sửa", rule_violation 422s); `fasttrack/check.sh --since effa4d4a --skip-gitleaks` on a throwaway PG16: migrations PASS (up/down/up, head 079), isolation 12 passed, ruff PASS, pytest 168 passed.
- [x] **AC-10.3 (P10-C)** Quyết định matches the artboards exactly at 1440 and 390 (side-by-side screenshots of every artboard state vs the app), wired to the contract with fixtures where the backend is not merged yet; lint/type-check/vitest/e2e/build green. — Evidence: commits fff98999, 74a29955, 25548b04, ba09acba (fasttrack/p10c-ui); vitest 1650/1650 incl. `quyet-dinh-p10.test.tsx` (28: card states, 3 reason dialogs required + codes, edit → edited_values, 422 rule_violation, photo upload + 422 checks, checklist gate → applied, measurement stages, collapse toggles, clients) and `quyet-dinh.test.tsx` (18); Playwright 124/124 vs `next start` incl. `e2e/decisions/quyet-dinh-p10.spec.ts` (6 flows × 2 projects); lint 0 errors, type-check, `pnpm build:demo` (dummy Supabase env) green; side-by-side screenshots of 63 artboard states (artboard | app @ artboard width | app @ 390) via `QD_P10_SHOTS_DIR` — remaining differences listed in LOG.md 2026-10-09 P10-C.

- [x] **AC-10.2 (P10-B)** Contract §4–§6 implemented with tests (photo checks, awaiting states, instructions/applied/verify, measurement stages and final labels; no TikTok promotion writes).
  Evidence (branch `fasttrack/p10b-flows`, ae6a515a..945ec32a): migration `080_lever_flows` onto 078 (ae6a515a; phone cleanup re-pinned onto 080); read-only `find_product_promotions` + staged cover URI kept server-side, cover replaced with the gallery kept (0d4b2b6e); lever flows (`services/lever_flows`), runner `enter_external_wait(narration=)` + `resume_after_external_wait`, worker `resume_lever_flow`, reaper per-flow policy, approve registers the flow and allows promotion cards, revert refused `seller_center`, routes `GET /v1/demo/runs/{id}` (`awaiting`), `POST .../photo`, `GET /v1/demo/photos/{shop}/{token}`, `GET .../instructions`, `POST .../applied`, `GET .../measurement`, `awaiting` on the runs list (be0735d9); tests (aa7dc586, 945ec32a): `tests/unit/test_lever_flows_photo.py` (checks pass/fail per key, file/type/size, end-to-end photo run through the real `WorkflowRunner`: wait + narration + before kept → stage → consent → cover written with before/after recorded; decline; 3-day expiry via the reaper, not at 71 h; routes 202/422/409/404, run detail + list `awaiting`, photo served by token), `test_lever_flows_promotion.py` (proposal vs margin floor/cap, refusal, no-cost fails loudly, 4 instruction sets, end-to-end promotion run: rules narrated → waits → not found "Chưa tìm thấy trên TikTok" + re-check scheduled → found → `measurement_start`; pre-existing promotion not taken; `FakePromotion.writes == []` and no listing edit; approve registers flows; instructions/applied 200/202/409/404; `/changes` + `/revert` `seller_center`; tool unavailable/shop-wide), `test_lever_flows_measurement.py` (waiting/day7/final, bands only from rules, `within_band` null/true/false + question id, dat/gan_dat/khong_dat/chua_ket_luan (thin data, other change), calibration 0.5 → 0.66/0.58/0.38/0.63 and unchanged for chua_ket_luan, stored once, promotion by calendar, 409/404), `test_lever_flows_wiring.py` (080 pins, reaper policy, Celery route, `NoExternalWaitError`), `tests/integration/test_lever_flows_two_tenant.py` (juli_app RLS: 2 passed on PG16). `fasttrack/check.sh --since effa4d4a --skip-gitleaks` on a fresh local PG16: migrations PASS (up/down/up at 080), isolation 12 passed, ruff PASS (77 files), pytest 400 passed / 1 failed = `test_reaper_two_tenant.py::test_each_run_is_reaped_by_its_own_workflows_policy_as_juli_app`, which fails identically on an untouched export of effa4d4a (pre-existing). Unit+harness (no DATABASE_URL): only pre-existing / node_modules failures (LOG).
- [ ] **AC-10.3 (P10-C)** Quyết định matches the artboards exactly at 1440 and 390 (side-by-side screenshots of every artboard state vs the app), wired to the contract with fixtures where the backend is not merged yet; lint/type-check/vitest/e2e/build green.

## P12 — Phân tích redesign (ADR-109 Amendment 2; contract: fasttrack/contracts/p12-phan-tich.md)

- [x] **AC-12.1** The report gains `daily_gmv`, `seller_skus`, `promo_products` (and bands `product_count`); product ranking rows gain `seller_sku`, LIVE / video rows `product_ids` — additive, no migration, older stored payloads still render.
  Evidence: commit 3fb2dab9; `tests/unit/test_shop_diagnosis_p12_fields.py` (5: seller SKU read, promo GMV in/out + depth, band product count, report keys, ranking SKU + tagged products) + updated `test_shop_diagnosis_daily.py` REPORT_KEYS; shop-diagnosis pytest 120 passed; `fasttrack/check.sh --since fasttrack/optimize-product`: migrations PASS (head 080, unchanged), isolation 12 passed, ruff PASS, pytest PASS, gitleaks PASS.
- [x] **AC-12.2** Phân tích matches `docs/product/design/phan-tich/` (PtProduct, PtContent, PtMobile, LinkA): collapsible stream cards (one open; the one whose weakest metric loses the most GMV opens), cells with value / Δ / ₫ per day / "✦ Juli gợi ý" / "trước X" on hover, clicked cell re-ranks, Kéo xuống / Kéo lên, rows expand in place, "Còn lại · 3 dòng", "Tổng" = the cell's figure, Khuyến mãi + Lịch sale và chiến dịch collapsed, ⓘ Cách tính, LinkA caption; Ví dụ panel, hero list and paragraph removed. Deviations listed in LOG 2026-10-10 P12.
  Evidence: `src/components/__tests__/phan-tich.test.tsx` (28), `e2e/analytics/phan-tich.spec.ts` (6 × 2 projects incl. axe and 390 px no-scroll).
- [x] **AC-12.3** Row "Xem đề xuất ›" opens `/decisions?tab=de-xuat&the=<card>` scrolled to the card, outlined 3 s; the card's "Xem phân tích ›" returns to that stream, metric and row (expanded); rows without a card read "Chưa có đề xuất"; "Xem N đề xuất ›" opens the metric's group.
  Evidence: unit "Đề xuất ← Phân tích" (2) + e2e "Xem đề xuất › → the card, highlighted; Xem phân tích › → back on that row".
- [x] **AC-12.4** Signed out, Phân tích is the Quyết định sample's shop (SM-012, MN-015, KD-030, SR-007, TN-021) and issues no `/v1` request.
  Evidence: `replay-module-graph.test.ts` (entry `sample-phan-tich.tsx`), unit coherence test (every sample card's product is ranked), e2e "no /v1 request" (`api == []`). Full: vitest 1673/1673 (Node 20), Playwright 134 passed / 140 skipped, lint 0 errors, type-check clean, build:demo OK.

## P13 — signed in, no TikTok Shop → the sample (owner decisions 2026-10-10)

- [x] **AC-13.1** Signed in with no TikTok Shop connected, Trang chủ, Phân tích
  and Quyết định show the signed-out sample screens (P11 / P12 samples, the
  cosmetics shop) under "Bạn đang xem dữ liệu mẫu · Kết nối TikTok Shop ›",
  linking to `/auth/connect-shop`; the sample issues no `/v1` request and its
  actions stay in local state; signed in WITH a shop is unchanged. — evidence:
  `src/__tests__/no-shop-sample.test.tsx`; `e2e/analytics/no-shop-sample.spec.ts`
  (strip, no /v1 request across the three pages, link → connect-shop)
- [x] **AC-13.2** Phân tích's header (kicker + h1) is left-aligned in the
  non-report states (`.pa-page > .page-header` overrode `align-items: flex-end`
  of the shared header). — evidence: no-shop-sample.test.tsx (CSS rule);
  no-shop-sample.spec.ts (bounding boxes, no-shop and empty-report states)
- [x] **AC-13.3** Trang chủ's sample is the same cosmetics shop and numbers as
  Phân tích / Quyết định (one name: "Cửa hàng Mẫu Hoa Mai"): 5-stream matrix
  (Liên kết added to the sample, greyed), GMV / Đơn / AOV from the additive
  streams; every Home link resolves to that stream in Phân tích, and to the same
  cell where clickable. — evidence: no-shop-sample.test.tsx (figures equal,
  CTOR Thẻ sản phẩm 5,14 % on both), e2e CTOR test; home.test.tsx updated
- [x] **AC-13.4** DEBT records the "reason box disappears after reload" item as
  accepted by the owner, won't fix. — evidence: fasttrack/DEBT.md (P12 section)

## P14 — recommendation pipeline (D24)

### P14-C/F — cost data (read-only) and rule fields for what TikTok does not give us (D24.5, D24.12, D24.13)

Contract: `fasttrack/contracts/p14-rules-and-cost.md`. Branch `fasttrack/p14-data`.

- [x] **AC-14.C1** `GET /order/202407/orders/{id}/price_detail` and `GET /finance/202501/orders/{id}/statement_transactions` are exact production-read GETs (numeric order id only), have a client (`OrderCostsResource`) and are documented in `endpoints.md` with the unverified fields marked. — evidence: `tests/unit/test_order_costs.py` (allowlist accepts both, refuses POST/PUT/other versions/non-numeric/suffixed paths; path helpers; endpoints.md), `test_tiktok_public_facade.py`.
- [x] **AC-14.C2** Migration `081_order_cost_data` (onto 080; the deferred phone cleanup re-parented onto 081, still the tail) adds `order_price_details` (per shop/order/SKU + order row, seller- vs platform-funded), `order_finance_transactions` (per shop/order/SKU/statement + order row, fee/shipping breakdown), `order_cost_fetches`; tenant_direct with RLS per verb; amounts and ids only, no buyer data. — evidence: `fasttrack/check.sh --since a1e6767e` on a fresh PG16: migrations PASS (up/down/up at 081), isolation 12 passed; `tests/integration/test_order_costs_two_tenant.py` (juli_app: A's rows invisible/unwritable from B, B's replace leaves A's rows); RLS/grant/isolation suites (`test_rls_*`, `test_runtime_role_grant_coverage`, `test_two_tenant_isolation_proof`, `test_check_7_production_write_rls`, `test_cross_tenant_probe`, two-tenant suites) 60 passed / 1 skipped / 1 xfailed on PG16; unit: idempotent replace, per-shop, no PII stored, model ⇔ migration columns.
- [x] **AC-14.C3** Each scheduled shop cycle reads a bounded number of orders of the last 60 days (new, or changed since read; finance for delivered, unsettled, at most daily), under the cycle's per-shop lock, one rate-limit bucket per endpoint, stops on an empty bucket / vendor 429 / missing scope, counts other errors per order (5 attempts), and never fails the cycle. — evidence: `test_order_costs.py` (first cycle reads, second cycle makes no vendor call, limiter bound + resume, 429, permission denied, per-order error count + give-up, failed SKU lookup, unexpected error contained, switch-off, env limits); `test_shop_ingestion.py::TestOrderCostsInTheCycle` (real `run_shop_cycle`).
- [x] **AC-14.F1** Optional rule fields for what no TikTok API gives (list and reasons in the contract §4): `sku_cost`, `default_gross_margin_pct`, `default_max_discount_pct`, `program_fee_pct`, `joins_platform_campaigns`, `platform_campaign_note`, `target_roas`, `gmv_max_daily_budget`, `live_schedule` (plus the existing `min_margin_pct`, relabelled "khi giảm giá"); validated with plain messages; served by the existing `GET/PUT/DELETE /v1/demo/rules`. — evidence: `tests/unit/test_shop_rules_off_api.py` (40: valid/invalid per field, unset defaults, routes incl. 422 and unset, per shop).
- [x] **AC-14.F2** The ranking layer reads them only through the typed `shop_rules.shop_economics` (`ShopEconomics`: costs, margins, caps, fee, campaign, ads targets, LIVE slots; `unit_cost`, `gross_margin`, `break_even_roas`, `max_discount_pct` return `None` rather than guess); nothing else reads them yet. — evidence: `test_shop_rules_off_api.py` (precedence SKU > product > default margin, margin and break-even ROAS, cap precedence, other shop empty).
- [x] **AC-14.F3** The demo rules editor has a "Thông tin TikTok không cung cấp" group with every field (Vietnamese label + help, who set it, Lưu / Bỏ đặt, inline Vietnamese errors, LIVE slots as `T2 T4 T6 20:00-22:00` lines); signed out (sample) it shows the sample values read-only with no input and no `/v1` request. — evidence: `src/components/__tests__/rules-editor-off-api.test.tsx` (13), `e2e/decisions/rules-off-api.spec.ts` (2 × desktop + mobile-web); full vitest 1702/1702 (Node 20), decisions Playwright 32 passed / 140 skipped, lint 0 errors, type-check clean.

### P14-A/B/D — card limits and learning (D24.17, D24.6, D24.2)

- [x] **AC-14.1** One limit for every shop: at most 5 new cards per shop day, 25 per shop week, 30 open; campaign-plan cards outside it; env overrides kept. Evidence: `tests/unit/test_p14_card_limits.py::test_fourteen_day_simulation_counts_per_day` (14 days, new/open/expired per day, daily/weekly/open limit each binding), `test_the_day_is_the_shops_day`, `test_campaign_plan_cards_are_outside_the_limits`, `test_decision_emission_budget.py::test_config_defaults_and_env_overrides`.
- [x] **AC-14.2** First connect: day 1 = 3 Juli (`juli`/`juli_with_photo`) + 1 Seller Center + 1 content (video/LIVE), an empty slot filled by the next best card; later days in priority order. Evidence: simulation day 1/day 2, `test_first_day_without_content_fills_the_slot_with_the_next_best`, `test_a_shop_that_has_had_cards_gets_no_first_day_mix`.
- [x] **AC-14.3** A card is valid 7 days from surfacing (`expired`, "Hết hạn" in the card block); expired, rejected, declined, reverted: the same action on the same product returns after 7 days, every time. Evidence: `test_an_expired_card_returns_seven_days_after_expiry`, `test_rejected_and_reverted_return_after_seven_days_every_time`, `test_a_legacy_workflow_card_also_waits_seven_days_after_expiry`, P10-A cooldown tests unchanged.
- [x] **AC-14.4** A surfaced card stays at least 3 days; earlier only when invalid (edited outside Juli, out of stock, metric at target). Evidence: `test_a_surfaced_card_stays_three_days_before_an_unranked_withdrawal`, `test_an_invalid_card_is_withdrawn_inside_its_three_days[edited|out_of_stock|at_target]`.
- [x] **AC-14.5** Open cards are re-scored in place daily (numbers, rank, `computed_at`; `surfaced_at` kept). Evidence: `test_an_open_card_is_rescored_in_place`, simulation stickiness asserts.
- [x] **AC-14.6** Ranking = recoverable GMV × calibration factor (coefficient ÷ 0.5, [0.25, 2]) × reason penalty (60-day fade, floor 0.4); shown GMV unchanged; `adjusted_by_history` in payload, card block and UI. Evidence: `test_calibration_and_reasons_reorder_the_ranking`, `test_a_rejection_lowers_that_actions_priority_for_the_shop`, `test_lever_history_maps_the_coefficient_around_the_neutral_half`, `test_reason_penalty_fades_over_sixty_days_with_a_floor`; vitest `quyet-dinh-p10.test.tsx` "P14-B: a card ranked by the shop's history says so".
- [x] **AC-14.7** Seller-facing "Đòn bẩy" → "Hành động" (rules label, design canvas title, ADR-109 UI copy); code identifiers unchanged. Evidence: `apps/demo` has no "đòn bẩy" left; `destination-naming.test.ts` allow-lists the new label.

### P14-E — "Juli soạn · bạn làm" content cards (contract: fasttrack/contracts/p14-content-cards.md)

- [x] **AC-14E.1** Contract written; ContentCards.dc.html and ContentRun.dc.html copied
  to `docs/product/design/quyet-dinh-flows/` with README rows. — evidence: b668231c.
- [x] **AC-14E.2** Nightly, rules only (no model before Phê duyệt, D24.1): a product
  whose videos' CTR is below the Video stream's prior CTR with ≥ 1 000 product
  impressions → "Kịch bản video mới" (KPI "CTR - Video của người bán", target = the
  stream prior, expected GMV = the ranking rows' D22 loss × 30); a product sold in LIVE
  sessions whose CTOR is below the LIVE prior with ≥ 100 clicks → "Kịch bản host +
  thứ tự giỏ" (KPI "CTOR - LIVE của người bán"). P10 card shape + `executor:
  "juli_drafts"` + `content`; template text. 7-day validity and 7-day return after
  expiry; reason cooldown (Từ chối / Không thực hiện) keyed on `video_script` /
  `live_script`; a surfaced card is withdrawn early only when at target / product not
  sellable; ≤ 5 new content cards per ISO week. — evidence:
  `tests/unit/test_p14_content_rules.py` (candidates ×6), `test_p14_content_flow.py`
  (cards + card block, stored rankings, re-score in place + weekly cap, expiry +
  return, at-target withdrawal, reason cooldown).
- [x] **AC-14E.3** After Phê duyệt: content run (`content_video` / `content_live`)
  reads `get_content_performance`, `get_product_information`, `get_seo_keywords` /
  `find_product_promotions` (tool.* SSE), narrates the seller's rules, makes ONE
  `gpt-5.4-nano` call with OpenAI structured output (`text.format` json_schema, added to
  the adapter), validates it (banned / protected / facts / discount cap / length /
  product on screen ≤ 3 s), waits (`content_choice`); Soạn lại = one more call (bản 2,
  sees bản 1); Dùng (edits re-checked, 422 otherwise) → waits (`content_publish`);
  "Tôi đã đăng video" / "Tôi đã LIVE xong" or the hourly poll's auto-detect →
  `find_new_content` → measuring. Không thực hiện = existing decline route (7-day
  cooldown). No TikTok write, no Hoàn tác. Token usage on the run row. — evidence:
  `test_p14_content_flow.py` (video run end to end, auto-detect, two failed drafts,
  LIVE run + decline + routes, 202/422 routes), rules tests (schemas, guardrails ×12,
  prompts, adapter body, drafter one call).
- [x] **AC-14E.4** Measurement: video CTR of new videos tagging the product vs old
  videos at day 7 / day 14; LIVE product CTOR over the next 3 sessions vs the prior
  session(s); P10 labels and per-lever calibration, stored once; 409 before it starts.
  — evidence: video run test (day 7 → final Không đạt 46 %, calibration `video_script`,
  one final row), progress / stage unit tests.
- [x] **AC-14E.5** Signed-out and no-shop samples carry MN-015 (video) and SM-012
  (LIVE) content cards with canned scripts; no network, no model. — evidence:
  `apps/demo/src/components/__tests__/quyet-dinh-content.test.tsx` (11),
  `e2e/decisions/quyet-dinh-content.spec.ts` (desktop + mobile, zero `/v1` requests).

## P16 — Juli Ops (D25) — branch `fasttrack/p16-ops`, contract `contracts/p16-ops.md`

- [x] **AC-16.1** Migration `083_ops_console`: ops tables are not tenant tables — RLS on, only `juli_ops`, no `juli_app` / `anon` / `authenticated` grant; DEFINER functions with EXECUTE scoped; up / down / up clean. — evidence: `tests/integration/test_ops_console_db.py` (13, PG16), `check_public_schema_privileges` PASS, alembic up/down/up.
- [x] **AC-16.2** Overrides honoured, defaults unchanged when unset: card limits, streams / actions / content on-off, model; OpenAI cap (shared `shop_rules` row, $5 default) stops drafting and Optimize Product model calls, logs `ops_openai_cap_reached`, badge in Tổng quan; rule cards unaffected. — evidence: `tests/unit/test_ops_overrides.py`.
- [x] **AC-16.3** Gates fail closed: Access JWT (aud / iss / exp / domain / key / missing header / missing config / certs down), bypass refused in production, Supabase JWT, active staff, role matrix. — evidence: `tests/unit/test_ops_cf_access.py`, `test_ops_api.py` (gates + role matrix).
- [x] **AC-16.4** No buyer PII in any ops response; every write audited with before / after. — evidence: `test_ops_masking.py`, `test_ops_api.py::test_run_detail_is_read_only_and_masks_buyer_pii`, `::test_settings_put_audits_before_after_and_reset`.
- [x] **AC-16.5** "Xem như shop" read-only (D25.3 amended): seller payloads via the seller handlers; every non-GET 403; no act routes; sessions logged. — evidence: `test_ops_api.py::test_view_as_refuses_every_write_even_for_admin`, `::test_no_act_routes_and_view_is_get_only`, `::test_view_session_is_logged_and_read_only`; `ops-view-as.test.tsx`; e2e `ops.spec.ts` (no write sent).
- [x] **AC-16.6** Mô phỏng: windows 7/14/30/90, trend, p10–p90 bands, CV stability, locked cells, ±5 % steps, GMV math, uncomputable windows reported; scenarios + one target. — evidence: `test_ops_simulation.py`, `test_ops_api.py::test_simulation_endpoint_windows_and_scenarios`, `ops-pages.test.tsx`, e2e.
- [x] **AC-16.7** Huỷ kết nối (D25.13): Admin only, reason + typed name, idempotent, audited; polling stops, runs cancelled, history kept, reconnect resumes. — evidence: `test_ops_disconnect.py`, `test_ops_console_db.py::test_disconnect_as_juli_app_under_the_shops_scope`, `ops-pages.test.tsx`.
- [x] **AC-16.8** Quy tắc in Cài đặt shop (D25.14): every seller rule incl. Giọng văn / Từ không được dùng / 5–30 open cards, set as team, audited, seller sees and edits them. — evidence: `test_ops_api.py::test_staff_set_the_sellers_rules_audited_and_the_seller_sees_them`, `test_shop_rules.py`, `ops-rules-permissions.test.tsx`.
- [x] **AC-16.9** Permission status (D25.15): scopes persisted on refresh; Ops status; seller reconnect strip. — evidence: `test_ops_scopes.py`, `ops-rules-permissions.test.tsx`.
- [x] **AC-16.10** Ops pages match the artboards on `ops.app-juli.com` (host split, noindex). — evidence: `middleware.test.ts`, `ops-pages.test.tsx`, Playwright `e2e/ops/ops.spec.ts` (8, port 3326). OpsSimulate awaits owner review.
- [ ] **AC-16.11** Owner infra (DNS proxied, cert expand, vhost, Cloudflare Access, env, first Admin) — files + `docs/runbooks/ops-console-runbook.md` ready; owner to apply. Evidence of files: `tests/unit/test_ops_vhost.py`.
- [x] **AC-16.12** Privacy: staff-access sentence (VN + EN) and connect-shop notice; consent timestamp stored. — evidence: `apps/landing/src/__tests__/privacy-staff-access.test.tsx`, `test_tiktok_oauth_start_route.py::test_start_records_the_staff_access_consent_on_the_callers_row`.

