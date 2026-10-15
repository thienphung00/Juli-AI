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
- [x] **AC-14.2** ~~First connect: day 1 = 3 Juli + 1 Seller Center + 1 content, an empty slot filled by the next best card; later days in priority order.~~ Superseded by D24.21 (4) — see AC-14.R3.
- [x] **AC-14.3** A card is valid 7 days from surfacing (`expired`, "Hết hạn" in the card block); expired, rejected, declined, reverted: the same action on the same product returns after 7 days, every time. Evidence: `test_an_expired_card_returns_seven_days_after_expiry`, `test_rejected_and_reverted_return_after_seven_days_every_time`, `test_a_legacy_workflow_card_also_waits_seven_days_after_expiry`, P10-A cooldown tests unchanged.
- [x] **AC-14.4** A surfaced card stays at least 3 days; earlier only when invalid (edited outside Juli, out of stock, metric at target). Evidence: `test_a_surfaced_card_stays_three_days_before_an_unranked_withdrawal`, `test_an_invalid_card_is_withdrawn_inside_its_three_days[edited|out_of_stock|at_target]`.
- [x] **AC-14.5** Open cards are re-scored in place daily (numbers, rank, `computed_at`; `surfaced_at` kept). Evidence: `test_an_open_card_is_rescored_in_place`, simulation stickiness asserts.
- [x] **AC-14.6** Ranking = recoverable GMV × calibration factor (coefficient ÷ 0.5, [0.25, 2]) × reason penalty (60-day fade, floor 0.4); shown GMV unchanged; `adjusted_by_history` in payload, card block and UI. Evidence: `test_calibration_and_reasons_reorder_the_ranking`, `test_a_rejection_lowers_that_actions_priority_for_the_shop`, `test_lever_history_maps_the_coefficient_around_the_neutral_half`, `test_reason_penalty_fades_over_sixty_days_with_a_floor`; vitest `quyet-dinh-p10.test.tsx` "P14-B: a card ranked by the shop's history says so".
- [x] **AC-14.7** Seller-facing "Đòn bẩy" → "Hành động" (rules label, design canvas title, ADR-109 UI copy); code identifiers unchanged. Evidence: `apps/demo` has no "đòn bẩy" left; `destination-naming.test.ts` allow-lists the new label.

### P14 — D24.21 owner choices (2026-10-10)

- [x] **AC-14.R1** Strictly 7 days after Từ chối / Không thực hiện / Hoàn tác before the same action on the same product returns — no early return on a > 20 % data change (`decision_reasons.clearly_changed` removed); Optimize Product, content and legacy-workflow cards alike (legacy: a dismissed card returns as a new revision after 7 days even with an unchanged basis, ADR-087 d.6 replaced there). Evidence: `test_p10a_card_reasons_edits.py::test_no_data_change_lifts_the_cooldown_early`, `test_cooldown_suppresses_re_proposal_and_lifts_after_seven_days`, `test_decision_emission_budget.py::test_a_dismissed_card_returns_after_seven_days_even_unchanged`, `test_p14_card_limits.py::test_rejected_and_reverted_return_after_seven_days_every_time`; UI copy no longer says "trừ khi số liệu đổi rõ".
- [x] **AC-14.R2** "Số thẻ mở cùng lúc" (`max_open_cards`) 5–30, default 30; a stored older value < 5 reads as 5; editor shows "thẻ (5–30)" with help and the 5–30 error. Evidence: `test_shop_rules.py` (defaults, out-of-range 4/31, routes 422, clamp), `test_p14_card_limits.py::test_the_sellers_rule_still_lowers_the_open_limit`, `test_optimize_product_decision_cards.py::test_the_sellers_max_open_cards_rule_caps_the_surfaced_cards`, vitest `quyet-dinh.test.tsx` rules editor.
- [x] **AC-14.R3** Fixed daily slots every day (the first day included): at most 3 Juli (`juli`/`juli_with_photo`; legacy cards after them), 1 Seller Center, 1 content; each type in its own priority (expected GMV × calibration × reason penalty); an empty slot stays empty; cards surfaced earlier the same day use up their slot; weekly 25 and open 30 still bind; the Optimize plan keeps top 30 per type. Evidence: `test_p14_card_limits.py::test_fourteen_day_simulation_counts_per_day` (slots 3/1/1 asserted each surfacing day), `test_fourteen_days_with_a_type_running_out_leave_its_slot_empty`, `test_an_empty_slot_stays_empty_on_the_first_day`, `test_every_day_has_the_same_fixed_slots`, `test_cards_surfaced_earlier_today_use_up_their_slot`; `test_d24_21_owner_choices.py::test_each_executor_type_keeps_its_own_top_k`, `test_content_priority_is_gmv_times_the_levers_history`.
- [x] **AC-14.R4** New rules "Giọng văn" (`content_tone`, text ≤ 300) and "Từ không được dùng" (`banned_terms`, ≤ 50 terms ≤ 100 chars): validation, `GET/PUT/DELETE /v1/demo/rules`, a "Nội dung video / LIVE" group in the rules editor, sample values, chips. Evidence: `test_shop_rules.py`, vitest "D24.21: edits the content voice".
- [x] **AC-14.R5** Content runs read exactly `content_tone` / `banned_terms` (aliases `tone` / `banned_words` ignored); a listing title / description write containing a banned term is refused (422 `rule_violation`, confirmation stays pending) — Juli's proposal and the seller's edit alike. Evidence: `test_d24_21_owner_choices.py` (load_rules, listing edit, approve refused, edit-out approved).
- [x] **AC-14.R6** Content ≤ 5/week counts in the shop's week (Asia/Ho_Chi_Minh, Monday). Evidence: `test_d24_21_owner_choices.py::test_the_content_week_is_the_shops_week`. And the public UPDATE-grant guard no longer lists P14-C's tables (081 trimmed, `order_cost_fetches` registered); 7 pre-existing tables remain (DEBT).

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
  sellable; ≤ 5 new content cards per shop week (Asia/Ho_Chi_Minh, Monday; was ISO week in UTC until D24.21). — evidence:
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

## P15 — content analysis of seller uploads (contract `contracts/p15-content-analysis.md`)

- [x] **AC-15.1** Migration `082_content_analysis` onto 081 (id ≤ 32 chars), deferred phone
  cleanup re-parented and still last; `content_analyses` tenant_direct, RLS per verb, juli_app
  SELECT/INSERT/UPDATE; no media column. — evidence: `check.sh` migrations PASS at
  `082_content_analysis` (upgrade / downgrade −1 / upgrade), isolation 12 passed;
  `test_content_analyses_are_isolated_per_shop_under_rls` (PG16, as `juli_app`: shop A sees only
  its row, an insert for shop B is rejected); `test_migration_082_…`; grant registry entry.
- [x] **AC-15.2** Upload: slot (type mp4/mov, video ≤ 500 MB, LIVE ≤ 4 GB, ≤ 2 in flight, cap),
  chunked PUT ≤ 32 MB with a signed slot token in `X-Upload-Token` + session + `X-Shop-Id`,
  offset resume, first chunk must be an MP4/MOV box, 6 h expiry; file 0600 under a non-served
  dir, path from Juli's ids only; another shop → 404. — evidence: `test_upload_slot_validation`,
  `test_chunks_offsets_first_box_and_expiry`, `test_the_upload_token_binds_the_slot_and_expires`,
  `test_storage_keys_cannot_escape_the_upload_dir`, `test_the_routes_open_a_slot_take_chunks_queue_and_list`.
- [x] **AC-15.3** Pipeline (video): ffprobe/ffmpeg only (never executed; renamed non-video refused
  before any parser), ASR with glossary, cuts, keyframes every 2 s, vision, ONE scoring call over
  derived signals; numbers from signals (product first second, CTA second by index, cuts / 10 s);
  banned suggestions dropped; claims in the seller's video flagged; file + work dir deleted after;
  cost per stage on the row. — evidence: `test_a_video_is_analysed_costed_and_its_file_deleted`
  (generated testsrc/sine fixture: cuts at 2 s and 4 s, product at 2 s, CTA at 3 s),
  `test_numbers_come_from_the_signals_and_words_are_checked`, `test_the_scoring_prompt_carries_derived_signals_only`,
  transcription / vision wire tests (MockTransport, recording adapter).
- [x] **AC-15.4** LIVE: windows from the first ASR mentions of name / brand / SKU (−2 / +5 min,
  ≤ 3), transcript / keyframes / cuts inside the windows only. — evidence:
  `test_a_live_is_analysed_only_around_the_product_mentions`. TikTok product timing: none exists
  in the API (DEBT).
- [x] **AC-15.5** Monthly OpenAI cap checked before ASR / vision / scoring and when a slot opens;
  over it: `refused`, Vietnamese message, nothing spent, file deleted / 402. — evidence:
  `test_over_the_monthly_cap_the_asr_step_is_refused_and_nothing_is_spent`,
  `test_the_cap_refuses_a_new_upload_with_a_vietnamese_402`, `test_the_month_starts_at_midnight_vietnam_time`.
- [x] **AC-15.6** Task idempotent, per-shop lock, provider error → retry with the file kept,
  last attempt → failed + file deleted; 24 h sweep; queue `content_analysis` routed and consumed
  by the worker unit; beat at :47. — evidence: `test_the_task_is_idempotent_locked_per_shop_and_retries_provider_errors`,
  `test_the_last_failed_attempt_deletes_the_file`, `test_the_sweep_deletes_files_older_than_a_day`,
  `test_the_tasks_are_routed_to_their_own_queue_and_the_worker_consumes_it`.
- [x] **AC-15.7** Content runs use the analyses (best / weakest by TikTok rate, else latest);
  an upload from a run takes the run's product. — evidence: `test_best_and_weakest_analyses_are_picked_by_the_tiktok_rate`,
  `test_the_drafter_prompt_carries_the_analyses_only_when_there_are_some`,
  `test_done_analyses_of_the_product_are_loaded_for_the_run`, `test_an_upload_from_a_content_run_takes_the_runs_product`,
  `test_p14_content_flow.py` unchanged green.
- [x] **AC-15.8** UI: "Phân tích video" block (hook, giây sản phẩm xuất hiện, CTA, nhịp cắt, vấn
  đề, gợi ý, upload + progress, polling, VI errors) in the content run and Phân tích › Nội dung
  row detail; signed-out / no-shop sample = canned analysis, upload disabled, zero `/v1`
  requests. — evidence: `src/components/__tests__/video-analysis.test.tsx` (7),
  `e2e/analytics/video-analysis.spec.ts` (desktop + mobile: sample, signed-in chunked upload →
  done), `e2e/decisions/quyet-dinh-content.spec.ts` (block in the sample run). No artboard (DEBT).

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

## P17 — onboarding speed (D26, D25.12; contract `contracts/p17-onboarding-speed.md`)

- [x] **AC-17.1** Quick scan beside the fast phase: `bootstrap_shop` enqueues
  `shop_quick_scan` on `ingest_priority` once (marker) before the fast phase; the scan
  takes its own `quick_scan` lock (never `cycle`), reads A-34 for the last 14 local days
  (≤ 2 pages) + one diagnoses call for the top 10 by GMV (+ Get Product only for a chosen
  product the catalog lacks), and selects 1–3 cover-image / title / description proposals
  backed by a TikTok code (decision 4 on 14 days, median trigger), priced by D22 on the 14
  days; no LLM. — evidence: `tests/unit/test_onboarding_speed.py`
  (`test_the_scan_window_is_the_last_fourteen_full_local_days`,
  `test_only_cover_title_description_backed_by_a_tiktok_code_become_quick_cards`,
  `test_a_product_not_asked_or_without_a_code_gets_no_quick_card`,
  `test_the_d22_estimate_on_fourteen_days_prices_extra_clicks_through_ctor`,
  `test_max_cards_is_one_to_three`, `test_bootstrap_enqueues_the_quick_scan_once_before_the_fast_phase`,
  `test_the_quick_scan_task_takes_its_own_lock_not_the_cycle_lock`,
  `test_the_quick_scan_routes_to_the_priority_queue_and_history_extends_nightly`,
  `test_a_product_missing_from_the_catalog_gets_a_placeholder_row`,
  `test_the_scan_runs_once_and_skips_when_full_cards_exist`,
  `test_a_failing_read_records_failed_and_never_raises`).
- [x] **AC-17.2** Quick cards take the day-1 Juli slots and are labelled ("Đề xuất nhanh ·
  dựa trên 14 ngày", "Tham khảo", `expected_impact.confidence = reference`, `gmv_method`
  14 ngày); the full diagnosis re-scores a same-lever quick card in place (same row,
  `surfaced_at` kept, TikTok codes reused as evidence, `quick_scan` removed), withdraws one
  it does not confirm at once, supersedes one whose product gets another lever, and fills
  the slots the quick cards left. — evidence:
  `test_quick_cards_take_the_day_one_juli_slots_and_the_full_run_upgrades_them`,
  `test_full_cards_fill_the_slots_the_quick_cards_left`,
  `test_a_quick_card_whose_product_gets_another_lever_is_superseded`,
  `test_the_decisions_endpoint_labels_a_quick_card`.
- [x] **AC-17.3** `GET /v1/shops/me/onboarding`: three steps (quick scan, 60-day backfill +
  diagnosis, history) with status / percent / ETA, `active`, label "Juli đang đọc dữ liệu
  shop · bước N/3", poll 15 s while active, 300 s with only history left, none when done;
  `history_days_available` / target / remaining / `window_90d_available` (≥ 180 days). —
  evidence: `test_status_*` (6), `test_history_days_available_is_contiguous_days_stored`,
  `test_the_onboarding_endpoint_reads_the_shops_state`,
  `test_the_onboarding_endpoint_needs_a_signed_in_shop`.
- [x] **AC-17.4** History to 180 days: look-back 180 (docs: no shop-analytics maximum
  documented; 180 days is the only documented analytics limit — Get Video Performances
  202403); the post-connect chain stops at 60 days (`connect_window_done`, not re-enqueued,
  the poll no longer revives it); nightly `shop-history-extend` (19:43 UTC) enqueues one
  `nightly` run per shop past its fast phase: 2 × 15-day chunks once per local day,
  resumable from the earliest date, per-shop `history` lock, ends at `max_lookback`. —
  evidence: `test_the_look_back_defaults_to_180_days`,
  `test_after_connect_the_chain_stops_at_sixty_days_then_extends_nightly`,
  `test_the_history_task_parks_at_sixty_days_and_nightly_never_re_enqueues`,
  `test_the_poll_keeps_only_the_post_connect_chain_alive`,
  `test_the_nightly_fanout_enqueues_one_run_per_shop_past_its_fast_phase`; existing
  `TestHistoryPhase` (resume, out-of-range halving, rate-limited chunk) unchanged.
- [x] **AC-17.5** 429 in the daily diagnosis: `with_backoff` waits 2/4/8/16/32 s (cap 60,
  jittered, env) then raises `ThrottledError`; `video_windows` then skips the video tables
  for the cycle (no `posted_in_window` fallback), other tables kept, counter
  `video_windows_throttled_skips` logged. — evidence: `test_shop_diagnosis_video_windows.py`
  (`test_backoff_is_exponential_jittered_and_capped`, `test_a_non_throttle_error_is_not_retried`,
  `test_still_throttled_details_skip_the_video_tables_instead_of_the_fallback`,
  `test_a_still_throttled_list_also_skips_without_whole_window_reads`,
  `test_the_job_drops_only_the_video_tables_when_windows_are_skipped`).
- [x] **AC-17.6** Cost reads: orders of the last 30 days up to 60 per pass per cycle before
  older ones at 10, the fast tier waiting for the rate-limit window within 600 s and the
  cycle deadline, a 429 / permission error still stopping at once; env-configurable. —
  evidence: `test_order_costs.py` (`test_recent_orders_read_up_to_sixty_a_cycle_before_older_ones_at_ten`,
  `test_the_fast_tier_waits_for_the_window_instead_of_stopping`,
  `test_the_wait_budget_bounds_the_cycle_and_older_orders_never_wait`,
  `test_a_429_in_the_fast_tier_still_stops_at_once`, `test_fast_tier_settings_come_from_the_environment`).
- [x] **AC-17.7** Migration `084_onboarding_speed` (≤ 32 chars, after 081 on this branch,
  phone cleanup re-parented and last) passes upgrade / downgrade / upgrade on a fresh PG16;
  as `juli_app`, the quick scan writes only its shop's rows and the onboarding read never
  sees another shop's state. — evidence: `check.sh --since 09960b20` migrations PASS at 084;
  `tests/integration/test_onboarding_speed_two_tenant.py` (3).
- [x] **AC-17.8** Demo: the strip on Trang chủ / Quyết định / Phân tích for a signed-in user
  with a shop, polling at the server's interval and re-reading Quyết định's cards while
  active; quiet history note; nothing when done; signed-out / no-shop samples unchanged and
  make no onboarding request; quick-card chip + "Độ tin cậy: Tham khảo". — evidence:
  `apps/demo/src/__tests__/onboarding-strip.test.tsx` (15),
  `quyet-dinh-p10.test.tsx` ("P17: a quick-scan card shows its label chip…", "P17: a full
  card … shows no quick chip"), `e2e/onboarding/onboarding-strip.spec.ts` (3 × projects).

## P32 — Shopee ISV reviewer access (D42; contract `contracts/p32-reviewer-access.md`)

- [x] **AC-32.1** Contract `contracts/p32-reviewer-access.md` written before code: where the
  role lives, how the session is pinned to Fujiwa, every write path the reviewer must not reach
  (listing / image / price / promotion / content publish / Hoàn tác / rules / settings / shop
  connect / invites / uploads / ops) and how each is barred, the simulated execute response, and
  the provisioning command. — 5e3c1410 (first commit of the branch, before any code); §2 table
  lists every write path and its bar.
- [x] **AC-32.2** Email + password sign-in on demo.app-juli.com for team-created accounts
  (GoTrue password grant); wrong password / expired / revoked → Vietnamese errors; no password
  sign-up; Google and OTP doors unchanged. — 23a9a77d (`signInWithPassword`,
  `components/partner-sign-in.tsx` on `/auth/email#doi-tac`, dictionary `auth.password.*`),
  f42d8521 `lib/__tests__/password-sign-in.test.ts` (success + each error), 5411b39c
  `e2e/auth/reviewer-sign-in.spec.ts` 6/6; existing `e2e/auth` specs unchanged and green.
  Live sign-in not exercised (no deploy; owner step in LOG).
- [x] **AC-32.3** Reviewer accounts: role `reviewer`, platform label, `expires_at` (default 30
  days); a provisioning command creates / renews / revokes one; an expired or revoked reviewer
  gets 401/403 on every `/v1` route. — 62bd4c1d (migration `090_reviewer_accounts`, ops-only
  table), 6f6d2729 (`python -m juli_backend.services.reviewer.cli`; password printed once, never
  stored); `test_reviewer_cli.py` (3), `test_reviewer_access.py::
  test_denied_reviewer_gets_403_everywhere[expired|revoked|unknown]`,
  `::test_renew_and_revoke_take_effect`; a denied reviewer is refused inside
  `get_current_user`, i.e. on every Supabase-authenticated route.
- [x] **AC-32.4** A reviewer session is pinned to Fujiwa (cannot read another shop, cannot pick
  a shop id) and every name / id / title it receives is masked (D25.6); Trang chủ, Phân tích,
  Quyết định render real Fujiwa magnitudes. — 89f7b3f5 (`REVIEWER_SHOP_ID`, alias-only
  `X-Shop-Id`, ops view-as scope, `ReviewerMaskMiddleware`); `test_reviewer_access.py::
  test_reviewer_cannot_pick_a_shop[real|other|garbage]`,
  `::test_decisions_are_masked_with_real_magnitudes` (same numbers as the seller's own
  response), `::test_mask_replaces_titles_in_free_text_brand_words_urls_and_long_ids`;
  `test_reviewer_no_write.py::test_two_tenant_reviewer_never_sees_the_other_shop` (every
  allowlisted read); PG: `tests/integration/test_reviewer_two_tenant.py`. Rendering checked
  with mocked responses in the e2e spec, not against live Fujiwa data (no deploy).
- [x] **AC-32.5** Duyệt → Thực thi works end to end for a reviewer: the response shows the
  change that would be sent, marked simulated; nothing is enqueued, no TikTok write client is
  built, no card / run / rule row of Fujiwa changes. — 89f7b3f5 (`POST
  /v1/reviewer/decisions/{id}/simulate`, `services/reviewer/simulation.py` imports no TikTok
  code), 3740b531 (UI `reviewer-simulation`); `test_reviewer_access.py::
  test_simulated_approve_then_execute`, `test_reviewer_no_write.py::
  test_simulated_approve_and_execute_change_nothing` (whole-DB snapshot + tripwires).
- [x] **AC-32.6** **No-write proof**: a test drives every write route as a reviewer and fails if
  any TikTok write, executor enqueue or Fujiwa row change happens; a two-tenant test shows a
  reviewer never sees another shop. — 7376840d `tests/unit/test_reviewer_no_write.py::
  test_every_route_as_reviewer_writes_nothing` (every route of the real app, real token; trips
  on `TikTokClient()` / client factories / httpx + requests network / `Task.apply_async` /
  `Celery.send_task`; whole-DB snapshot; mutation-checked: allowlisting approve fails it on
  `Task.apply_async`), `::test_allowlist_is_pinned_to_real_routes`,
  `::test_two_tenant_reviewer_never_sees_the_other_shop`; d915fe2c
  `tests/integration/test_reviewer_two_tenant.py` (PG16, `juli_app`, RLS) 2 passed.
- [x] **AC-32.7** UI: a persistent banner "Tài khoản dùng thử cho đối tác · dữ liệu shop đã ẩn
  tên · thao tác chỉ mô phỏng" (dictionary), simulated result screen, no connect / invite / upload
  entry points for a reviewer. — 3740b531 (`reviewer-banner`, `reviewer-simulation`, entry
  points hidden, `/auth/connect-shop` → `/`, all writes read-only except Duyệt); dictionary
  `reviewer.banner` / `reviewer.simulated` / `reviewer.read_only_title`; f42d8521
  `components/__tests__/reviewer-mode.test.tsx`, 5411b39c e2e (no `/approve` request).
- [x] **AC-32.8** Every reviewer sign-in and action is audited with the platform label. —
  89f7b3f5 (`ops_audit_log`, actor `reviewer:<platform>:<email>`: `reviewer_sign_in` once per
  Supabase session, `reviewer_simulated_approve/_execute`, `reviewer_write_refused`,
  `reviewer_read_refused`; account create / renew / revoke); `test_reviewer_access.py::
  test_sign_in_audited_once_per_session_with_platform`, `::test_refused_write_is_audited`;
  the no-write sweep asserts one refused-write row per refused write.
- [x] **AC-32.9** Landing names Shopee in text ("đang tích hợp qua Shopee Open Platform");
  `/privacy` and `/terms` (VN + EN) carry a Shopee section and no longer say Shopee support is
  "in development"; no claim the trial account cannot show.
  Evidence: d5b1c276 (hero) + 767e9797 (privacy 4A VN/EN, terms VN+EN). Tests (landing vitest,
  Node 20, 63/63): `sections.test.tsx` hero names Shopee in text; `legal-pages.test.tsx`
  "/privacy has a Shopee section (VN + EN) and no 'in development' line", "/terms covers Shopee
  as 'đang tích hợp' in VN and EN", "translates every section 1–12" (now incl. 4A). Landing lint,
  type-check, `next build` clean; built HTML contains the Shopee text on /, /privacy, /terms.
- [x] **AC-32.10** `fasttrack/shopee-isv-services-information.md`: English description +
  numbered reviewer steps matching what shipped, the account's expiry noted, no video. — evidence:
  `fasttrack/shopee-isv-services-information.md` (2026-10-15; written for the D42 amendment sample
  shop, labels checked against `partner-sign-in.tsx` and `dictionary.md` `reviewer.*`).

- [x] **AC-32.12** (P32-E, D42 amendment 2) In sample mode every seller write is usable as a
  labelled browser-side simulation ("Mô phỏng · không gửi tới TikTok"; settings "Mô phỏng · không
  lưu"): Từ chối with reasons, Duyệt → Thực thi → the sample run (consent edits, cover photo,
  Seller Center, content drafts use / redraft / published), the run timeline, Đo lường day 7 / day
  14, Hoàn tác, Quy tắc (Quyết định + Cài đặt), Phân tích video; connect / invites / ops stay
  hidden; a full session's only request is `GET /v1/reviewer/me`; the pinned reviewer, a seller
  and the signed-out sample are unchanged; no backend change. — a278a3b5;
  `apps/demo/src/components/__tests__/reviewer-all-features.test.tsx::
  a full session uses every simulated write and sends nothing but GET /v1/reviewer/me` (real
  `DemoShell` + `DecisionsPageClient` / `SettingsPageClient`; fetch, XMLHttpRequest, EventSource
  and sendBeacon spied; `expect(requests).toEqual(["GET /v1/reviewer/me"])`), `::the labels belong
  to the reviewer's sample only`, `::a reviewer pinned to a real shop stays read-only`;
  `reviewer-sample-mode.test.tsx` (Từ chối now enabled); existing `sample-quyet-dinh`,
  `quyet-dinh-content`, `reviewer-mode`, `replay-module-graph` tests unchanged and green (demo
  vitest 152 files / 1926 passed).
- [ ] **AC-32.11** `check.sh` green on the integrated branch; deployed; a fresh browser signs in
  as the Shopee reviewer and walks the steps.

## P33 — app-juli.com business site and indexing (D43)

- [x] **AC-33.1** (A) Shared helpers in `apps/landing`: per-page metadata (title, description,
  absolute canonical, OG / Twitter with a 1200×630 image), JSON-LD component, Organization +
  WebSite on every page, BreadcrumbList helper, a route registry feeding `sitemap.ts` with
  lastmod; existing pages migrated.
  — P33-A 875fb83b, 70323acb: `apps/landing/src/lib/seo/` (README = API for P33-B/C/D);
  `seo.test.tsx` (12 tests: every page registered, titles ≤ 60 / descriptions ≤ 155 unique,
  sitemap = registry with lastmod, Organization taxID/address/ContactPoint, no sameAs, Offer
  500000 VND); `pnpm check:seo` on the built site: 7/7 (6 routes + uniqueness); local
  `curl /sitemap.xml` lists 6 URLs with `<lastmod>`.
- [x] **AC-33.2** (A) `/product` → 301 `/san-pham` (stub page until P33-B), and any other renamed
  URL redirected; 404s stay 404.
  — P33-A 875fb83b: `RENAMED_PATHS` in `apps/landing/next.config.ts` (`statusCode: 301`); local
  `next start`: `curl -I /product` → `301 location: /san-pham`, `/nope` → 404; nginx proxies
  every path (no override; comment added in `infra/nginx/app-juli.com.conf`); test "301s each
  renamed URL to a registered page". `/product/` takes Next's 308 to `/product` first.
- [x] **AC-33.3** (A) demo.app-juli.com and ops.app-juli.com send `X-Robots-Tag: noindex, nofollow`
  and `<meta name="robots" content="noindex">` on every page; their robots.txt does not block
  crawling.
  — P33-A 93d8455c: `next.config.ts` headers() on `/:path*` + middleware on every host;
  layout `robots: noindex, nofollow`; `app/robots.ts` = `Allow: /`. Tests `noindex.test.ts` (3)
  + middleware "noindex on every response of every host". Local `next start` (Host header):
  demo `/`, `/decisions`, `/robots.txt`, 404s and ops `/` (307), `/ops`, `/decisions` (404) all
  carry `X-Robots-Tag: noindex, nofollow`; HTML has `<meta name="robots" content="noindex,
  nofollow">`. Live today: demo robots.txt is Cloudflare's content-signal comments only (no rules),
  ops is behind Cloudflare Access (302 to login, never crawlable). Owner step in LOG.
- [x] **AC-33.4** (A) PageSpeed fixes: images with width/height, contrast failure fixed, legacy JS
  (modern browserslist) and unused JS reduced, cache headers for static assets documented for the
  VPS; Lighthouse mobile on a production build recorded (target Perf ≥ 95, LCP < 2.5 s).
  — P33-A 875fb83b..HEAD. Lighthouse 12.8.2 mobile, local `next start`, A/B interleaved with
  e1c6d68f (5 runs each, host load avg 9–18 from parallel agents, so Perf/TBT are noisy):
  A11y 0.96 → **1.00** (contrast + unsized images pass), Best Practices 0.96 → **1.00**
  (favicon 404 gone), SEO 1.00; page weight 282 → **229 KB**, images 76 → **17 KB**
  (image-delivery savings 71 → 14 KiB, the rest is the hero poster P33-B replaces). Perf median
  0.78 → 0.73 (run spread 0.40–0.91 both sides; best new run 0.95, LCP 2.46 s); LCP median
  2.77 → 2.66 s. **Target not demonstrated locally** — LCP is the hero text, render-delay bound by
  framework JS; legacy-JS (13 KiB est.) is Next's built-in 1.4 KB polyfill-module and unused-JS
  (28 KiB) is react-dom — neither removable by config (DEBT). Cache: `/media/*` immutable 1 y,
  `/og`, `/videos` 1 week (next.config.ts), documented in `infra/nginx/app-juli.com.conf`.
  PageSpeed re-run after deploy is AC-33.9.
- [x] **AC-33.5** (B) Homepage per D43.2, H1 → H2 → H3 valid, hero poster + click-to-load video
  (D43.6) with VideoObject, FAQ + FAQPage, no testimonial or invented number.
  — P33-B 2f16f2eb..512c3993 (`fasttrack/p33b-homepage`): one H1, 10 H2 / 24 H3 (marketplace strip,
  problem, 5-step loop, 3 capability blocks → product pages, data safety, audiences, transparency
  with method + sample-data label + company MST/address, pricing teaser, 7-question FAQ, final
  CTA); `HeroVideo` = `<Picture>` AVIF/WebP poster 640/1280 with width/height + ▶, `<video
  preload="none">` mounted only on click; JSON-LD VideoObject + FAQPage = rendered questions.
  Tests `sections.test.tsx` (outline, section order, Shopee status, capability links, D13 scope,
  "no outcome figure / no %", company identity, FAQ ↔ schema, poster-then-video), `cta.test.tsx`;
  `pnpm check:seo` 7/7 on the built site. Removed: "+1–3% GMV", "~1,7 giờ/ngày", "ROI cao",
  "tạo đơn nhập / đồng bộ tồn kho / tạo mã giảm giá"; poster changed to a figure-free frame.
- [x] **AC-33.6** (B) `/san-pham` overview (~1,500 words) + SoftwareApplication / Offer + breadcrumbs.
  — P33-B 512c3993: ~1,680 words in `<main>` (whitespace tokens), H1 + 10 H2 (what Juli is, loop,
  capabilities linking the 3 pages, does / does not do, integrations TikTok live · Shopee đang tích
  hợp · sign-in, data control, audiences, pricing `#bang-gia` 500.000đ/tháng, 6-question FAQ,
  CTA); visible breadcrumb + BreadcrumbList, SoftwareApplication + Offer, FAQPage. Test
  `info-pages.test.tsx`; `check:seo` 7/7.
  — D43 additions (owner 2026-10-15), P33-B 2e37f3c0..4c7788ea: every "Dùng thử miễn phí 3 tháng"
  CTA (home hero / pricing / final, `/san-pham` hero / pricing card / final) → `SIGNUP_URL` =
  `/dang-ky` (P33-F), Pixel-tracked (`cta.test.tsx`, `info-pages.test.tsx`,
  `tiktok-tracking.test.tsx` 6 StartDemo); `/terms` §5 trial sentence (`legal-pages.test.tsx`);
  disconnect copy = contact Juli, team disconnects, no "thu hồi quyền" (`sections.test.tsx`);
  demo door at `/?dang-ky=dung-thu` reads "Đăng ký dùng thử miễn phí 3 tháng"
  (`demo-landing.test.tsx` +4, copy in `dictionary.md` `auth.trial_signup*`).
- [x] **AC-33.7** (C) Three capability pages (~2,500 words each) + `/ket-noi/tiktok-shop`, H1 → H2 →
  H3, one labelled real UI screenshot per H2 (AVIF/WebP, width/height), FAQ, internal links, schema.
  — P33-C 9f8a03b4 (24 screenshots), 2109ac66 (pages): rendered `<main>` words incl. FAQ
  2,776 / 3,114 / 2,495 / 1,572 (phan-tich-shop / de-xuat-va-thuc-thi / do-luong-gmv /
  ket-noi); 6 / 8 / 6 / 4 content H2, each with one `<picture>` (AVIF + WebP 640/1280, width/height,
  alt "… (dữ liệu mẫu)", caption "Dữ liệu mẫu") of the demo's signed-out sample shop (connect /
  onboarding states rendered with mocked API, fictional shop); the FAQ H2 has no screenshot.
  `capability-pages.test.tsx` (16 tests: one h1, a labelled sized screenshot per content H2 with
  files on disk, FAQ dt = FAQPage, Breadcrumb + SoftwareApplication on `/san-pham/*` only, links to
  sibling pages + `/blog` + `/privacy`|`/san-pham`, both CTAs, Shopee only "đang tích hợp").
  Node 20.20.2: landing lint 0, type-check clean, vitest 10 files 91 passed, build OK, `check:seo`
  11/11; `fasttrack/check.sh --since f55809fd` 5/5 PASS. `/blog` links 404 until P33-D (DEBT).
- [x] **AC-33.8** (D) `/blog` index + post template (Article, BreadcrumbList, author, dates) + 3
  pillar drafts of 3,000+ words with internal links; **owner approval recorded before deploy**.
  — P33-D 7ef53a7a, dad5460c, efb19ca7 (branch `fasttrack/p33d-blog`): `/blog` + `/blog/[slug]`
  (SSG, server-rendered Markdown subset, TOC from H2s, breadcrumbs, author "Đội ngũ Juli AI",
  published/updated dates, reading time, FAQ, sources, related posts, links to all five product
  pages); Article + BreadcrumbList + FAQPage JSON-LD. Drafts (word counts, space-separated):
  chi-so-tiktok-shop-ctr-ctor-aov 4,882, toi-uu-the-san-pham-tiktok-shop 4,579,
  cong-cu-cho-nha-ban-tiktok-shop-2026 3,700. All three `status: "draft"` → robots
  `noindex, follow`, not in sitemap.xml, not listed on `/blog` in production. `blog.test.tsx`
  (23 tests: draft noindex + out of sitemap, published indexable + in sitemap, index links no
  draft in production, 3,000+ words, internal links resolve); `check:seo` 11/11 (asserts drafts
  noindex and no indexable page links a draft; also passed with one post flipped to published).
  **Approval: PENDING** — the owner flips `status` per post in
  `apps/landing/src/content/blog/posts.ts` and records it (commit + LOG line), steps in
  `apps/landing/src/content/blog/README.md`. Until then the posts ship as noindex drafts.
- [ ] **AC-33.9** Integration: landing lint / type-check / tests / build green; heading-outline and
  schema checks (a test or script) pass on every route; `check.sh` green; deployed by owner tag;
  PageSpeed re-run recorded.
- [x] **AC-33.10** (E) Search Console monitoring scripts (`scripts/seo/`, owner 2026-10-15: "de-index
  the subdomains, Google indexes only the main domain"): `seo_live_check` (no credentials: on-page
  D43 rules per sitemap URL + noindex on demo / ops with robots.txt still crawlable),
  `gsc_index_audit` (URL Inspection: main pages PASS with self canonical, subdomain pages not
  indexed), `gsc_pull` (one final day per run into SQLite, 25k paging), `gsc_report` (weekly
  actions), `gsc_sitemaps` (list / submit); README with owner setup and the de-index procedure.
  — evidence: `tests/unit/test_seo_scripts.py` (8 passed); `seo_live_check` against production
  2026-10-15: 10 / 14 URLs failing (no canonical / OG / JSON-LD on 6 main pages; demo without
  noindex), ops behind Cloudflare Access counted as out of the index.

- [x] **AC-33.11** (F) Free-trial sign-up (owner 2026-10-15, D43 additions P33-F): `/dang-ky`
  (one H1 "Đăng ký dùng thử miễn phí 3 tháng", value list, accessible mobile-first form: họ tên,
  số điện thoại/Zalo (VN mobile), email, tên/link shop TikTok, vai trò nhà bán / affiliate / đội
  vận hành sàn / agency, optional ghi chú, required consent linking `/terms` + `/privacy`,
  honeypot; works without JS via `POST /dang-ky/gui` + 303) → `/dang-ky/cam-on` (noindex, not in
  the sitemap; "Tự kết nối shop ngay" → `https://demo.app-juli.com/?dang-ky=dung-thu`,
  env-overridable; CompleteRegistration only behind analytics consent). Backend: migration
  `091_trial_signups` (ops_only), public `POST /v1/trial-signups` (validation, honeypot, per-IP /
  e-mail / site-wide limits, IP stored as HMAC only, team e-mail to `TRIAL_SIGNUP_NOTIFY_TO` via
  the ops mailer, succeeds without SMTP, no PII in logs); Ops tab "Đăng ký dùng thử"
  (`GET/PATCH /v1/ops/trial-signups`, Vận hành+, audited); `/privacy` VN + EN paragraph.
  — evidence: commits 64ab3b0a, 6a88d0c5, 4d0eb765, 09b6720b, 7120dbec, 95f428e7, c4a5f0ba,
  3b74c001;
  `tests/unit/test_trial_signups.py` 38 passed (validation, honeypot, rate limits, one row + one
  mail, no SMTP / no recipients, no PII in logs, Ops roles + audit, migration shape);
  `tests/integration/test_trial_signups_two_tenant.py` 14 passed on PG16 (`juli_app` refused
  SELECT/INSERT/UPDATE/DELETE under tenant A, B and no scope; real app as `juli_app`: POST stores
  via `juli_ops` and restores the role, Xem 403, Vận hành list + PATCH + one audit row);
  landing `signup.test.tsx` 32 passed; demo `ops-trial-signups.test.tsx` 6 passed;
  `fasttrack/check.sh --since f55809fd` 5/5 PASS (migrations at `091_trial_signups`; pytest 18 files 390 passed).
