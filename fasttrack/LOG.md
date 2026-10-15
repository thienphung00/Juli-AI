# Log

Append-only. Newest at the bottom. Format: `## YYYY-MM-DD — who` then bullets.

## 2026-10-05 — orchestrator (Claude Opus)

- Grilling session completed: D1–D19 recorded in `DECISIONS.md`.
- #2079 merged by owner. Branch `fasttrack/optimize-product` cut at `0332c405`
  into worktree `/Users/macos/juli-fasttrack`.
- Wrote README, SPEC, ACCEPTANCE, PROGRESS, DECISIONS, LOG, DEBT.
- Next: disable hooks, P0 agent for check.sh + deploy workflow, P1-A and P1-B
  agents in parallel.
- Blocked by the Claude Code permission classifier, left for the owner:
  disabling `.claude` hooks / executor-cache pre-commit gate (AC-0.3);
  committing + pushing these `fasttrack/` docs (AC-0.1, AC-0.2);
  closing Dependabot PRs (AC-0.6).
- Started agents in separate worktrees: P0 deploy (`fasttrack/p0-deploy`),
  P1-A mapper (`fasttrack/p1a-mapper`), P1-B ingestion
  (`fasttrack/p1b-ingestion`). All branch from `0332c405`.
- With owner approval the orchestrator closed 19 Dependabot PRs (AC-0.6).
  Hook disabling + the docs commit/push stay with the owner (classifier blocks
  them even with chat approval).
- P1-A done (Sonnet), `fasttrack/p1a-mapper` @ 4010fece: A-33 impressions /
  clicks / ctr / traffic+sales breakdown per content type; A-34 →
  `conversion_rate`; `merge_product_analytics_rows` helper; products.price from
  `tax_exclusive_price`; category leaf from `category_chains`; migration
  `075_analytics_breakdown` (down 073). 15 new tests. Orchestrator verified: the
  `-k etl|transform|analytics|alembic|migration|mapping|tiktok|product|sync`
  selection fails the same 9 tests on P1-A and on the untouched base
  (pre-existing, missing node_modules) — no regressions.
- P0 done (Opus), `fasttrack/p0-deploy` @ 596f9d0b: `fasttrack/check.sh`
  (migration up/down/up on throwaway PG with prod-URL guard, two-tenant proof,
  gitleaks, ruff, pytest on changed files) and
  `.github/workflows/fasttrack-deploy.yml` (dispatch: validate → backup on VPS,
  verified pg_dump -Fc → check → deploy.sh <sha>). Local full run passed except
  the node_modules contract tests.
- OPEN (owner): the workflow is dispatch-only, and GitHub only dispatches
  workflows present on the default branch (`main`, frozen). Options: land the
  file on `main` once, or add a tag-push trigger (`fasttrack-deploy-*`). The
  orchestrator's attempt to add the tag trigger was blocked pending owner
  decision.

## 2026-10-05 — orchestrator (Claude Opus) — P1 integrated

- P1-B done (Opus) @ add4abd1..ea0142ee: `shop_ingestion_state` table (074),
  `bootstrap_shop` on `ingest_priority`, `shop_history_backfill` on
  `ingest_backfill`, beat `shop-poll-fanout` replaces `fujiwa-poll-cycle`,
  Redis per-shop lock, daily analytics ranges up to `latest_available_date`,
  bounded parallel detail calls, latency events. OAuth callback enqueues
  bootstrap after commit.
- Merged P0, P1-A, P1-B into `fasttrack/optimize-product` (merge 728f67d1).
  Re-chained migrations 073 → 074 → 075 → deferred phone cleanup.
- Found + fixed a latent test-isolation bug: `_isolated_migration_database`
  swapped only DATABASE_URL while alembic prefers DATABASE_DIRECT_URL.
- `fasttrack/check.sh` on a fresh throwaway PG16: all 5 steps PASS. Full
  unit+harness vs base: the only real new failure (MODULE.md allowlist) fixed;
  four others were flaky from running during concurrent edits and pass on
  rerun.
- All P0 + P1 ACs ticked. P2 waits on the FastMoss API trial.
- Deviations from SPEC (accepted): latest_available_date probed via one A-36
  call; bestseller/promotion calls dropped from the scheduled path; CVR lands
  only from single-day (daily incremental) windows, not multi-day backfill.

## 2026-10-05 — orchestrator (Claude Opus) — deploy trigger

- Owner decision: deploys trigger on pushing a `fasttrack-deploy-*` tag (push
  triggers use the workflow file from the tagged commit, so this works while
  `main` is frozen). Validate now accepts `refs/tags/fasttrack-deploy-*`; the
  existing ancestry check still refuses any commit not on the fast-track
  branch, and the VPS re-checks it. `workflow_dispatch` kept for after merge.
  actionlint clean. Not yet run.

## 2026-10-08 — orchestrator (Claude Opus) — D21, D22

- Synced main into the branch (7c31a0a4: ADR-106 amendments, ADR-108 shop
  diagnosis). D21 + P7 tasks recorded; P7-A..D running on fasttrack/p7*
  branches. P7-D done @ debb24d7 (not merged yet).
- Owner confirmed D22: three-tier recommendation (diagnosis → recoverable-GMV
  ranking → day-14 calibration); P3 = TikTok-only shop model for ranking;
  FastMoss (P2) optional. SPEC §4 P2/P3/P6 and PROGRESS updated.

## 2026-10-08 — P7-A agent (Claude Opus) — Phân tích backend

- ADR-108 report is now a backend product. `services/shop_diagnosis_daily/`
  holds the read-only fetch (moved from `scripts/shop_diagnosis_fetch.py`,
  which now wraps it; 429 backoff on every call), the job (per-shop read
  credential, temp-dir snapshot deleted after the build, both rankings built,
  aggregates stored) and the read for the route. The pure `shop_diagnosis`
  package is unchanged, so the `report.json` shape is unchanged.
- Table `shop_diagnosis_reports` (migration `076_shop_diagnosis_reports` onto
  075; deferred phone cleanup re-parented onto 076; classified tenant_direct).
- Task `juli_backend.build_shop_diagnosis` (default queue), enqueued by
  `maybe_enqueue_diagnosis` after a poll cycle whose daily analytics pass ran
  and after the bootstrap fast phase. Idempotent per (shop, end date); end date
  = `analytics_through_date` capped at yesterday UTC+7.
- `GET /v1/demo/analysis` → `{as_of, built_at, ranking, report}`, 404 if none.
- check.sh on a throwaway PG16 (gitleaks not installed locally): all other
  steps PASS. Guard tests (import boundaries, ratchets, route auth invariant,
  grants, beat/routed task registration, chain tail pins) pass.
- Merge note: P7-B may add a migration on 075 too — re-chain whichever lands
  second, and keep the deferred phone cleanup as the tail. Both may touch
  `Enqueuers` in `workers/tasks/shop_ingestion.py` (one added field here).

## 2026-10-08 — P7-B agent (Claude Opus) — Quyết định backend: ADR-106 cards per shop

- `services/optimize_product/daily_funnel.py` + `decision_cards.py` (pure): P1's
  daily product/SKU analytics → ProductFunnel (14 vs prior 28) and card evidence
  (30 vs prior 30, TikTok KPI names, ADR-108 confidence); reuse of `diagnose_all`,
  `build_cards`, report statuses; top 10 ranked by D22 recoverable GMV/day.
- `services/action_cards/optimize_product_cards.py`: plan + emit via the ADR-087
  ladder, withdraw unranked drafts. Hooked inside `emit_scoring_cards`, so the
  P1 hook (`score_and_persist_cards`, unchanged), manual refresh and cdp_speed all
  produce them; shops without product analytics keep the rule card.
- Emission budget: `workflow_max_active` (optimize_product_2 = 5, one slot).
- `/v1/demo/decisions`: `recommendation.diagnosis` / `recommendation.evidence` /
  `expected_impact` (recoverable GMV, rule-based).
- Mapper: A-34 `add_cart_count` under `traffic_breakdown.A34_TOTAL` (no migration).
- Tests: new file 13 passed; related suites (57 files) 689 passed; full unit+harness
  38 failed / 2 errors — 36 identical on base 3ecd5e48 (node_modules contracts etc.),
  2 order-flaky (pass alone), 2 errors were my fixture timing out (fixed, bulk seed).
  check.sh `--since 3ecd5e48 --skip-gitleaks`: ruff + pytest PASS; migrations/isolation
  not run (docker daemon down, no gitleaks); no migration added.
- Next: UI agent consumes the fields; DEBT P7-B lists data gaps (channel blocks,
  diagnoses endpoint, add-to-cart backfill).

## 2026-10-08 — P7-D agent (Claude Opus) — demo lane in fasttrack-deploy

- `fasttrack-deploy.yml`: new `build` job (needs validate, parallel to
  backup/check) checks out the SHA, sets up pnpm/node 20 like release.yml, runs
  `build-release-artifact.sh --app demo` with the NEXT_PUBLIC_SUPABASE_URL/_ANON_KEY
  secrets (build-time verify via `pnpm build`), asserts commit traceability,
  uploads `juli-demo-<short7>`. `deploy` now needs check + build, downloads it,
  scp's it to `~/fasttrack-artifacts/`, and runs deploy.sh with
  DEMO_ARTIFACT_TARBALL so the demo lane runs after the API lane. Preflight now
  refuses only the landing lane. No infra script changed.
- actionlint clean. Not run on GitHub. README deploy section, DEBT (demo half
  struck, landing kept) and AC-7.9 updated.

## 2026-10-08 — P7-C agent (Claude Opus) — demo UI

- Worktree `fasttrack/p7c-ui`, commits 93a6b445 (Quyết định label, D21),
  17002419 (app-kit restyle), 24aca816 (decision cards + evidence mapper),
  65c9c856 (Phân tích report view), plus this docs commit.
- Restyle: kit tokens/classes appended to `apps/demo/src/app/globals.css`;
  bottom nav at every width (rail retired), 1120px column, kit type scale.
- Quyết định: mock recommendation cards; tolerant mapper for P7-B fields in
  `apps/demo/src/lib/decision-evidence.ts` (assumed shape documented there).
- Phân tích: `/analytics` renders the ADR-108 report (`components/shop-analysis/`);
  signed in via `GET /v1/demo/analysis` (`{as_of, built_at, ranking, report}`,
  `?ranking=60d|30d` toggle, 404 → empty state); anonymous → synthetic sample.
  KPI dashboard kept at `/analytics/[metricKey]`, linked from the report footer
  (its data source differs from the report, so it is secondary, not removed).
- recharts added to apps/demo (same ^2.15.4 as @juli/ui) for the timeline.
- Checks: lint/tsc/vitest green on Node 20 (Node 26 breaks jsdom storage —
  pre-existing); `pnpm build:demo` OK with dummy Supabase env, `.next` removed.
- Next: align evidence keys with P7-B; run demo e2e; reject endpoint.

## 2026-10-08 — P7 integration agent (Claude Opus) — P7 integrated

- On `fasttrack/optimize-product` after the A–D merges (8a857b04).
- c446bb2d: Quyết định evidence mapper reads P7-B's real
  `recommendation.diagnosis/evidence/expected_impact` (types added to
  `@juli/contracts`); card shows stage, lever action, trigger, rule-based
  recoverable GMV sentence and the metrics table. Guessed key lists removed;
  fixture captured from the backend endpoint test.
- 44b622ed: Phân tích funnel tiles wrap (auto-fit grid). Screenshots
  before/after at 1280 and 390 in the integration session scratchpad `shots/`.
- ebbe4df0: P7-A debts repaid — per-shop Redis lock `ingest:diagnosis:{shop}`
  on `build_shop_diagnosis`; fetch reads take tokens from the poll's Redis
  per-endpoint window (`shop_diagnosis_daily/pacing.py`, waits, 8 of 10).
- 0041fe29: mypy errors from P7-A/B fixed (full `mypy backend/src/juli_backend`
  clean, as on base). 2f162d25 + d057de8d: guard baselines (MODULE.md drift
  allowlist, surface inventory, test-quality corpus) regenerated for P7.
- Tests: unit+harness vs base 3ecd5e48 — base 9 failed; HEAD after fixes has
  no new failures (pre-existing: agent_workflow_task_wiring ×7,
  cross_tenant_probe, destructive_migration CI-config; full-run-only flakes
  under CPU contention pass alone). check.sh `--since 0332c405` on a throwaway
  PG16: migrations, isolation, ruff, pytest (745) PASS; gitleaks FAIL only on a
  main-origin test false positive (clean vs origin/main). demo: lint 0 errors,
  tsc clean, vitest 1650/1650 (Node 20), `build:demo` OK (dummy env, shell only).
- e2e: 82 passed / 8 failed — restyle/route changes, not nav (see DEBT P7-C).
- Next: owner decides the two e2e specs; deploy tag when ready.

## 2026-10-08 — orchestrator (Claude Opus) — P7 e2e specs follow D21

- Updated `static-asset-render.spec.ts` (body background colour instead of
  the old gradient image; wordmark asserted as gradient text) and the
  accessibility KPI-chart test (`/analytics/gmv-tiktok`). Both specs 18/18
  passed on desktop + mobile-web. Remaining e2e from the integration run: 82
  passed before, so the full suite should now be green; not re-run in full.

## 2026-10-08 — orchestrator (Claude Opus) — D22 formula amended

- Owner confirmed: recoverable GMV follows TikTok's decomposition; at the CTR
  stage extra clicks are multiplied by the product's CTOR. Matches the P7-B
  code. DECISIONS D22 and SPEC §4 P3 updated. Branch pushed to origin.

## 2026-10-08 — orchestrator (Claude Opus) — first fast-track deploy run

- Tag fasttrack-deploy-20261008T0819Z did not trigger (pushed with 16 other
  tags via `git push --tags`; GitHub creates no tag events when > 3 tags are
  pushed at once). fasttrack-deploy-20261008T0821Z ran (run 37749344234):
  validate, build, backup (verified), check all passed; deploy failed at the
  landing preflight because P7 changed `packages/contracts` and
  `pnpm-lock.yaml`, which the landing lane watches. Nothing deployed; the VPS
  clone is left detached at 6edac8b6 (no migration ran).
- Fix: the build job also builds the landing artifact; deploy copies both and
  exports LANDING_ARTIFACT_TARBALL. actionlint clean.

## 2026-10-08 — orchestrator (Claude Opus) — first fast-track deploy LIVE

- Run 37751703616 (tag fasttrack-deploy-20261008T0843Z, d86a1d34): validate,
  build (demo + landing), backup, check, deploy all success. Migrations
  073 → 074 → 075 → 076 applied. API live at releases/d86a1d34, /health ok;
  demo and landing cut over, all asset/route checks passed.
- Found: through https://demo.app-juli.com every `/v1/*` path (decisions,
  analysis, analytics) returns the Next.js 404 — the live nginx vhost lacks
  the `/v1/demo/`, `/v1/auth/`, `/v1/` proxy blocks that the repo's
  `infra/nginx/demo.app-juli.com.conf` has (vhosts are installed only by
  `provision-nginx.sh`, never by deploy). api.app-juli.com answers (401
  without auth). Pre-existing, not caused by P7. Owner action: diff and
  re-run provision-nginx.sh on the VPS.

## 2026-10-08 — orchestrator (Claude Opus) — nginx reprovisioned; login host bug

- Owner re-ran provision-nginx.sh: demo `/v1/*` now reaches the API (401
  unauth on decisions/auth, 200 on analytics). www.app-juli.com answered 526:
  the repo vhost had no 443 block for www. Added one (redirect to apex); the
  cert must be expanded to www once with certbot.
- Google sign-in opened https://db.<ref>.supabase.co/auth/v1/authorize →
  certificate error: the NEXT_PUBLIC_SUPABASE_URL repo secret holds the
  Postgres host, not the project API URL (https://<ref>.supabase.co). Owner
  fixes the secret; the demo build now fails on a db.* host.

## 2026-10-08 — P8-A agent (Claude Opus) — ADR-109 d.5 rankings, DB only

- Branch fasttrack/p8a-rankings, commits 47ccfc4f, 0500f337, 4d7ee200,
  f51da34b, dcd6af07 + the integration test and these notes.
- Pure `services/shop_diagnosis/rankings.py`: per stream × clickable metric
  (Thẻ sản phẩm ×6 incl. the two CTOR steps, Tab Cửa hàng ×4, LIVE ×3, Video ×2
  when `VideoWindowMetrics` are given) GMV/day per row by log-share, sequential
  at a zero side, prior median for missing prior rates; content rows vs the
  stream's prior rate; ADR-108 labels on the metric's quantity; top 10 per
  direction + few/others/mix closing rows reconciling to the stream factor.
- Storage: migration `077_metric_rankings` → `shop_metric_rankings`, one row per
  (shop, end_date, stream, metric) with the table's JSON; deferred phone
  cleanup re-parented onto 077. Read: `read.latest_metric_ranking` +
  `GET /v1/demo/analysis/rankings?stream=&metric=`.
- check.sh (throwaway PG16, `--skip-gitleaks`): all steps PASS, 153 tests.
- Fujiwa snapshot dry-run (local, not stored): 13 tables, all reconcile.
- Next: P8-C's migration re-chains after 077 (or vice versa) at merge; P8-B
  wires `video_metrics` in the worker task; P8-E reads the endpoint.

## 2026-10-08 — P8-B agent (Claude Opus) — per-video 30/30 data (AC-8.2)

- Spec answer (`tts-openapi-guide` OAS analytics, v202509): Get Shop Video
  Performance List, Get Shop Video Performance Details and Get Shop Video
  Product Performance List all REQUIRE `start_date_ge`/`end_date_lt`. The list's
  `views` is "during the selected time range" and it has SKU orders/GMV but no
  product impressions (its CTR is clicks ÷ views); details with
  `granularity=1D` gives dated daily intervals with product impressions,
  clicks, CTR, GMV, views, but no SKU orders. Today's fetch asks for the 60-day
  window, so the snapshot's videos.json holds 60-day totals (Fujiwa: top-40
  sum 99.8M ₫ ≤ 167.5M ₫ A-34 video GMV), not lifetime ones.
- 5498e2ee: details endpoint (GET wrapper, production-read allowlist pattern,
  shop-diagnosis rate-limit gate key) + tests.
- 3e74be51: `services/shop_diagnosis_daily/video_windows.py` —
  `fetch_video_windows(resources, snapshot)` → `VideoWindowMetrics` (per video:
  id, title, posted_at, last/prior `WindowMetrics`, basis). 2 list walks + ≤ 40
  details calls per shop/day (top 20 by window GMV per window, deduplicated).
  Fallback `posted_in_window` when a list or the first details call fails.
- 7542e04b: `scripts/shop_diagnosis_fetch.py --video-windows` for the owner's
  live check.
- Tests: video_windows 8, promotion_search 23, scripts 9, shop_diagnosis_daily +
  two-tenant 58 passed (2 PG skips), allowlist/capability/module guards 146
  passed; ruff + mypy clean.
- Next: owner live check (DEBT P8-B); orchestrator wires it into job.py for P8-A.

## 2026-10-08 — P8-G agent (Claude Opus) — get_product_diagnoses read tool (AC-8.4)

- Added READ/AUTO tool `get_product_diagnoses` (tools/product.py, labels in
  tools/diagnosis_labels.py) and made it playbook step "0", before
  `get_product_information`, with guidance: read TikTok's codes first, change no
  unflagged field unless the card's lever says so.
- `tool.completed.summary` is now per-tool via `tool_completed_summary`
  (runner/seller_facing_copy.py): `Có mã: "Tiêu đề quá ngắn"` / `Không có mã chẩn đoán`;
  every other tool still says `Hoàn tất`. SSE envelope and event types untouched.
- Updated pinned tests: step list, registry/handler sets, descriptions, wall-clock
  bound (105 -> 115s tools, 445s total), composed-prompt goldens, budget record
  (2992/3000), golden scenario sha, dictionary.md rationale, MODULE.md.
- Known env failures unchanged: agent_events_contract (node_modules missing),
  agent_workflow_task_wiring x7 (pre-existing).
- Next: owner reads one live product's codes to confirm labels (DEBT).

## 2026-10-08 — P8-G agent (Claude Opus) — diagnoses soft-fail

- `get_product_diagnoses` now catches TikTokAPIError/TransportGuardError only: returns
  `codes=[]`, `unavailable=true`, logs WARNING `get_product_diagnoses_unavailable`;
  summary "Không đọc được chẩn đoán TikTok — tiếp tục với thông tin sản phẩm". Test: run
  continues to get_product_information. DEBT item struck.

## 2026-10-08 — P8-D agent (Claude Opus) — app shell + Trang chủ (AC-8.5)

- Branch fasttrack/p8d-shell: 165ce61d (mapping + ShopReportProvider),
  80c6e118 (shell, header, Home, guard tests), f60ce932 (e2e), docs commit.
- Shell (`components/demo-shell.tsx`): `AppNavigation` rail ≥ 768px / bottom
  bar below (one `<nav>`), Juli shown but locked (aria-disabled, lock,
  "Sắp có: nhật ký 24 giờ"); `ShopHeader` with avatar menu (Cài đặt, Đổi shop,
  Đăng xuất; anonymous: Đăng nhập, Làm mới Demo) and "Juli đang chạy · cập nhật
  HH:MM" from `built_at` (omitted without a report; sample says "Dữ liệu mẫu").
  No global stepper. Retired: assistance aside, mode toggle, Cài đặt tab,
  HomeLauncher, `lib/mock-data.ts`.
- For P8-E/P8-F: page goes in the shell's `<main>` slot; start with
  `AppPageHeader` (`components/app-shell/page-header.tsx`); Home cells link
  `/analytics?tab=san-pham|noi-dung&stream=…&metric=hien-thi|ctr|ctor|aov`;
  `useShopReport()` holds the acting shop's envelope. Documented in MODULE.md.
- Trang chủ: GMV/Đơn/AOV (daily avg × window days; whole orders from
  `orders_last`), 5-stream matrix tinted by direction, Liên kết greyed,
  missing stream → "Chưa có dữ liệu", Tab cửa hàng CTOR/AOV "ước tính".
- Guards changed on purpose: navigation/demo-shell/home tests rewritten,
  demo-landing + replay-module-graph entry (sample-home), analytics-live-wire
  (refresh via menu), assistance test removed, issue-397 contract
  (nav in `lib/app-navigation.ts`, Home = overview), e2e helpers/specs.
- Gates: see AC-8.5 evidence. Next: P8-E/P8-F build inside the shell; DEBT
  P8-D lists ngành/SKU data, double analysis fetch, dead CSS/state cleanup.

## 2026-10-08 — P8 integration agent (Claude Opus) — video rankings wired; merged-head verification

- fe21ec7b: the worker body (`workers/tasks/shop_diagnosis.py`) passes
  `job.fetch_ranking_videos` as `video_metrics`; it runs P8-B's
  `fetch_video_windows` in the fetch thread with the snapshot's own
  rate-limited resources and pacing (one credential resolution; ≤ 2 list walks
  + 40 details calls) and `video_windows.ranking_videos` converts the result.
  A failing video fetch, or a ranking that fails only with videos, keeps the
  other 13 tables. `VideoMetricsFn` is now `(resources, snapshot)`.
- Type clash fixed: the ranking's per-video input is `rankings.VideoWindowCounts`
  (was `VideoWindowMetrics`, `last` now optional); P8-B keeps
  `VideoWindowMetrics` (container) of `VideoWindowRow` (per video) of
  `WindowMetrics` (one window).
- Merge regressions fixed: f3b5bffc mypy (P8-G `is_diagnosis_code` →
  `TypeGuard[str]`); fc07b873 two new import-boundary deep imports in the
  rankings route (back to the base's 56); 5fe28816 guard baselines
  (surface_inventory `get_product_diagnoses`, TikTok facade export, test-quality
  layer 449 → 452).
- Verification vs base bd55f06b (tests/unit + tests/harness, no DATABASE_URL):
  base 9 failed / 6362 passed; head 12 failed / 6433 passed before 5fe28816,
  the 3 extra were the guard baselines above; the 9 shared are pre-existing
  (agent_workflow_task_wiring ×7, cross_tenant_probe demo-runs-events 404,
  destructive_migration_isolation CI-disposable). mypy clean (530 files), ruff
  clean, credentials-in-url / cycles / ownership PASS.
- check.sh --since bd55f06b (throwaway PG16 via initdb on a random port,
  deleted afterwards; gitleaks run): OK — migrations up/down/up at 077, isolation
  12 passed, gitleaks, ruff (54 files), pytest 55 files / 779 passed. A second
  run on the same already-migrated database fails the privilege check by
  design; use a fresh database per run.
- Not done: merging fasttrack/p8c-undo-rules — the merge command was refused by
  the session's permission policy; left for the owner/orchestrator.

## 2026-10-08 — P8-C agent (Claude Opus) — before/after + Hoàn tác, rule store, day-7 guardrail

- Branch `fasttrack/p8c-undo-rules`, cd626005..HEAD. Migration
  `078_rules_and_write_values` onto 076 (P8-A's 077 is parallel — re-chain at
  integration); deferred phone cleanup re-parented onto 078 (tests updated).
- Every recorded agent WRITE (`update_product_listing`, `update_product_price`)
  stores per field the value read just before and just after (sent value when
  TikTok still shows the old one) in `run_write_values`.
- Hoàn tác: `POST /v1/demo/runs/{id}/revert` creates a normal `workflow_runs`
  row (`reverts_run_id`) run by the same `WorkflowRunner` with a revert playbook
  (read → CONFIRM restore → status) and a deterministic planner instead of the
  LLM — SSE events, confirmation endpoint, ledger unchanged. Refuses in
  Vietnamese (409) on external change (also re-checked at the write →
  `concurrency_conflict`), unfinished run, nothing written, price, revert-of-revert,
  already reverted.
- Rules: `shop_rules` + `/v1/demo/rules`; max_open_cards drives Optimize
  Product's surfacing cap, auto_levers decides executable/approvable cards
  (promotion levers never). set_by from request (no team role exists → DEBT).
- Day-7: the impact reader's preliminary pass raises a `run_revert_questions`
  row when a non-target band metric exceeds the seller's ±%; never reverts.
- Guard baselines regenerated (module drift allowlist, surface inventory,
  test-quality layer 449→451). check.sh OK; full unit+harness only pre-existing
  / node_modules failures. See DEBT "P8-C".
- Next: P8-F reads `/changes`, `/revert`, `/revert-questions`, `/rules`.

## 2026-10-08 — P8-E agent (Claude Opus) — Phân tích UI (AC-8.6)

- Branch fasttrack/p8e-analysis: aca17597 (generator + sample rankings),
  fdd8410f (UI), 8c2fdfb2 (vitest), 0cd3598b (e2e + layout/contrast fixes),
  docs commit.
- `/analytics` = ADR-109 Phân tích inside DemoShell (`components/phan-tich/`,
  pure model in `lib/phan-tich/model.ts`): Sản phẩm / Nội dung sub-tabs, one
  funnel row per stream, clickable cells per d.4 (Thẻ sản phẩm's CTOR tile
  carries Thêm giỏ/bấm and Đơn/thêm giỏ, both ranked), URL `tab/stream/metric`
  (Home links land). Bottleneck = across the sub-tab's two streams, the
  clickable factor with the most negative report contribution labelled "Rõ";
  outlined + "✦ Juli gợi ý" from the report's numbers, no "Mục tiêu" (backend
  has none); h1 from it ("Thẻ sản phẩm: CTOR giảm 15,2 %"). Ranking table from
  `GET /v1/demo/analysis/rankings` (memoised per cell), Kéo xuống/lên, closing
  rows + the other direction folded so the shown rows sum to "Tổng =
  stream_factor_gmv"; 404 → "Chưa có bảng xếp hạng cho chỉ số này". Ví dụ panel
  (hero 5-channel profile when present), hero list expanding in place,
  Khuyến mãi / Dòng thời gian / Cách tính collapsed ("Xem thêm").
- Report read through `useShopReport()` — P8-D's double fetch repaid. Retired
  `ShopAnalysisView`, its signed-in/sample wrappers and their test; hero
  ranking 60d/30d toggle dropped (DEBT).
- `scripts/demo_analysis_sample.py`: real `build_report` + `build_rankings`
  over `tests/support/shop_diagnosis.py` helpers + synthetic LIVE sessions and
  video windows; regenerates sample-report.json byte-identical, writes
  sample-rankings.json; `--check`.
- Gates: type-check, lint (0 errors), vitest 1657/1658 (pre-existing
  replay-scenario byte check, fails on the merge base too), e2e 102/102,
  build:demo OK. Screenshots in the session scratchpad `shots-p8e/`.
- Next: integration — re-copy the golden scenario fixture; P8-F reuses the
  page header pattern; DEBT P8-E lists target/diagnosis data, step default,
  label duplication with Home.


## 2026-10-09 — Verification of aa91074d against bd55f06b

- `fasttrack/check.sh --since bd55f06b` on a fresh local Postgres 16: migrations
  PASS (head 078_rules_and_write_values), isolation 12 passed, gitleaks PASS,
  ruff PASS (85 files), pytest PASS (67 files, 891 passed).
- Chain 076 -> 077 -> 078 up/down/up verified. The deferred 074 phone cleanup
  applies on top of 078 and is irreversible by design (NotImplementedError on
  downgrade). Its id (35 chars) exceeds alembic_version's varchar(32); it
  applied only after widening the column in the throwaway DB. Pre-existing
  (same id at base) — production must have a widened column, check before apply.
- tests/unit + tests/harness (-m "not live and not demo_contract", no
  DATABASE_URL): 9 failed / 6407 passed — exactly the 9 known pre-existing.
  mypy backend/src/juli_backend clean (544 files); ruff clean.
- apps/demo (Node 20.20.2): lint 0 errors (14 warnings), type-check OK,
  vitest 1657/1658. Failure: replay-scenario byte check — merge-caused:
  7a901f39 re-captured tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json
  (prompt_sha256 changed) but apps/demo/src/lib/run-surface/golden-scenarios/
  copy was not refreshed. Needs a frontend copy (cp fixture over it); not done
  here (apps/ off limits).

## 2026-10-09 — P8-F agent (Claude Opus) — Quyết định UI (AC-8.7)

- Branch fasttrack/p8f-decisions: d1695f17 (golden scenario re-copied from
  `tests/fixtures` — orchestrator note; only `prompt_sha256` changed,
  `expires_at` already rebased at runtime; DEBT P8-E item repaid), 44a5c340
  (UI), 725d9136 (vitest), 800e7b80 (e2e + mobile layout), docs commit.
- Signed-in /decisions = `SignedInQuyetDinh` with Đề xuất / Đang thực hiện /
  Đo lường (URL `tab`, `run`, `quy-tac`). Grouped compact cards (stream ×
  weak stage, GMV dự kiến = Σ recoverable/day × 30), price cards excluded,
  sequential batch approve, blocked until a stability band is set; rules
  editor (Sửa + signed-in /settings) with team/seller set_by; SSE-only step
  timeline (`buildRunTimeline`) with inline consent; queue in ledger
  sections; before → after + Hoàn tác; Đo lường placeholder + Hoàn tác?
  questions. `SignedInDecisions` + its test retired; contracts gained
  `lever.evidence`, `tiktok_product_id`.
- Anonymous /decisions unchanged (fixtures; e2e asserts zero /v1).
- Gates: type-check, lint 0 errors, vitest 1667/1667, e2e 106/106,
  build:demo OK. Use Node 20 explicitly: `~/.local/bin/node` (v26) shadows
  nvm and breaks jsdom localStorage (269 false failures).
- Screenshots 1440/390 in the session scratchpad `shots-p8f/`.
- Next: integration; DEBT P8-F (anonymous sample, measurement API, revert flag
  on the runs list).


## 2026-10-09 — orchestrator (Claude Opus) — P8 integrated

- Merged P8-C (06a95d38; 078 re-chained onto 077, phone cleanup last), P8-E
  (edbf937b), P8-F (8e873ffc). Verification on aa91074d: check.sh OK on a
  fresh PG16 (migrations to 078, isolation 12, gitleaks, ruff, pytest 891);
  unit+harness 6407 passed, only the 9 known failures; mypy clean.
- After P8-F: consent countdown reads in days past 24 h (was "633166 giờ").
  Demo vitest 1668/1668, type-check clean, lint 0 errors; backend
  contract/decision tests 762 passed.
- Owner updated NEXT_PUBLIC_SUPABASE_URL (2026-10-09 01:28 UTC); takes effect
  with the P8 deploy build.
- Open: anonymous /decisions still shows the legacy fixture flow (P8-F debt);
  deferred phone-cleanup revision id is 35 chars vs varchar(32) — check prod
  before running that manual step.

## 2026-10-09 — P9-A agent (Claude Opus) — Email sign-in (AC-9.1)

- Branch fasttrack/p9a-email: 6ad94d8b (OTP client + magic-link callback),
  0fdbcbd0 (UI), 6ebd3220 (vitest), e4b54f6b (e2e + CSS), docs commit.
- "Đăng nhập bằng email" beside Google: landing sign-in door (h2 now
  "Đăng nhập"; disclosure → email → "Gửi mã" → 6-digit code → "Xác nhận"),
  anonymous avatar menu ("Đăng nhập" relabelled "Đăng nhập với Google" + new
  email item → `/auth/email`). Plain fetch to GoTrue (`/auth/v1/otp`
  with `create_user` + `redirect_to=<origin>/auth/callback`,
  `/auth/v1/verify` type=email); session stored exactly like Google, then a
  full load to `/auth/connect-shop`. Magic link = same implicit hash →
  existing callback; `otp_expired` → Vietnamese. 60 s resend cooldown,
  Vietnamese copy for format / wrong-or-expired code / rate limit / network
  (dictionary `auth.email.*`). No env, no backend change: the backend accepts
  any same-project token with aud=authenticated + UUID sub.
- Intentional guard edits: tests pinning the menu label "Đăng nhập" (2 e2e,
  demo-shell) → "Đăng nhập với Google"; replay module-graph guard allows the
  sign-in door's Supabase fetch, pinned to the two /auth/v1 paths.
- Gates: type-check, lint 0 errors, vitest 1699/1699, e2e 114/114,
  build:demo OK (dummy env), issue-397 contract 11/11. Screenshots 1440/390 in
  the session scratchpad `shots-p9a/`.
- OWNER (Supabase dashboard, project used by NEXT_PUBLIC_SUPABASE_URL):
  1. Authentication → Sign In / Providers → Email: enable; "Confirm email" may
     stay on (verify confirms); keep "Allow new users to sign up" on.
  2. Same page (or Authentication → Settings): Email OTP Expiration 600–900 s;
     Email OTP Length 6.
  3. Authentication → Emails → Templates: BOTH "Magic link" and "Confirm
     signup" (a first-time email gets the signup template) must show
     `{{ .Token }}`; Vietnamese body, e.g. subject "Mã đăng nhập Juli:
     {{ .Token }}", body "Mã đăng nhập Juli của bạn: <b>{{ .Token }}</b> (hết
     hạn sau 10 phút). Hoặc bấm: <a href="{{ .ConfirmationURL }}">Đăng nhập
     Juli</a>. Nếu bạn không yêu cầu, hãy bỏ qua email này."
  4. Authentication → URL Configuration: Site URL https://demo.app-juli.com;
     Redirect URLs include https://demo.app-juli.com/auth/callback (already
     there for Google — confirm).
  5. Built-in SMTP is for testing only (a handful of emails/hour, may only
     deliver to team addresses): Authentication → Emails → SMTP Settings →
     custom SMTP (e.g. Resend/SES/Postmark on a verified app-juli.com sender
     such as no-reply@app-juli.com, SPF/DKIM set); then raise Authentication →
     Rate Limits → "emails sent per hour".
- Next: owner steps above, then one real sign-in (code + link); check
  `users.email` is filled (DEBT P9-A).

## 2026-10-09 — P9-C agent (Claude Opus) — drop the /analytics/[metricKey] KPI dashboard
- Removed the route and its only-users: `analytics-dashboard`, `analytics-kpi-card`, `analytics-supplementary-sections`, `analytics-charts`, `lib/analytics/visual-polish` (+ their vitest files incl. analytics-live-wire). Kept `analytics-data-context`, `api-client`, `envelope-mapper`, `fallback-envelope`, `main-kpis`, `mock-data`: still used by `DemoShell` and the plan impact block.
- `next.config.ts` redirects `/analytics/:path+` to `/analytics` (permanent). No Phân tích footer link existed to remove.
- Tests: dropped the e2e "Analytics chart…" a11y test and two Python exit-gate asserts that pinned it; navigation test now uses `/analytics`. TikTok pixel spec untouched (targets `/`).
- Gates: lint, type-check, vitest 1593, Playwright 104, build:demo pass; pytest -k "demo or issue_397" passes except pre-existing `test_cross_tenant_probe` (SQLAlchemy URL parse, no DATABASE_URL).
- Debt: backend `GET /v1/demo/analytics` retire at merge (DEBT.md). Dead `.analytics-*` CSS left.

## 2026-10-09 — P10-A agent (Claude Opus) — card payload, reasons + cooldown, consent edits (AC-10.1)

- Branch fasttrack/p10a-card: 0b3a6381 (migration `079_decision_reasons` onto 078:
  `decision_reasons` RLS + juli_app SELECT/INSERT, tenant_direct; `inventory_items.seller_sku`;
  phone cleanup re-parented to 079 — pins, tests, runbook), c40052f2 (consent edits),
  9a370552 (reasons + cooldown), 4e2f496e (`recommendation.card`), cb1a3a47 (tests,
  surface inventory, test-quality reconcile), cfc95fd3 (MODULE.md drift allowlist).
- Endpoints: `POST /v1/demo/decisions/{id}/reject` and `POST /v1/demo/runs/{id}/decline`
  → 200 `{status, cooldown_until}`; revert now requires `{reason_code, note?}`; 422 on
  missing/unknown code or note > 300. Decline = the ordinary confirmation decline +
  resume(approved=False). All three dismiss the card. Confirmations accept
  `edited_values`; 422 `{code: rule_violation, message (VI), field}`.
- Cooldown: (product, lever) skipped 7 days (`decision_cooldown`); lifts early only when
  the weak stage's rate (CTR/CTOR/AOV the card was proposed on) moved > 20 % relative.
  A dismissed latest card is governed by this cooldown alone.
- Rules for edits: title 25–255, description non-empty ≤ 10,000 (TikTok edit-product
  spec, VN = "other regions"), protected terms present in the current field must stay.
- Gates: check.sh --since effa4d4a --skip-gitleaks on a throwaway PG16 (initdb, random
  port, deleted after): migrations PASS (head 079, up/down/up), isolation 12, ruff,
  pytest 168. tests/unit + harness (no DATABASE_URL): 6410 passed, 36 failed = 27
  agent_events_contract (no packages/contracts/node_modules in this worktree) + the 9
  known pre-existing. mypy juli_backend clean (550 files); import boundaries: no new
  violations (56 before/after).
- Next: P10-C must send a reason body to revert (it 422s without one); orchestrator
  re-chains 079/080 with P10-B. Debt in DEBT.md "P10-A".

## 2026-10-09 — P10-C agent (Claude Opus) — Quyết định to the approved artboards (AC-10.3)
- New: `lib/quyet-dinh/{p10-types,reasons,p10-format,card-model,consent-model,run-model,measure-model}.ts`; timeline rewritten per run kind (listing/photo/manual/revert, "Bỏ qua" after decline); clients for reject/decline/revert-with-reason/photo/instructions/applied/measurement; confirmation sends `edited_values`, keeps `rule_violation`'s field.
- UI: `recommendation-card` (Main ≥768, Mobile <768, executor chip + after-line for photo/Seller Center cards per Levers), `reason-dialog` (3 modes, one reason required, no "Để sau"), `run-panel` (Run/RunPhoto/RunManual/Revert incl. edit panel, upload, checklist, done/declined/conflict), flat queue, `do-luong-panel` (target + band block, Ngày 0/7/14 tabs by `measurement.stage`, Day7/Day14 step lists, ask/kept/reverted/final boxes). Styles in `app/quyet-dinh.css` (artboard hex as `--qd-*`). Be Vietnam Pro via next/font on Quyết định only (shell keeps Inter: switching app-wide changes Trang chủ/Phân tích metrics). P8 grouping header, Duyệt N thẻ and the rules strip kept ABOVE the cards; the card itself is the artboard's. Single Phê duyệt now shows the in-card notice (no confirm dialog, no navigation); batch still confirms + navigates.
- Guard tests updated on purpose: `quyet-dinh.test.tsx` (timeline copy "Đang chờ bạn"/"Bạn đã xác nhận", terminal "Đo sơ bộ dd/mm (ngày 7) · chốt dd/mm (ngày 14)", flat queue, done panel / dialog revert); `e2e/decisions/quyet-dinh.spec.ts` (executor chip text, consent button "Xác nhận thay đổi này", flat queue, axe excludes greyed steps).
- Fidelity: scratchpad `shots-p10c/` — `raw/*--artboard.png` rendered from the `.dc.html` with a stub `support.js`, `raw/*--app-<w>.png` from the stubbed app, composites `<Artboard>--<state>.png`. Remaining differences: (1) app chrome (rail, shop header) and app-content width (944 vs 976 at 1040); (2) Levers is a 4-column compact catalogue — the app shows the Main-size card, 2 per row, and juli cards carry no executor chip (Main/Mobile have none; kept them exact); (3) RunPhoto/RunManual have no queue column — the app keeps Run.dc's queue for every run; chevron only on title/description runs as drawn; (4) Measure shows the Day7/Day14 step lists inside the panel and Day14's verdict chip/box colours (Measure's d14 box is green, Day14's Gần đạt blue — Day14 followed); (5) the demo-only switches / "Mô phỏng" / "↺ Xem lại từ đầu" not shipped, so grey running bars are shorter; (6) figures computed from data, not the illustrative ones (e.g. AOV −5,0 % vs −4,8 %); (7) photo captions without size/background; (8) the revert conflict from a 409 shows under the run's done panel (the artboard draws it inside a revert run, which the app shows when the revert run itself fails).
- Gates: lint (0 errors, 7 pre-existing warnings), type-check, vitest 1650, Playwright 124 vs `next start`, `pnpm build:demo` green.
- Next: orchestrator integrates with P10-A/P10-B; re-shoot against the live backend; DEBT P10-C items.

## 2026-10-09 — P10-B agent (Claude Opus) — cover-image flow, promotion flow, measurement (AC-10.2)

- Branch `fasttrack/p10b-flows`, ae6a515a..HEAD. Migration `080_lever_flows`
  onto `078_rules_and_write_values` (P10-A's 079 is parallel — re-chain at
  integration; the deferred phone cleanup is re-parented onto 080 and its four
  pins moved). Tables `run_lever_flows`, `run_lever_photos`,
  `lever_calibrations`, `run_measurement_finals`, RLS + per-verb grants.
- Design: a `cover_image` / promotion card's run is a "lever flow" — the real
  `WorkflowRunner` with its own playbook and a deterministic planner (P8-C's
  revert pattern). Waiting for the seller is the existing `waiting_external`
  state (`external_wait_reason` = `photo` / `seller_action` = `awaiting`):
  the planner raises `AwaitSeller`, `LeverFlowRunner` (returned by the
  worker's `_construct_runner`, task shells unchanged) records what it computed
  and calls `enter_external_wait(narration=...)` → one `workflow.status`
  event. New `WorkflowRunner.resume_after_external_wait`; new Celery task
  `resume_lever_flow` (agent_runs queue). The reaper judges these waits by the
  flow's policy (photo 72 h → `timed_out`). No new SSE event type.
- Photo: reads (diagnoses, listing, current photo), keeps the current cover as
  "before" (TikTok CDN, allowlisted hosts), waits; `POST .../photo` checks
  (1:1, ≥ 800 px exact; plain background, product ≥ 70 % heuristic, marked
  `heuristic: true`) → 202/422 `{checks}`; resume stages the photo
  (`upload_product_image`, URI kept on the photo row via
  `ProductToolContext.on_image_staged`, never model-visible) → ordinary consent
  on `update_product_listing` → the cover replaced, gallery kept, before/after
  recorded so Hoàn tác restores. Photos served at
  `/v1/demo/photos/{shop}/{token}` (capability token; allowlisted route).
  Consent shows before/after via `GET /v1/demo/runs/{id}` → `photo`.
- Promotion: approve now allows the four Seller Center levers (never written,
  D13). Reads price + existing promotions (new read-only tool
  `find_product_promotions`), checks the rules (cost required — a run without
  one fails loudly; margin floor; per-SKU cap), narrates it, waits.
  `GET .../instructions` (4 VI steps per type, Seller Center link, summary);
  `POST .../applied` → verify read-only; not found → "Chưa tìm thấy trên
  TikTok", stays waiting, re-check every 30 min (≤ 4); found → completed,
  `measurement_start` = the promotion's start date. `/changes` and `/revert`:
  unavailable, `seller_center`.
- `GET .../measurement`: contract §6 shape; stage from the impact reader's
  readings (promotion runs: calendar — DEBT); bands only from the seller's
  rules (none → `[]`, `within_band: null`); day-14 labels per the contract;
  calibration 0.5 start, stored per shop × lever, not moved by
  `chua_ket_luan`; verdict stored once.
- Contract interpretation (no shape change): the photo is staged on TikTok
  before the consent and the consent is on the listing write (ADR-069 order,
  DEBT); run detail / list responses gain only `awaiting` (+ detail extras:
  `awaiting_expires_at`, `lever`, `photo`, `promotion`); photo checks carry an
  extra `heuristic`/`detail` per item; measurement row `key` for GMV is
  `gmv_per_day`.
- Gates: new tests 63 passed (unit) + 2 (PG16 two-tenant). check.sh `--since
  effa4d4a --skip-gitleaks` on a fresh PG16: migrations PASS (080 head,
  up/down/up), isolation 12, ruff PASS, pytest 400 passed / 1 failed —
  `test_reaper_two_tenant.py::test_each_run_is_reaped_by_its_own_workflows_policy_as_juli_app`,
  which fails identically on an untouched `git archive effa4d4a` (pre-existing,
  not P10-B). Unit + harness without DATABASE_URL: remaining failures are the
  known ones (agent_workflow_task_wiring ×7 URL parse, cross_tenant_probe,
  destructive_migration_isolation) plus 27 `test_agent_events_contract` tests
  that need `node_modules` (`typescript`) in this worktree. mypy clean on the
  touched modules; import boundaries 56 (unchanged).
- Guard baselines regenerated (module drift allowlist, surface inventory,
  ownership registry, runs-list fields, shared-tool marker, test-quality
  456 + corpus re-derived — the corpus figures will need `python -m
  eval.quality_detectors reconcile --write` again after P10-A/C merge).
- Next: integration re-chains 079/080; P10-C reads `awaiting`, `photo.*_url`,
  `/instructions`, `/applied`, `/measurement`. See DEBT "P10-B".

## 2026-10-09 — P10 integration agent (Claude Opus) — UI ↔ backend wired; merged-head verification

- Commits: 90aec127 (drift allowlist re-sorted — merge interleaved P10-A/B
  entries, test_module_md_sync_parser failed), 8ba4e9ff (runs list + detail
  `decision_id`; decline at a photo / Seller Center wait ends the run
  `cancelled_by_seller`), 9849f24a (demo wiring), f54ada3b (tests incl.
  Python↔TS P10 contract), 0aaba190 (contract §7 accepted deviations),
  ee38e801 (racy vitest heading).
- Mismatches fixed: photo consent showed placeholders (consent payload is
  `attach_staged_image`; URLs now from run detail `photo.*_url`, stored checks
  reload); photo timeline counted the pre-consent staging upload as the write;
  promotion timeline slots mis-mapped P10-B's tools (`find_product_promotions`
  read/verify, rules = narrated text); "Không áp dụng" at the seller step 409'd
  (backend only declined consents) — backend now ends the wait; decline 404
  fallback to the consent decline removed (English codes → VI sentence); cards
  joined by `decision_id`; null `within_band` (no bands) read as out of band;
  nullable card KPI/title/gmv_method and measurement values. Reason codes,
  `edited_values`, 422 `rule_violation`, multipart `file`, status codes matched.
- Verification vs effa4d4a: check.sh --since effa4d4a on a fresh PG16 (initdb,
  random port, deleted after): migrations PASS (head 080), isolation 12,
  gitleaks PASS, ruff PASS (98 files), pytest 513 passed / 1 failed =
  known test_reaper_two_tenant. Unit+harness: 6590 passed / 10 failed vs base
  6483 / 9 — the known 9 plus test_credentials_in_url_guard, which only failed
  while check.sh ran concurrently and passes alone. task_wiring 29/29 with the
  sqlite URL. mypy (backend config) clean, 561 files; ruff clean; guards
  (route-auth, import boundaries, threat-model/surface inventory, module drift,
  test-quality, ownership) green.
- Demo: lint 0 errors (7 pre-existing warnings), type-check clean, vitest
  1654 (2 failed under load, both pass alone; one hardened), Playwright 124
  passed / 140 skipped vs `next start`, build:demo OK with dummy Supabase env.
- Next: owner deploy; re-shoot fidelity against a live backend (DEBT).

## 2026-10-09 — P11 agent (Claude Opus) — signed-out Quyết định on the P10 design; sign-in survives new tabs

- Branch `fasttrack/p11-sample-mode` from 96322798 (worktree `/Users/macos/juli-ft-p11-sample`).
- Signed out, `/decisions` now renders `SampleQuyetDinh`: the P10 screens
  (`QuyetDinhView`, split out of `signed-in-quyet-dinh.tsx`) over
  `createSampleQdClients()` — an in-memory store seeded with contract-shaped
  fixtures (`lib/quyet-dinh/sample-data.ts`: SM-012 Son môi số 12 CTOR 5,4 → 5,9 %,
  +2,1 tr ₫/tháng (juli); SR-007 ảnh bìa (juli_with_photo); KD-030 giảm giá
  (seller_center); MN-015 mô tả; TN-021 applied with a day-7 measured run). Approve /
  reject / consent (with edits) / photo / "Tôi đã áp dụng" / Hoàn tác change local
  state only and play the next contract events (`validateAgentEvent`) on a 700 ms
  timer. A "Dữ liệu mẫu · … shop minh họa" notice sits under the header, like Home and
  Phân tích. "Làm mới Demo" remounts the store (`resetEpoch` in demo-state).
- No network on that branch: `QdClients` contract, `QdApiError` and pure helpers moved
  to `lib/quyet-dinh/client-types.ts`; `DemoDecisionApproveError` to
  `lib/decision-approve-error.ts` (both re-exported from the old modules); the SSE
  hook is injected (`clients.useRunEvents`). `components/quyet-dinh/sample-quyet-dinh.tsx`
  is a new entry of `replay-module-graph.test.ts`, which now also forbids the
  quyet-dinh / decisions / confirmation / stream clients and `signed-in-quyet-dinh`.
- `RecommendationsView` is no longer rendered by `/decisions` but is kept: its unit
  tests and the fixture review route / replay run (`/decisions/recommendations/*`,
  `/decisions/in-progress/*`) still use the same fixtures. `verify-replay-scenario-in-build`
  unchanged and passing (build OK). The e2e journeys that clicked the old list cards
  now open those routes directly.
- Auth: `supabase-auth.ts` / `shop-session.ts` store in localStorage through
  `lib/persistent-storage.ts` (try/catch on every access, falls back to
  sessionStorage when localStorage is blocked, one-time migration from
  sessionStorage, sign-out clears both).
- Tests: `sample-quyet-dinh.test.tsx` (7, no fetch), storage tests (migration,
  clear-both, blocked storage), `e2e/decisions/quyet-dinh-sample.spec.ts` (P10 card,
  approve→consent→done, reject, photo, Seller Center, Đo lường, zero `/v1` requests;
  a second tab stays signed in). Updated: manual-refresh, responsive-parity,
  decisions-journey, accessibility, locale-and-assistance (`?load=error` state is
  gone — the bundled sample cannot fail), static-asset-render, replay-run-journey,
  quyet-dinh.spec (anonymous), email-sign-in (localStorage). Fixed a time bomb in
  `quyet-dinh-p10.test.tsx` (consent `expires_at` 2026-10-09T07:00Z had passed → the 2
  "consent with an edit" tests failed at HEAD).
- Verification (Node 20; Node 26's built-in localStorage breaks jsdom storage, 243
  unrelated failures at HEAD): lint 0 errors (7 pre-existing warnings), type-check
  clean, vitest 1665 / 1665, Playwright 132 passed / 140 skipped (port 3317, built
  artifact), build:demo OK, pytest exit-gate / P10 wiring / workspace guards 43 passed.


## 2026-10-10 — P12 agent (Claude Opus) — Phân tích redesign (ADR-109 Amendment 2)

Branch `fasttrack/p12-phan-tich` from d65eb320; worktree `/Users/macos/juli-ft-p12-phan-tich`.

- Backend (3fb2dab9, additive, contract `contracts/p12-phan-tich.md`, no migration):
  report `daily_gmv`, `seller_skus`, `promo_products` (`promotions.promo_products`),
  `Band.product_count`; ranking rows `seller_sku` (products), `product_ids` (LIVE /
  video, `rankings.tagged_products`). Per-cell ₫/day impact and the weakest metric
  were already in the report (`factors[].contribution`); the row → card join uses
  the existing `diagnosis.tiktok_product_id` and stage.
- UI: `lib/phan-tich/{model,rows,cards,extras,format,sample-data}.ts`,
  `components/phan-tich/{phan-tich-view,stream-card,extras,sample-phan-tich,signed-in-phan-tich}.tsx`,
  `app/phan-tich.css` (`.pa-*` on the `--qd-*` tokens). Removed: StreamFunnel,
  RankingTable, DetailPanel (Ví dụ), HeroList, `components/shop-analysis/*`,
  `lib/phan-tich/notes.ts`. Quyết định: `the=` / `nhom=` focus (3 s outline) and
  "Xem phân tích ›" on every diagnosed card.
- Deviations from the artboards (all data-driven or honesty):
  1. Sample numbers: the cells' ₫/day impacts and last values are the artboards',
     prior values are derived with ADR-108's log-share split so Δ % agrees with
     ₫/day — CTOR shows ▼ 6,9 % (artboard 15,2 %), Hiển thị ▲ 19,4 %, GMV ▲ 7,5 %;
     h1 "Thẻ sản phẩm: CTOR giảm 7 %". Video/LIVE Hiển thị/ngày 5.630 / 1.410
     (artboard 41.200 / 6.300 cannot give 1,9 / 0,8 tr ₫ with those rates).
     "Còn lại" sums are reconciled so Tổng = the cell (artboard rows did not add up).
  2. Row ↔ card links follow the real sample cards (product × metric): TN-021 AOV
     ("Mua nhiều giảm nhiều"), KC-004 CTOR ("Phí vận chuyển") and SM-012 CTR
     ("Tiêu đề") read "Chưa có đề xuất" — those cards do not exist in the
     Quyết định sample; TN-021 CTOR (applied card) links to it.
  3. Row facts: see DEBT (AOV facts, Kênh khác only for heroes, no "Lý do" on
     Kéo lên rows, video Nguồn / LIVE duration); a no-card down row shows a generic
     "Gợi ý" ("Theo dõi thêm" when Tham khảo).
  4. Khuyến mãi: "Giảm thật trung bình" sub reads "So với giá đang bán trước flash
     sale" (what true depth measures); a shallow depth reads "(quá nông)" in red
     instead of "(giá đã tăng trước)"; Voucher sub "N voucher đang chạy · đơn đạt
     ngưỡng"; all promo products are listed (sample: 5 rows, not 3); KD-030 is a
     product discount, not "Voucher 20k" (vouchers are shop-level).
  5. Lịch sale: 8 flash days are drawn pink (the artboard's stat says 8/60 but
     draws one); tiles' "gấp N lần" / "+N %" are computed against the median
     normal day; "Sắp tới" omits "chưa đăng ký".
  6. LinkA's dashed pink frame marks "what option A adds" — the app draws the
     caption as a white strip with the 1px pink hairline.
  7. A "Dữ liệu mẫu · … shop minh họa" notice sits under the header when signed
     out (P11 precedent); the footer "Số liệu là ví dụ minh hoạ." shows only then.
  8. "Xem N đề xuất ›" scrolls to / outlines the group rather than filtering.
  9. Mobile Khuyến mãi / Lịch sale item texts are the desktop tiles' texts.
  10. `--qd-faint` #6b6b76 (AA) for "Chưa có đề xuất" and the footer, as P10.
- Verification (Node 20): lint 0 errors (7 pre-existing warnings), type-check
  clean, vitest 1673/1673 (in a full parallel run 5 unrelated tests time out
  intermittently; they pass in isolation), Playwright 134 passed / 140 skipped
  (port 3318), build:demo OK, shop-diagnosis pytest 120 passed, `check.sh` OK
  (migrations at 080 unchanged, isolation 12, ruff, pytest 32, gitleaks).

### 2026-10-10 — P12 follow-up: reason note → completion message (owner edit a0382006)

- Dialogs: the "Lý do giúp Juli…" hint is gone from all three; Từ chối / Không thực
  hiện legend "Vì sao? (chọn một)"; Không thực hiện body "Khi đồng ý, gợi ý sẽ không
  quay lại", submit "Đồng ý" (Hoàn tác keeps "(chọn một · bắt buộc)", as its artboard).
- Completion (`ReasonDone`, green box + white "Lý do bạn chọn" box with the picked
  reason's label and its `learn` sentence — the artboards' `reasonLearn`, keyed by
  `reason_code` in `lib/quyet-dinh/reasons.ts`): "Hoàn thành · đã từ chối thẻ" on the
  card, "Hoàn thành · không thực hiện thay đổi" in the run panel, "Hoàn tác hoàn
  thành · đã khôi phục nội dung cũ" on the finished revert; then the artboards' note
  and outcome lines. Signed-in and sample doors share it.
- The reason is known only in the visit it was given (the frontend keeps the code;
  no read endpoint returns it): after a reload a rejected card / declined run /
  finished revert falls back to the previous text without the reason box.
- Verification: lint 0 errors, type-check clean, vitest 1675/1675, Playwright 136 passed.

### 2026-10-10 — P13: signed in without a shop sees the sample; one sample shop

- Owner decisions 2026-10-10. Branch `fasttrack/p13-no-shop-sample` from 4ebea7a8.
- `no-shop` (session, no acting shop): Trang chủ / Phân tích / Quyết định render
  the signed-out sample under `NoShopSampleStrip` ("Bạn đang xem dữ liệu mẫu ·
  Kết nối TikTok Shop ›" → `/auth/connect-shop`); no `/v1` request; sample
  actions stay in memory. Signed in with a shop unchanged.
- Phân tích header bug: `.pa-page > .page-header` made the shared header a
  column but kept its `align-items: flex-end`, pushing kicker + h1 right in the
  non-report states → `align-items: flex-start`.
- Home's sample (and the shell header's anonymous envelope) now come from
  `lib/phan-tich/sample-data.ts`. The sample report gained Liên kết (affiliate,
  greyed on Home, not a Phân tích stream) and a shop-wide `total` = the
  additive streams summed (it was Thẻ sản phẩm's comparison); Video / LIVE are
  no longer flagged `orders_estimated` (only Tab cửa hàng is, as on the wire).
  Phân tích's figures are unchanged. Home: GMV 30 ngày 214,9 tr (+3,1 %), Đơn
  1.314 (trước 1.250), CTOR Thẻ sản phẩm 5,14 % = Phân tích's cell. Name kept:
  "Cửa hàng Mẫu Hoa Mai" (already the P11 / P12 samples' name).
- DEBT: reason-box-after-reload accepted by the owner, won't fix.
- Verification (Node 20): lint 0 errors (7 pre-existing warnings), type-check
  clean, vitest 1687/1687, Playwright 147 passed / 140 skipped (port 3319; new
  `e2e/analytics/no-shop-sample.spec.ts` 10/10 across desktop + mobile-web),
  build:demo OK (Playwright webServer build).

### 2026-10-10 — P14-C/F: cost data (read-only) and rule fields for what TikTok does not give us

- Branch `fasttrack/p14-data` from a1e6767e. Commits e16ee0c9 (P14-C), 89aaf11e (P14-F), then docs.
- Schemas from the local corpus (`partner_documents/api-reference/orders/get-price-detail-202407.md`,
  `finance/get-transactions-by-order-202501.md`; their examples are truncated) completed from the
  bundled OAS (`tts-openapi-guide` references). Price-detail line items have a line-item id but no
  SKU id, so the step maps them with the existing order-detail read (ids only; the payload's buyer
  e-mail / address are never kept). The `voucher_deduction_*` fields are documented as a voucher
  *type* with an amount-looking example: stored, marked UNVERIFIED, excluded from the funded totals.
- Migration `081_order_cost_data` onto `080_lever_flows`; the deferred phone cleanup re-parented
  onto 081 (pins in five tests and the deploy runbook moved with it).
- Where the step lives: first written as `workers/services/polling/order_costs.py`; the
  import-boundary check forbids a NEW `workers → integrations` edge, so the fetch loop is
  `services/order_costs/sync.py` and `run_shop_cycle` calls it. It takes rate-limit tokens directly
  (10 / 60 s, the poll steps' window) without waiting, instead of `analytics_range.acquire_or_wait`.
- P14-F needs no migration: new `shop_rules` keys. The list was checked against the OAS (no cost
  field in the Product API; campaigns only as `campaign_inventory` after approval; analytics splits
  GMV_MAX / NON_GMV_MAX GMV but has no spend or target; finance has programme fees only per settled
  order; LIVE analytics is past sessions). `min_margin_pct` relabelled "Biên lợi nhuận tối thiểu
  khi giảm giá". The signed-out sample shows the new group read-only (`offApiReadOnly`); the
  existing groups keep their in-memory sample editing.
- Verification: ruff + format clean, mypy `backend/src/juli_backend` clean (569 files), import
  boundaries PASS; new pytest: `test_order_costs.py` 36, `test_shop_rules_off_api.py` 40,
  `TestOrderCostsInTheCycle` 1, `test_order_costs_two_tenant.py` 1; 156 related unit files: 1916
  passed, 9 failed = 7 `test_agent_workflow_task_wiring.py` (fail identically at the base checkout,
  local DATABASE_URL parsing) + 2 fixed in this branch (facade export list, import boundary);
  `fasttrack/check.sh --since a1e6767e` on fresh PG16: migrations PASS (at 081), isolation 12
  passed, gitleaks PASS, ruff PASS (30 files), pytest 298 passed; RLS / grant / two-tenant suites
  on PG16: 60 passed, 1 skipped, 1 xfailed. Demo (Node 20): type-check clean, lint 0 errors (7
  pre-existing warnings), vitest 1702/1702 (a first full run had 3 timing failures in other files
  that passed on re-run), Playwright `e2e/decisions/` 32 passed / 140 skipped (port 3321).

## 2026-10-10 — P14 agent (Claude Opus) — card limits, learning from history, "Hành động"

- Branch `fasttrack/p14-cards` from a1e6767e. No migration.
- **P14-A (D24.17).** `DecisionEmissionConfig` is now `daily_new_cap` 5 /
  `weekly_new_cap` 25 / `max_open` 30 / `validity_days` 7 / `min_stay_days` 3 /
  `cooldown_days` 7 / `first_day_mix` (juli 3, seller_center 1, content 1), each
  with a `CDP_DECISION_EMISSION_*` override; the old `max_active` / weekly novelty /
  per-workflow cap are gone. `apply_emission_budget`: expires surfaced cards at 7 days
  (`status = "expired"`, `metadata_json.expired_at`), keeps the others with their
  original `surfaced_at` (no more re-stamping), surfaces drafts up to
  min(daily, weekly, open) room in shop time (UTC+7); first connect uses the executor
  mix. Counts read the novelty ledger, now one row per surfacing. Campaign-plan and
  content hooks: `CAMPAIGN_PLAN_WORKFLOW_KEYS`, `CONTENT_WORKFLOW_KEYS` /
  payload `executor_type`. Optimize Product: top 30; open card with an unchanged
  diagnosis re-scored in place; expired card → same lever returns 7 days after expiry
  (`expired_cooldown`), another lever at once; `withdraw_unranked_cards` keeps a
  surfaced card ≥ 3 days unless `invalid_reason` (title edited outside Juli, not on
  sale, stock 0, metric at target). `persist` (legacy workflows) gives expired cards
  the same 7-day return. Card block: `expired` status, validity 7 days from
  surfacing. Rejected / declined / reverted: existing P10-A cooldown already matches
  (7 days, every time, no escalation) — kept its > 20 % early lift.
- **P14-B (D24.6).** `LeverHistory`: factor = coefficient ÷ 0.5 clamped [0.25, 2];
  `decision_reasons.reason_penalty` = max(0.4, 1 − 0.2 × Σ fade over 60 days),
  circumstantial codes excluded; `measurement.shop_calibrations`. Ranking sorts on
  recoverable × factor × penalty; shown GMV and measurement unchanged. Payload
  `adjusted_by_history` + `diagnosis.history_adjustment`; API card block and UI line
  "Thứ tự đề xuất đã điều chỉnh theo kết quả trước của shop." Formula in DECISIONS
  D24 notes.
- **P14-D.** "Đòn bẩy được tự thực thi" → "Hành động được tự thực thi" (rules label;
  allow-listed in `destination-naming.test.ts`), canvas title "(7 hành động)",
  ADR-109 UI copy. Internal `shop_report.py` HTML left (DEBT).
- Tests: new `tests/unit/test_p14_card_limits.py` (18: 14-day simulation, mix,
  shop day, campaign hook, seller rule, expiry return ×2, no escalation, 3-day stay,
  invalid ×3, in-place re-score, calibration/penalty math and ordering); existing
  emission / optimize / API / CDP tests updated to the new limits.
- Verification: action_cards / optimize_product / lever_flows / decision_reasons /
  demo_decisions suites 455 passed, 20 skipped; wider `tests/unit` + integration
  subset importing these modules 2541 passed, 11 failed — all pre-existing or
  environmental (9 fail identically on a1e6767e: agent workflow wiring, cross-tenant
  probe, CI-yaml guard; credentials-in-URL guard only times out at 30 s, passes
  without the timeout). mypy clean (45 files), ruff clean. Demo (Node 20): lint 0
  errors (7 pre-existing warnings), type-check clean, vitest 1690/1690.
  `fasttrack/check.sh --since a1e6767e` (docker PG16): migrations PASS (head 080),
  isolation 12 passed, gitleaks PASS, ruff PASS, pytest 139 passed.

### 2026-10-10 — P14-E: "Juli soạn · bạn làm" content cards (Video / LIVE)

- Branch `fasttrack/p14-content` from 7590ba9d (D24.19). Contract
  `fasttrack/contracts/p14-content-cards.md`; artboards ContentCards / ContentRun
  copied to `docs/product/design/quyet-dinh-flows/` (b668231c). UI built by a fork
  in parallel against the contract (1534786b); backend 2f7692b3 + docs commit.
- **Candidates (rules, nightly)**: `services/content_cards/candidates.py` over the
  stored `shop_metric_rankings` — `seller_video × ctr` rows below the stream prior with
  ≥ 1 000 impressions per product (impressions = clicks ÷ CTR) → video card;
  `seller_live × ctor` rows below the LIVE prior with ≥ 100 clicks → LIVE card.
  Expected GMV = −Σ the rows' `gmv_per_day` (already D22's formula), shared 1/N across
  a row's products, × 30. Template copy only.
- **Emission** (`emission.py`), called from `action_cards.persist.emit_scoring_cards`
  at a marked P14-E hook (the only edit in the sibling's file): writes ActionCards with
  `workflow_key` `content_video` / `content_live` (`CONTENT_WORKFLOW_KEYS`) and payload
  `card_executor: "juli_drafts"`, `content{…}` (no `diagnosis`). Re-scores open cards in
  place; 7-day validity from `surfaced_at`, expiry → withdrawn + `expired_at` → back
  after 7 days; reason cooldown via `decision_reasons` (card_basis learns content
  cards); surfaced cards withdrawn early only at target / product not sellable;
  ≤ 5 new content cards per ISO week; approved-in-measurement blocks 21 days.
  Never touches `surfaced_at` (surfacing is the budget's).
- **Run**: playbooks `content_video` / `content_live` (`agent/playbooks/content.py`,
  registered; prompt pins `content_*/v1.md`); deterministic `ContentPlanner` +
  `ContentRunner` wired in `_construct_runner`. Reads via a new `content` tool domain
  (`get_content_performance`, `find_new_content`, read-only analytics) + existing
  `get_product_information` / `get_seo_keywords` / `find_product_promotions`; seller
  rules narrated (`assistant.text`). ONE `gpt-5.4-nano` call per version through the
  OpenAI adapter with the new `response_format` → `text.format` json_schema (strict);
  usage rides the planner's turn, so `workflow_runs.input/output_tokens` / `cost_usd`
  count it. Guardrails: banned claim patterns + Juli/founder phrases + seller banned
  words, protected-term respelling, prices / stock / discount vs data and cap, length,
  hook ≤ 12 words, product on screen ≤ 3 s, basket order. Prompts adapt the
  content-engine voice rules, hook-pattern table and HOOK/SETUP/VALUE/CTA frame to the
  seller (tone, banned words, the shop's best videos / LIVEs as examples).
- **Waits**: `content_choice` (3 days) and `content_publish` (7 days) join
  `lever_flows.AWAITING_VALUES` (runs list, decline route, reaper policies). Seller
  routes `POST /v1/demo/runs/{id}/content/use|redraft|published` (202 / 409 / 422) →
  existing `resume_lever_flow`. Run detail `content` block (steps, script blocks,
  wait, measuring line). State in `workflow_runs.state["content_run"]` (RunState keeps
  unknown keys) — no migration.
- **Measurement / poll**: hourly beat `content-runs-poll` (minute 41) per pollable
  shop: auto-detects the new video / LIVE (then resumes the run) and stores the video
  day-7 / day-14 readings (new vs old videos' CTR) or the next-3-sessions LIVE CTOR;
  `GET /measurement` turns them into the P10 §6 body, final stored once with
  calibration per `video_script` / `live_script`.
- **Existing tests touched**: tool description snapshot + dictionary entries for the
  two tools, production registry set, dispatcher-domain preservation scoped to the
  pre-#1704 domains, beat schedule (8 entries), surface inventory regenerated.
- Verification: ruff + format clean, mypy 581 files clean; backend unit suite 6473
  passed, 9 failed — all pre-existing locally (also fail at 7590ba9d: cross-tenant
  probe, destructive-migration CI flag, 7 `_construct_runner` wiring tests needing a
  DB URL); new tests `test_p14_content_rules.py` 24, `test_p14_content_flow.py` 12.
  Demo: lint 0 errors (7 pre-existing warnings), type-check clean, vitest 1700/1700,
  Playwright `e2e/decisions` 32 passed / 140 skipped on port 3322 (content spec on
  desktop + mobile, zero `/v1` requests).

### 2026-10-10 — P14 integration: p14-data + p14-cards + p14-content

- Branch `fasttrack/p14-integration` from ddef3245 (worktree `juli-ft-p14-int`). Merged `--no-ff`:
  `fasttrack/p14-data` (clean), `fasttrack/p14-cards` (6e808245; conflicts only in PROGRESS / LOG /
  ACCEPTANCE / DEBT / DECISIONS → union; P14-A/B/D implementation notes kept under D24.17, before
  D24.18–20 and D25), `fasttrack/p14-content` (5095558d; docs union + three code conflicts kept
  both sides: `DemoDecisionCard` has `adjusted_by_history` and `content`, `p10-types.ts` both fields
  + `CardContentPayload`, `destination-naming.test.ts` both allow-list entries). P14 sections in
  PROGRESS / ACCEPTANCE now sit under one "## P14 — recommendation pipeline (D24)".
- Integration fixes (separate commits): aace1159 the emission budget's `CONTENT_WORKFLOW_KEYS` is
  P14-E's (`content_video` / `content_live`) and payload `card_executor: "juli_drafts"` claims the
  day-1 content slot, so content cards take the daily / weekly / open limits, the 7-day validity
  and the 3-day stay like any card (P14-E's ≤ 5/week stays a creation sub-limit); P14-E's
  `expired_recently` honours a card the budget expired (`expired`), so its 7-day return holds —
  new `tests/unit/test_p14_integration_content_budget.py` (3). 438e3f6e import boundary (p14-cards
  deep-imported `core.config.decision_emission`; failed on the branch alone too). ff1db5df
  zero-assertion reconciliation 456 → 459 (three P14-C/F `pytest.raises`-only tests; failed on
  `fasttrack/p14-data` alone too).
- No changes needed: migration head `081_order_cost_data`, deferred phone cleanup parented on 081
  (pins already moved by p14-data); beat schedule (only p14-content adds a beat); surface inventory
  regenerated — identical. Seller tone / banned words: p14-data added no rule key, P14-E's reader
  of `content_tone`/`tone`, `banned_terms`/`banned_words` left as is (DEBT).
- Verification: ruff clean; `ruff format --check` over the tree lists the same 37 files as
  ddef3245; mypy 589 files clean. `tests/unit` 6664 passed, 242 skipped, 2 xfailed, 9 failed —
  the same 9 fail at ddef3245 (7 `test_agent_workflow_task_wiring`, `test_cross_tenant_probe`,
  `test_destructive_migration_isolation` CI flag). `tests/integration` without a DB: 50 passed,
  244 skipped, 2 failed + 4 errors (same at ddef3245); on a fresh PG16: 276 passed, 21 skipped, 3
  failed — the same 3 at ddef3245 (recorded-replay registry, sanitizer registry, public UPDATE
  grants; the last now also lists P14-C's three tables, DEBT). `fasttrack/check.sh --since
  ddef3245` (docker PG16): migrations PASS at 081, isolation 12 passed, gitleaks PASS, ruff PASS (89
  files), pytest 35 files 624 passed. Demo (Node 20): lint 0 errors (7 pre-existing warnings),
  type-check clean, vitest 130 files 1714 passed, Playwright 154 passed / 140 skipped (port 3323),
  `pnpm build:demo --force` OK.


### 2026-10-10 — P14 integration: D24.21 owner choices

- Merged `fasttrack/optimize-product` (`--no-ff`, docs 3836bf2a: DECISIONS D24.21 + D25 8–10; no conflict).
- (1)/(3) Strict 7-day return: `decision_reasons.clearly_changed` / `CLEAR_CHANGE_RELATIVE` removed;
  Optimize Product's `_cooled_down` is the reason row alone; content emission already keyed on the
  cooldown only. Legacy workflows (`persist.emit_scoring_cards`): a dismissed newest row is handled
  like an expired one — inside 7 days suppressed (`basis_unchanged` / `active_card_exists` as
  before), after 7 days a new chained revision even with an unchanged basis. **ADR-087 d.6
  ("clock never triggers") is replaced for dismissed cards** (DEBT: ADR text not amended). UI copy
  drops "trừ khi số liệu đổi rõ".
- (2) `max_open_cards` 5–30, default 30; stored values < 5 clamp to 5 on read (no data migration).
- (4) Fixed daily slots: `DecisionEmissionConfig.first_day_mix` → `daily_slots`
  (env `CDP_DECISION_EMISSION_DAILY_SLOTS`); `apply_emission_budget` picks per slot every day
  (`daily_slot_pick`), today's earlier surfacings (ledger rows → cards) use up their slot, no
  backfill, the first-day-only mix and `_shop_ever_surfaced` are gone. Legacy cards (no lever) take
  Juli slots after the ADR-106 Juli cards. `plan_shop_cards` keeps the top 30 per executor type
  (`keep_top_per_type`). Content candidates rank by GMV × lever weight (`lever_history`).
- (5) `content_tone` / `banned_terms` rule keys (validation, routes, accessors), editor group
  "Nội dung video / LIVE", sample values, chips; `content_cards.driver.load_rules` reads exactly
  them; `agent_runs.confirmations` refuses an `update_product_listing` approve whose title /
  description contains a banned term (`EditRejected` → 422 `rule_violation`), also checked on the
  seller's edit (`validate_listing_edits(banned_terms=…)`).
- Also: content ≤ 5/week in the shop week (`emission._week_start` = shop Monday 00:00 +07);
  `081_order_cost_data` grants no UPDATE on `order_price_details` / `order_finance_transactions`
  (delete + insert only; 081 is not deployed, edited in place, no new migration), `order_cost_fetches`
  UPDATE registered in `GRANT_REQUIRED`; PROGRESS AC id 14E.6 → 14E.5.
- Tests updated for the slots (14-day simulation now 48 Juli / 16 SC / 16 content, slots 3/1/1 per
  day; first-day backfill tests replaced by empty-slot / every-day / same-day tests; legacy-card
  budgets 5 → 3), new `tests/unit/test_d24_21_owner_choices.py` (7).
- Verification: ruff clean; `ruff format --check` lists none of the changed files (whole-tree
  list unchanged: 37 under tests/ plus agent-runtime/infra/.claude files); mypy 589 files clean.
  `tests/unit` (run in 8 chunks): 6681 passed, 242 skipped, 2 xfailed, 9 failed — the same 9
  pre-existing (7 `test_agent_workflow_task_wiring`, `test_cross_tenant_probe`,
  `test_destructive_migration_isolation` CI flag). `tests/integration` on a fresh PG16: 276 passed,
  21 skipped, 3 failed — the same 3 (recorded-replay registry, sanitizer registry, public UPDATE
  grants — now only the 7 older tables). `fasttrack/check.sh --since 3836bf2a` (docker PG16):
  migrations PASS at 081, isolation 12 passed, gitleaks PASS, ruff PASS (98 files), pytest 42 files
  693 passed. Demo (Node 20): lint 0 errors (7 pre-existing warnings), type-check clean, vitest 130
  files 1715 passed, Playwright 154 passed / 140 skipped (port 3324, example Supabase env),
  `pnpm build:demo --force` OK.

## 2026-10-10 — P15 content analysis of seller uploads (agent: Claude Opus, `fasttrack/p15-content-analysis` from `fasttrack/p14-integration` 2c35c1e4)

- Built D24.20 per `contracts/p15-content-analysis.md`: migration `082_content_analysis`
  (`content_analyses`, tenant_direct, RLS, juli_app S/I/U; deferred phone cleanup re-parented, still
  last — the orchestrator re-chains against P16's migration at merge); resumable chunked upload
  (slot → `PUT …/file?offset=N` + `X-Upload-Token`, 32 MB chunks for Cloudflare, first-box sniff);
  pipeline on the new Celery queue `content_analysis` (ffprobe/ffmpeg with `-f mov
  -protocol_whitelist file`; `whisper-1` ASR in Vietnamese with a product glossary; LIVE windows
  from ASR mentions; cuts ported from the content engine's `reference_analyze.py`; keyframes / 2 s;
  `gpt-5.4-nano` vision for on-screen text + product on screen; ONE structured-output scoring call
  over derived signals; numbers from signals only); per-shop monthly OpenAI cap (default $5,
  `shop_rules.openai_monthly_cap_usd` override for P16); file deleted after analysis, hourly sweep at
  24 h. Content runs' drafter gets the best / weakest analysis (prompt `p15-content-prompt-v2`). UI
  "Phân tích video" block in the content run and in Phân tích › Nội dung row detail; sample shows a
  canned analysis with no network. No new Python dependency (numpy/PIL/httpx only).
- Guards that caught things on the way: import boundaries (api/workers now import the package
  root), credentials-in-URL (the slot token moved from the query string to a header), ratchet (no
  new noqa), test-quality reconciliation (re-derived with `reconcile --write`), surface inventory
  and beat-set pins (regenerated / extended).
- Measured on the generated fixtures (Apple M2, mocked OpenAI): 6 s and 30 s 320×240 videos → 0.32
  s / 0.40 s of ffmpeg work end to end (probe 0.04–0.07, audio 0.07–0.16, cuts 0.07–0.08,
  keyframes 0.06–0.07 s). OpenAI cost (estimate from the price tables, not billed): 30 s video ≈
  ASR $0.003 + vision ≈ $0.001 + scoring ≈ $0.0003 → ≈ $0.004–0.005; a 2 h LIVE scanned 60 min +
  3 windows ≈ $0.36–0.40 ASR + ≈ $0.01 vision.
- Verification: ruff / format clean on changed files; mypy clean (content_analysis, content_cards,
  routes, task, llm). `tests/unit` in four chunks: all green except the pre-existing failures
  (`test_cross_tenant_probe`, `test_destructive_migration_isolation` CI flag, 7
  `test_agent_workflow_task_wiring`). `tests/unit/test_p15_content_analysis.py` 31 passed on PG16
  (incl. RLS as juli_app). `tests/integration` on fresh PG16: 276 passed, 21 skipped, 3 failed — the
  same 3 as at ddef3245 / P14 integration (`content_analyses` is justified in the UPDATE registry).
  `fasttrack/check.sh --since 2c35c1e4` (docker PG16): migrations PASS at 082, isolation 12 passed,
  gitleaks PASS, ruff PASS (38 files), pytest 10 files 204 passed. Demo (Node 20): lint 0 errors (7
  pre-existing warnings), type-check clean, vitest 131 files 1719 passed + 2 failed in
  `rules-editor-off-api.test.tsx` under the full parallel run only (13/13 alone, before and after
  P15 — flake, DEBT), Playwright `e2e/analytics` 32 passed, `e2e/decisions` 36 passed / 140 skipped,
  P15 specs re-run after the token change 18 passed (port 3325, example Supabase env),
  `pnpm build:demo` OK.
- Note: a `git stash`/`pop` probe during the vitest flake check popped an unrelated old stash
  (stashes are shared across worktrees); the pop conflicted and was reset — that stash entry is
  intact (`stash@{0}`), nothing of it was committed.
- Next: owner review of the UI deviation (no artboard) and of vision-instead-of-OCR; install ffmpeg
  on the VPS; P16 to own the cap override; orchestrator to re-chain 082 against P16's migration.

### 2026-10-10 — P16 Juli Ops (D25) + P9-B handover — P16 agent (Opus)

- Branch `fasttrack/p16-ops` from `fasttrack/p14-integration` (2c35c1e4), worktree `juli-ft-p16`.
  Migration **`083_ops_console`** onto `081_order_cost_data` (orchestrator re-chains after P15's
  082); deferred phone cleanup re-parented onto 083 (pins moved in 5 tests).
- Backend: role `juli_ops` + 5 `ops_*` tables (RLS, `juli_ops` only, `ops_only` class),
  `users.staff_access_consent_at`, DEFINER `ops_current_shop_overrides` / `ops_list_shops` /
  `ops_transfer_shop`; `/v1/ops/*` (Access JWT verified + staff role, fail closed; PII-masking
  route class; every write audited); overrides read by emission budget / content emission /
  drafting / agent runs; OpenAI cap = shared `shop_rules` row `openai_monthly_cap_usd` ($5
  default, P15 coordination) gating drafting and Optimize Product model calls; simulation from
  new additive report keys `daily_streams` / `daily_products`; scenarios; invites + seller accept
  (P9-B); Huỷ kết nối; Ops Quy tắc; scopes persisted on refresh + permission status.
- Owner changes mid-task, all applied: D25.11 window / trend, D25.13 disconnect, D25.14 Quy
  tắc, D25.15 permissions, D25.3 amended (view-as always read-only — act mode, flag and
  consent removed; non-GET under `/view/` → 403), cap storage shared with P15. D24.21 (2)/(5)
  implemented on the way (open cards 5–30 default 30; Giọng văn, Từ không được dùng rule keys +
  seller editor fields).
- Frontend (apps/demo): `/ops` route group (Tổng quan, Cài đặt shop + Quy tắc, Xem như shop,
  Mô phỏng, Nhân viên, Nhật ký, own Google sign-in landing), `middleware.ts` host split + noindex,
  `/nhan-shop` (token in the link fragment, POSTed), staff-access notice on connect, reconnect
  strip. Landing privacy sentence VN + EN.
- Infra (files only): `infra/nginx/ops.app-juli.com.conf`, `INSTALL_OPS_VHOST=1` in
  `provision-nginx.sh`, env example, `docs/runbooks/ops-console-runbook.md`.
- Guards touched: quality reconciliation re-derived (459 → 473, 6236 functions / 615 modules),
  surface inventory regenerated (threat-model test now detects auth transitively), no new
  suppressions, creds-in-URL clean.
- Verification: ruff clean; mypy (backend config) 610 files clean. `tests/unit` 6777 passed,
  11 failed — the 9 that fail at the P14 base (7 `test_agent_workflow_task_wiring` without a DB
  URL — all pass with one, `test_cross_tenant_probe`, `test_destructive_migration_isolation`),
  plus `test_action_card_revisions` (pinned `ops_disabled` afterwards) and one timing flake
  (`test_slow_backing_store_does_not_stall_the_event_loop`, passes alone). `tests/integration`
  on PG16: 288 passed, 4 failed — the 3 base failures (recorded-replay, sanitizer registry,
  public UPDATE grants) + `test_run_changes_two_tenant` (5–30 rule; fixed, passes).
  `fasttrack/check.sh --since 2c35c1e4` (docker PG16): migrations PASS at `083_ops_console`,
  isolation 12, gitleaks PASS (one test false positive allowlisted), ruff 70 files, pytest 41
  files 511 passed → **OK**. Demo (Node 20): lint 0 errors (7 pre-existing warnings), tsc clean,
  vitest 135 files 1733 passed, `pnpm build:demo` OK, Playwright `DEMO_E2E_PORT=3326`: ops 8,
  auth + analytics 36, decisions + exit-gate 118 passed / 140 skipped. Landing: lint, tsc,
  vitest 49, build OK.
- Next: owner — review OpsSimulate; apply `docs/runbooks/ops-console-runbook.md`; the
  orchestrator re-chains 083 after P15's 082 and confirms P15 reads the same cap row.
## 2026-10-10 — P17 onboarding speed (D26, D25.12, P14-C pacing)

Branch `fasttrack/p17-onboarding-speed` from 09960b20 (P17 agent, Opus; UI by a forked
agent). Contract `contracts/p17-onboarding-speed.md`. Not merged, not deployed.

- **Quick scan (D26)**: `juli_backend.shop_quick_scan` (queue `ingest_priority`, lock
  `quick_scan`) is enqueued by `bootstrap_shop` as it starts (marker `quick_scan_queued`),
  so it runs in another worker beside the fast phase. TikTok calls: A-34 202605 for the
  last 14 local days (`page_size` 100, ≤ 2 pages) + one `/product/202405/products/diagnoses`
  call for the top 10 by GMV (+ Get Product for a chosen product the catalog does not hold
  yet — placeholder `products` row at `update_time` 1970-01-01, overwritten by the first
  sync), all through the shared Redis window. Selection = ADR-106 decision 4 on the 14-day
  funnels (median trigger, TikTok codes as evidence, no discount cap), only cover image /
  title / description, D22 on the 14 days, 1–3 cards. Written through
  `emit_optimize_product_cards` + `apply_emission_budget` → the day-1 Juli slots.
  Upgrade: the full run feeds the quick cards' TikTok codes to `plan_shop_cards`
  (`tiktok_evidence`), re-scores a same-lever quick card in place (`surfaced_at` kept),
  supersedes one with another lever, withdraws one not proposed at once
  (`quick_scan_not_confirmed`).
- **Time to first card**: the scan's own work is ~1 s with fakes (selection 3 ms for 200
  products); in production it is 2–5 TikTok reads behind the shared window, so **≈ 15–60 s
  after connect** (Celery pick-up + reads + one DB transaction) when the A-34 window is free;
  if the fast phase has just spent it, the gate waits for the reset (≤ 60 s per window, cap
  180 s) → **≤ ~3–4 min worst case**. Not measured on a live shop (no connect performed);
  `shop_quick_scan_done.seconds_since_connect` and `shop_ingestion_state.quick_scan_done_at
  − connect_committed_at` measure it in production.
- **Onboarding status**: `GET /v1/shops/me/onboarding` (bearer + X-Shop-Id) → three steps,
  percent / ETA (typical 900 s, `ONBOARDING_FULL_DIAGNOSIS_TYPICAL_SECONDS`), `active`,
  label, poll interval (15 / 300 / null), `history_days_available` (contract §2, read by
  P16), `window_90d_available` at ≥ 180 days.
- **History (D25.12)**: API look-back checked in `partner_documents/api-reference/analytics/`:
  no maximum is documented for the shop analytics reads (A-34 202605, 202509 shop / product
  / SKU / video / LIVE); the only documented analytics limit is **180 days** (Get Video
  Performances 202403, "start_time must be within the last 180 days"); hourly shop data is
  30 days. `SHOP_HISTORY_MAX_LOOKBACK_DAYS` default 1095 → **180**; the existing out-of-range
  halving still stops at TikTok's real limit. Connect chain stops at 60 days
  (`SHOP_HISTORY_CONNECT_DAYS`); nightly beat `shop-history-extend` (19:43 UTC = 02:43 +07)
  → `shop_history_backfill(nightly=True)`: 2 × 15-day chunks once per local day
  (`history_extended_on`), per-shop `history` lock, resumable; 60 → 180 days in 4 nights.
- **429 (D25.12)**: `fetch.with_backoff` 2/4/8/16/32 s (cap 60, upper-half jitter, env) then
  `ThrottledError`; `video_windows` skips the video tables for the cycle on it (no
  `posted_in_window` fallback), counter `video_windows_throttled_skips`.
- **Cost reads**: orders of the last 30 days up to 60 per pass per cycle (waiting for the
  window ≤ 600 s), older at 10; 429 / permission still stop at once.
- **Migration** `084_onboarding_speed` → `081_order_cost_data` (5 nullable columns +
  check constraint on `shop_ingestion_state`); deferred phone cleanup re-parented onto 084;
  the five tests pinning the head / cleanup parent updated.
- **Demo** (fork): `lib/onboarding/*` client + `useOnboardingStatus`, `OnboardingStrip` /
  `ShopOnboardingStrip` on Trang chủ, Phân tích and Quyết định (signed in with a shop only;
  Quyết định re-reads its cards on each active poll), quick chip + "Độ tin cậy: Tham khảo".
- Guards: surface inventory regenerated (new route), beat-set test + `shop-history-extend`,
  `eval.quality_detectors reconcile --write` (corpus 6,199 / 609 modules; zero-assertion 49
  unchanged), workers import `services.onboarding` via its package root, MODULE.md entries.
- Verification: ruff + format clean on changed files; mypy clean on the changed modules.
  `tests/unit` in 4 chunks: a 1661 passed / 7 failed, b–c 693 / 1, d–r 2858 / 1, s–z 1505 /
  3 → the 3 fixed (surface inventory, beat set, quality corpus); remaining 9 = the known
  pre-existing (7 `test_agent_workflow_task_wiring` — 29/29 with a sqlite `DATABASE_URL` —,
  `test_cross_tenant_probe`, `test_destructive_migration_isolation`). `tests/harness`: 2
  failures in `test_module_md_sync_parser` also fail at 09960b20 (P14 drift; P17's own
  symbols documented). PG16 (initdb, port 55417): `test_migrations` + contract + order-costs /
  shop-diagnosis / shop-ingestion / onboarding two-tenant: 64 passed, 1 failed = the known
  `test_no_public_table_holds_update_beyond_its_call_site` (7 pre-existing tables).
  `fasttrack/check.sh --since 09960b20` (fresh PG16): migrations PASS at 084, isolation
  12 passed, gitleaks PASS, ruff PASS (37 files), pytest 17 files 313 passed / 1 skipped. Demo (Node 20): lint 0
  errors (7 pre-existing warnings), type-check clean, vitest 132 files 1771 passed,
  Playwright (port 3327, example Supabase env) 160 passed / 140 skipped incl. the new
  onboarding spec, `pnpm build:demo --force` OK.

## 2026-10-14 — orchestrator (Claude Opus) — P32 opened (D42)

- Shopee rejected the ISV profile ("unable to identify the actual service via Test URL").
  Grill with the owner → D42; ACs 32.1–32.11; P32-A (reviewer access, Opus) and P32-B
  (Shopee copy, Sonnet) dispatched in parallel from this commit; P32-C after them.
- Noted: the decisions were first recorded on `main` as ADR-109 (#2134) and GitHub issues
  #2135–#2139 before D2/D4 were noticed; `main`'s ADR-109 collides with this branch's ADR-109
  and is renumbered at merge-back.
- Live demo check: Google + email-OTP sign-in work after hydration (the SSR HTML shows the
  "chưa sẵn sàng" fallback); a new account lands on the P13 sample — the reviewer never saw a
  connected shop.

## 2026-10-14 — P32-A agent (Claude Opus) + orchestrator — reviewer access (AC-32.1–32.8)

- Branch `fasttrack/p32a-reviewer-access` (5e3c1410..ce38297b + this docs commit): contract,
  migration `090_reviewer_accounts`, reviewer claim + gate bound in `get_current_user`
  (allowlist by matched endpoint), Fujiwa pin via alias id + view-as read scope, response mask,
  `POST /v1/reviewer/decisions/{id}/simulate`, ops audit, provisioning CLI, demo password mode on
  `/auth/email`, banner, simulated Duyệt → Thực thi, e2e.
- The agent was cut off twice by network errors (ENOTFOUND); the orchestrator finished: reviewer
  unit tests 27 passed; `fasttrack/check.sh --since 0e80c18b` (docker PG16): migrations PASS at
  090, isolation 12 passed, gitleaks PASS, ruff PASS (44 files), pytest 543 passed / 1 failed —
  the failure is pre-existing (DEBT, fails on the base too).
- Owner steps: `REVIEWER_SHOP_ID` (+ optional `REVIEWER_MASK_TERMS`) in the API env; after deploy
  run the provisioning CLI on the VPS (contract §8).

## 2026-10-14 — P32-B agent (Claude Sonnet) — Shopee status copy (AC-32.9)

- Landing hero: new line "TikTok Shop · Shopee (đang tích hợp qua Shopee Open Platform)" under
  the unchanged TikTok badge. `/privacy`: removed the "in development" sentence (VN + EN), added
  section 4A (VN + EN: data, purpose, retention mirror, Shopee Open Platform Data Protection
  Policy, write-back only after approval, effective when a Shopee shop is connected); dated
  14/10/2026. `/terms`: Shopee paragraph in section 4 (VN + English note), "TikTok Shop hoặc
  Shopee" in the lawful-use clause. Tests extended; privacy wording avoids a second "never
  buyer data" match so `privacy-staff-access` still pins exactly the D25.6 sentence.
- Gates (Node 20.20.2): landing lint, type-check, vitest 63/63, `next build` OK. Under Node 26
  the localStorage tests fail (pre-existing, environment only).
- Branch not merged, not deployed. (Orchestrator correction: `fasttrack-deploy.yml` does build and
  ship the landing artifact since 2026-10-08 — DEBT repaid; the README sentence saying landing SHAs
  are refused is stale and is fixed in the P32 integration commit.)

## 2026-10-15 — orchestrator (Claude Opus) — P32 integrated

- Merged `fasttrack/p32a-reviewer-access` (d28161bd) and `fasttrack/p32b-shopee-copy` (3a582b9f)
  into `fasttrack/optimize-product` (owner approved in the P33 grill); fasttrack doc conflicts
  resolved by keeping both sides. Repaid the p10a time bomb (card surfaced now in the test);
  README landing-lane sentence corrected (landing ships since 2026-10-08).
- `fasttrack/check.sh --since 0e80c18b` (docker PG16): 5/5 PASS twice (migrations at 090,
  isolation 12, gitleaks, ruff 44 files, pytest 544); one earlier run hit a flaky isolation seed
  (DEBT). Not deployed — owner tags.

## 2026-10-15 — P33-A agent (Claude Opus) — technical SEO foundation (AC-33.1–33.4)

- Branch `fasttrack/p33a-seo-foundation` (875fb83b..HEAD, pushed; not merged, not deployed).
- **Helpers** `apps/landing/src/lib/seo/` (API + how-to in its README): route registry split by
  owner (`routes/core.ts`, `product.ts`, `capabilities.ts` (P33-C), `blog.ts` (P33-D)) feeding
  `sitemap.ts` with lastmod; `buildMetadata(path, opts?)` (absolute title, description, absolute
  self canonical, OG vi_VN 1200×630 + Twitter); `<JsonLd data>` + builders (Organization with
  legal name / taxID / PostalAddress / ContactPoint lienhe@app-juli.com, WebSite — both on every
  page from the layout — BreadcrumbList, SoftwareApplication + Offer 500000 VND, FAQPage,
  Article, VideoObject). No sameAs, no hreflang. `src/lib/media.ts` (`LOGO_WORDMARK`,
  `HERO_VIDEO`, `HERO_VIDEO_SCHEMA`), `<Picture>` (AVIF/WebP + width/height), `SiteLogo`,
  `scripts/media.py` (optimize / brand: OG card, favicon + icons, logo WebP, poster AVIF/WebP).
  Home canonical is the bare origin (Next strips the slash).
- **Pages**: home, about, contact, privacy, terms migrated; `/product` content moved verbatim to
  `/san-pham` (Breadcrumb + SoftwareApplication + FAQPage for its rendered FAQ); `/product` 301
  (`RENAMED_PATHS`, `statusCode: 301`). Nav, about, 404 link `/san-pham`.
- **Demo/ops noindex**: X-Robots-Tag from next.config headers() + middleware on every host,
  layout robots meta, `app/robots.ts` Allow: / (no sitemap). `@juli/tiktok-events/pixel-id`
  subpath added so the landing consent banner no longer bundles the pixel snippet.
- **PageSpeed**: mockup contrast fixed with landing-local `color-mix` tokens (theme `tokens.css`
  is byte-pinned by #1314, so not touched); logo 50 KB PNG → 6 KB WebP with width/height;
  poster → WebP; favicon/icon/apple-icon; pixel tracking via next/dynamic after consent;
  explicit modern browserslist; cache headers for `/media` (immutable), `/og`, `/videos`.
  `experimental.inlineCss` measured and dropped (TBT ×3). Lighthouse A/B numbers in AC-33.4:
  A11y and BP 1.00, page 282 → 229 KB, Perf/LCP target not demonstrated on this loaded host.
- **Check for B/C/D**: `pnpm --filter @juli/landing build && pnpm --filter @juli/landing check:seo`
  (one h1, no skipped level, title/description/canonical = registry and unique, OG/Twitter,
  JSON-LD parses, Org/WebSite everywhere, Breadcrumb on inner pages, FAQ visible, no sameAs,
  no hreflang, not noindex).
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 9 files 75 passed,
  `next build` OK, `check:seo` 7/7; tiktok-events vitest 89 passed; demo lint 0 errors (7
  pre-existing warnings), type-check clean, vitest 149 files 1903 passed / 5 failed in one run
  under load avg ~25 (timeouts + `no-shop-sample` race; passes 3/3 alone and on the base; DEBT),
  `pnpm build:demo --force` OK (example Supabase env); nginx/landing/demo packaging pytest 160
  passed; `fasttrack/check.sh --since e1c6d68f` (docker PG16): 5/5 PASS.
- **Owner steps** (after deploy): (1) Cloudflare → demo.app-juli.com: keep the managed
  robots.txt / AI Crawl Control from adding any `Disallow` for search crawlers (today it only
  prepends content-signal comments; origin now serves `User-Agent: * / Allow: /`); check
  `curl -sI https://demo.app-juli.com/ | grep -i x-robots` shows `noindex, nofollow` (Cloudflare
  must not strip it). (2) Cloudflare Browser Cache TTL "Respect existing headers" for
  app-juli.com (today `/videos/*.jpg` shows `max-age=14400`, a CF override of Next's
  `max-age=0`; with the new longer origin TTLs CF keeps the origin value). (3) Search Console:
  submit `https://app-juli.com/sitemap.xml`; for demo.app-juli.com use Removals only if old URLs
  linger after the noindex is crawled. (4) No nginx change needed.
- Next: P33-B / C / D branch from this branch's head.

## 2026-10-15 — P33-B agent (Claude Opus) — homepage + `/san-pham` overview (AC-33.5, AC-33.6)

- Branch `fasttrack/p33b-homepage` from P33-A f55809fd (2f16f2eb..HEAD, pushed; not merged, not
  deployed).
- **Homepage** (`app/page.tsx`, `components/home/`): H1 "Juli AI — trợ lý AI vận hành cho nhà bán
  TikTok Shop: phân tích, đề xuất, thực thi sau khi bạn duyệt, đo GMV"; marketplace strip (TikTok
  Shop live via Open API · Shopee "đang tích hợp qua Shopee Open Platform", never live), problem,
  Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường, three capability blocks linking
  `/san-pham/{phan-tich-shop,de-xuat-va-thuc-thi,do-luong-gmv}`, data safety, audiences,
  transparency (measurement method, sample-data label, company + MST + address), "từ 500K/tháng
  · dùng thử 3 tháng", 7-question FAQ + FAQPage, final CTA. CTAs: "Dùng thử 3 tháng" (LOGIN_URL)
  + "Xem demo" (DEMO_URL); all five still tracked by the pixel.
- **Hero video**: new poster `public/media/home-demo-poster-v1-{640,1280}.{avif,webp}` (video frame
  t=19 s, GMV formula, no figure — the old card said "+1–3% GMV"); `<video preload="none">`
  mounted only on click; VideoObject.
- **Claims**: "+1–3% GMV mỗi tháng" and "~1,7 giờ/ngày" had no source beyond CONTEXT.md's
  2026-10-09 hero framing → dropped (D43.3). Also dropped: "ROI cao", the comparison table, and
  copy promising things Juli does not do (tạo đơn nhập, đồng bộ tồn kho, tạo mã giảm giá on
  `/san-pham`, alerts via Zalo). Scope now per D13 / D24.5. The video still shows figures →
  captioned "minh hoạ" + DEBT.
- **`/san-pham`** rewritten (~1,680 words): what Juli is, the loop, capabilities, does / does
  not do, integrations, data control, audiences, pricing (`#bang-gia`), FAQ, CTA; breadcrumb
  (visible + JSON-LD), SoftwareApplication + Offer, FAQPage. Registry titles/descriptions for `/`
  and `/san-pham` updated.
- **Header/footer**: header Sản phẩm · Blog · Giới thiệu · Liên hệ + CSS-only mobile menu;
  footer columns Sản phẩm (overview, 3 capability pages, Kết nối TikTok Shop) / Công ty / Pháp lý,
  © company name, no social links. `SITE_PAGES` gained `/blog`; `PRODUCT_PAGES`,
  `FOOTER_PRODUCT_LINKS` in `lib/site.ts`.
- Deleted the old hero/steps/comparison/features/mockup/trial components and their CSS
  (`lp-hero*`, `lp-steps*`, `lp-comparison*`, `lp-features*`, `lp-mockup*`, `lp-curiosity*`);
  new classes `lp-home-*` in `globals.css` (replaces that block). `lp-page-*` untouched for C/D.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 9 files 79 passed, `next
  build` OK, `check:seo` 7/7; no horizontal overflow at 390 px (Playwright) on `/`, `/san-pham`,
  `/about`; `fasttrack/check.sh --since f55809fd`: 5/5 PASS. Lighthouse not run (loaded host).
- **Integration note**: the new links 404 until P33-C/D merge; merge B with C and D.
- **Owner questions**: re-cut or replace the hero video (figures + a discount run Juli does not
  do); confirm "Dùng thử 3 tháng" is free (landing said so; /terms §5 is silent); add an in-app
  disconnect.

## 2026-10-15 — P33-B agent (Claude Opus) — owner's D43 additions (trial, disconnect, video, poster)

- Recorded **D43 additions** in DECISIONS (video stays; free 3-month trial via `/dang-ky` (P33-F);
  no disconnect button, the team disconnects on request; keep old poster files).
- **Landing** (2df45c3e, 7c7a6b22): `SIGNUP_URL` = `/dang-ky` (env `NEXT_PUBLIC_SIGNUP_URL`),
  `TRIAL_CTA_LABEL` "Dùng thử miễn phí 3 tháng" on home hero / pricing / final and `/san-pham`
  hero / pricing card / final; `TikTokTracking` now also fires StartDemo for clicks to
  `SIGNUP_URL` (content_name = testid). `/terms` §5: "Tài khoản mới được dùng thử miễn phí 3
  tháng kể từ ngày đăng ký, không cần thẻ thanh toán. Sau thời gian dùng thử, phí dịch vụ Juli là
  500.000đ/tháng." (dated 15/10/2026; **owner's legal review**). Homepage / FAQ / `/san-pham`
  disconnect copy: contact Juli by email or `/contact`, the Juli team disconnects. `/san-pham`
  FAQ +2 (trial, disconnect).
- **Demo** (2e37f3c0): `DemoLanding` at `/?dang-ky=dung-thu` forces the doors and the sign-in
  door reads "Đăng ký dùng thử miễn phí 3 tháng" (eyebrow "Tài khoản mới"; body + existing-account
  line); buttons and the P32-A partner door unchanged. "Không cần thẻ thanh toán" verified: no
  payment integration (Ops "Thanh toán · tự động, sắp có" is disabled; terms granted by contract).
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 81/81, build OK, `check:seo`
  7/7; demo lint 0 errors (7 pre-existing warnings), type-check clean, vitest 1909/1912 in the full
  run at load avg ~35 (3 load flakes in `quyet-dinh-p10`, `ops-pages`; 70/70 in isolation with
  `demo-landing`), `pnpm build:demo --force` OK (example Supabase env); `fasttrack/check.sh
  --since f55809fd` 5/5 PASS.
- `/dang-ky` 404s until P33-F integrates (DEBT); `check:seo` does not check links, so no allow-list.
## 2026-10-15 — P33-C capability pages (agent: Claude Opus, branch `fasttrack/p33c-capabilities`)
- **Pages** (Vietnamese, D43.1/D43.4): `/san-pham/phan-tich-shop`, `/san-pham/de-xuat-va-thuc-thi`,
  `/san-pham/do-luong-gmv` (parent `/san-pham`, SoftwareApplication + Offer) and
  `/ket-noi/tiktok-shop` (parent home, no SoftwareApplication). Shared frame
  `src/components/product/capability-page.tsx` (+ CSS module, tokens only): breadcrumb, one H1,
  ToC, H2 sections each with one `<Picture>` + "Dữ liệu mẫu" caption, FAQ rendered = FAQPage,
  related links, "Dùng thử 3 tháng" (LOGIN_URL) / "Xem demo" (DEMO_URL). Routes in
  `routes/capabilities.ts`.
- **Screenshots**: 24 crops (`public/media/cap-*-v1-{640,1280}.{avif,webp}`,
  `components/product/screens.ts`) from the demo's signed-out sample "Cửa hàng Mẫu Hoa Mai"
  (Phân tích, Quyết định: Đề xuất / Đang thực hiện / Đo lường, reject / undo dialogs, confirm step)
  plus connect-shop and the P17 onboarding strip rendered with mocked API responses. The sales-demo
  stills were not used (marketing frames with promised uplift numbers).
- **Accuracy**: facts from D13/D14/D22/D24/D26/D29–D32/D39/D41, ADR-106/108, `/privacy`, and code
  (scope list, revert rules, card limits in `decision_emission.py`, onboarding labels). Left out
  on purpose: product attributes as an executed field, exact OAuth scope names, a seller
  disconnect button, daily email / Zalo reports, cross-shop learned effects or any result number,
  Liên kết in Phân tích, time estimates beyond what the app shows.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 10 files 91 passed (new
  `capability-pages.test.tsx` 16), build OK, `check:seo` 11/11; `check.sh --since f55809fd` 5/5.
- Next: P33 integration merges B/C/D; owner confirms the real-shop write wording (DEBT).
## 2026-10-15 — P33-D agent (Claude Opus) — blog + three pillar drafts (AC-33.8)
- Branch `fasttrack/p33d-blog` from P33-A f55809fd. Commits 7ef53a7a (infra), dad5460c (drafts),
  efb19ca7 (READMEs) + this docs commit.
- **Blog architecture**: posts are typed TS — metadata in `apps/landing/src/content/blog/posts.ts`
  (one `status` field per post), bodies in `content/blog/bodies/<slug>.ts` as a small Markdown
  subset parsed and rendered on the server (`src/components/blog/markdown.tsx`; no MDX, no new
  dependency, no client JS for content). `/blog` index + `/blog/[slug]` (SSG,
  `dynamicParams = false`), blog CSS in `src/app/blog/blog.css` (kept out of `globals.css` to
  avoid conflicts with P33-B/C). Routes derived from `posts.ts` in `src/lib/seo/routes/blog.ts`.
- **Draft mechanism** (touches P33-A helpers, small): `SiteRoute.noindex`; `metadataForRoute`
  adds robots `noindex, follow`; `sitemapEntries()` drops noindex routes; `check:seo` asserts a
  noindex route IS noindex and that no indexable page links one. A published post renders links
  to drafts as plain text and hides them from "Bài viết liên quan". Drafts are listed on `/blog`
  only under `next dev`.
- **Drafts** (Vietnamese, H1 → H2 → H3, sources section, FAQ): metrics 4,882 words, product card
  4,579, tools 3,700 (space-separated tokens). TikTok facts from Academy VN pages cited by title;
  method from ADR-106/108; worked examples labelled "số giả định"; no customer data (Fujiwa
  numbers deliberately not used). Tool facts from vendors' own sites, checked 2026-10-15 via a
  Sonnet research sub-agent (WebFetch summaries); no third-party prices quoted.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 10 files 98 passed (blog 23),
  `next build` OK, `check:seo` 11/11 (also 11/11 with one post temporarily flipped to published:
  it entered the sitemap, its links to drafts were unlinked); `fasttrack/check.sh --since
  f55809fd`: 5/5 PASS.
- **Owner**: approve each post by flipping `status` to `"published"` (README in
  `apps/landing/src/content/blog/`); re-check the tool facts flagged in DEBT before publishing
  post 3. After integration, P33-B's header/footer link `/blog`; P33-C's four pages make the
  posts' product links resolve (the blog test allow-lists them until then).
## 2026-10-15 — orchestrator (Claude Opus) — P33-E Search Console scripts
- Read the Search Console API guides (overview, limits, prereqs, authorizing, performance, batch,
  search analytics, all-your-data) and reference (searchanalytics.query, sitemaps, sites,
  urlInspection.index.inspect + UrlInspectionResult, errors). Key facts: OAuth 2.0 only;
  Removals is UI-only (no API), Indexing API is JobPosting / livestream only; URL Inspection
  2,000 / day / site and reports BLOCKED_BY_META_TAG vs BLOCKED_BY_HTTP_HEADER; Search Analytics
  final after 2-3 days, 25k rows / page, page×query grouping is the most expensive.
- `scripts/seo/` written (see AC-33.10). Pitfall found: `RobotFileParser.read()` sends
  `Python-urllib`, Cloudflare answers 403 and the parser turns that into "disallow all" — the
  live check fetches robots.txt with its own UA.
- Baseline (production, before P33-A): 10 / 14 URLs failing.
- 2026-10-15 follow-up: the OAuth token now also asks `openid email` so `gsc_sitemaps --sites`
  names the Google account (an account without the property silently got `{}`). Owner moved the
  property to the company account: `thien.phung@app-juli.com` is siteOwner of
  `sc-domain:app-juli.com` (a Domain property also covers demo. / ops.; no separate property).
- First real run: sitemap not submitted under this account; URL Inspection — `/`, `/privacy`,
  `/terms` indexed; `/product`, `/about`, `/contact` unknown to Google; **demo `/`, `/decisions`,
  `/analytics` indexed** (crawled 2026-08-20..10-02); ops unknown (Access). Search Analytics: ~1
  click / 5 impressions a week, data through 2026-10-10.
## 2026-10-15 — P33-F agent (Claude Opus) — free-trial sign-up (AC-33.11)
- **Branch** `fasttrack/p33f-trial-signup`, cut from P33-A `f55809fd`; siblings B/C/D untouched.
- **Landing**: `/dang-ky` (registered, indexable; one H1, value list, form) and
  `/dang-ky/cam-on` (registered `noindex: true`, out of the sitemap). To register a noindex route
  the branch takes **P33-D's noindex plumbing verbatim** (`git checkout fasttrack/p33d-blog --` on
  types.ts, metadata.ts, lib/seo/sitemap.ts, app/sitemap.ts, lib/seo/index.ts, seo.test.tsx,
  built-site.check.ts — byte-identical, so the integration merge of those files is clean). New
  registry file `routes/signup.ts`. Form: `components/signup/*` (CSS module, no globals.css edit:
  P33-B rewrote it). No-JS: `POST /dang-ky/gui` → 303 to the thank-you page or
  `/dang-ky#loi-…` (`:target` notice). JS: fetch + inline Vietnamese errors (validate.ts twins the
  API rules). The relay forwards `X-Real-IP` as `X-Juli-Client-Ip` with `TRIAL_SIGNUP_RELAY_KEY`,
  refuses foreign `Origin`. CompleteRegistration fires on the thank-you page only when the form set
  a sessionStorage flag AND analytics consent is granted (lazy import of the pixel package).
  `/privacy` VN §2 + EN §2 gain a "Đăng ký dùng thử" paragraph (what, why, 12-month retention,
  deletion on request in 30 days); effective date 15/10/2026.
- **Backend**: migration `091_trial_signups` (ops_only; deferred 074 re-parented, pins moved),
  `services/trial_signups.py`, public `POST /v1/trial-signups` (threat-model allowlist + surface
  inventory regenerated), `GET/PATCH /v1/ops/trial-signups` (Vận hành+, audited, NOT masked —
  route class keeps the 503 on a missing juli_ops grant). Rate limits are counted from the table.
- **Ops UI** (`apps/demo`): `/ops/dang-ky-dung-thu`, nav item after Thời hạn (ops-d27 nav
  assertion updated), audit sentence "Đăng ký dùng thử: Mới → Đã liên hệ".
- **Docs**: D43 additions P33-F (PROPOSED: Vận hành-only + unmasked, 12-month retention, relay
  key), contract p16-ops §10, runbook env rows, api/frontend env templates, DEBT section.
- **Gates (Node 20.20.2)**: landing lint 0, type-check clean, vitest 10 files 107 passed, build OK
  (`/dang-ky` static, `/dang-ky/gui` dynamic), `check:seo` 9/9 (cam-on asserted noindex); demo lint
  0 errors (7 pre-existing warnings), type-check clean, vitest 150 files 1914 passed after the nav
  assertion update, build OK (example Supabase env); backend `test_trial_signups.py` 38 passed,
  PG16 `test_trial_signups_two_tenant.py` + `test_ops_console_db.py` 31 passed;
  `fasttrack/check.sh --since f55809fd` 5/5 PASS. Smoke: `next start` + fake API — no-JS post 303
  → `/dang-ky/cam-on`, invalid → `/dang-ky#loi-du-lieu`, relay key + client IP forwarded.
- **Full backend unit suite** (SQLite, no DB): after fixing the invariants this branch tripped
  (route-auth allowlist, users.phone reviewed list, reviewer sweep `{signup_id}`, import
  boundaries, ratchet suppression/exports) the remaining failures are all on the base f55809fd
  too: `test_agent_workflow_task_wiring` (7), `test_cross_tenant_probe` (1, needs a DB URL),
  `test_destructive_migration_isolation` (fasttrack-deploy.yml), `test_import_boundaries` (6
  grandfathered ops.py deep imports), `test_ratchets` (branch-wide baseline drift),
  `test_test_quality` (corpus count drift). Not touched here.
- **Owner**: set `TRIAL_SIGNUP_NOTIFY_TO`, `TRIAL_SIGNUP_IP_SALT`, `TRIAL_SIGNUP_RELAY_KEY` in
  `juli/api/production`, the same relay key in `juli/frontend/production`, and `OPS_SMTP_*` if not
  yet set; confirm the PROPOSED items. No nginx change.
- Next: integration with P33-B/C/D (expect doc-file conflicts in ACCEPTANCE/PROGRESS/LOG/DEBT/
  DECISIONS only), then deploy.

## 2026-10-15 — orchestrator (Claude Opus) — P33 integrated (A–F)

- Merged `fasttrack/p33a-seo-foundation`, `p33b-homepage`, `p33c-capabilities`, `p33d-blog`,
  `p33e-gsc-monitor`, `p33f-trial-signup` into `fasttrack/optimize-product` (owner: "deploy website
  ngay"); fasttrack doc conflicts resolved by union (ticked rows win). Integration fixes 8e0f66ee:
  blog test no longer allow-lists the P33-C pages; `/ket-noi/tiktok-shop` disconnect copy = contact
  Juli (owner decision 3).
- Gates (Node 20.20.2): landing lint / type-check / vitest 152 / build / check:seo PASS; demo lint /
  type-check / build PASS, vitest 1917 / 1918 (one load-sensitive test, passes alone — DEBT);
  `check.sh --since 7486edf1` 5/5 (migrations at `091_trial_signups`, pytest 398).
- Owner decision 2026-10-15: deploy now; real-shop writes (P5) must ship before real customers are
  onboarded (the trial form routes every new seller through the team).

## 2026-10-15 — P32-D agent (Claude Opus) — reviewer on the sample shop (D42 amendment)

- Owner decision 2026-10-15 amends D42.3: the Shopee rejection was about the product page and the
  trial sign-up, not the data, so the partner reviewer sees the sample shop ("Cửa hàng Mẫu Hoa Mai")
  instead of Fujiwa; `REVIEWER_SHOP_ID` stays unset in production. Branch
  `fasttrack/p32d-reviewer-sample` from f3c84b55.
- Backend: the gate no longer answers 503 when the pin is unset. `ReviewerContext.shop_id` /
  `alias_id` may be None: `/v1/reviewer/me` → `shop: null`, `/v1/shops` → `[]`,
  `enter_reviewer_shop` → 403 `shop` (every shop-scoped route, `simulate` included). Allowlist,
  write barrier, account-state checks (expired / revoked / unknown → 403) unchanged; refused-write
  audit rows carry `shop_id = NULL`. Pin set → unchanged behaviour, unchanged tests.
- Demo: `shop: null` → sign-in stores no active shop and `sample: true` in the reviewer record →
  P13's no-shop door on every page (no shop request), banner `reviewer.banner_sample` (dictionary),
  no-shop connect strip hidden as before. `SampleQuyetDinh` opens the reviewer's simulation dialog
  (split out of `ReviewerSimulation` as `simulation-dialog.tsx`, so the sample module graph stays
  request-free) over `lib/reviewer/sample-simulation.ts`, an in-memory port of the API simulation.
  A stored stale shop is cleared (and the page reloaded) if `/me` later says `shop: null`.
- Tests: backend `test_no_pin_reviewer_gets_sample_mode`, `test_no_pin_still_refuses_expired_and_revoked`
  (replace the old 503 test); the every-route no-write sweep is parametrised over both modes.
  Demo `reviewer-sample-mode.test.tsx` (real `DemoShell` + `DecisionsPageClient`: banner, no strip,
  simulated execute, the only request is `GET /v1/reviewer/me`).
- Gates (Node 20.20.2): demo lint 0 errors (7 pre-existing warnings), type-check clean, vitest
  151 files / 1923 passed, build OK (example Supabase env); reviewer pytest 32 passed (PG
  integration included via check.sh); `check.sh --since f3c84b55` 5/5 PASS.
- Owner: nothing to set for the sample-shop reviewer (leave `REVIEWER_SHOP_ID` unset); still
  provision `shopee-review@app-juli.com` with the CLI after deploy (contract §8.3). DEBT: no
  Playwright e2e for sample mode.

## 2026-10-15 — P32-E agent (Claude Opus) — every feature simulated for the reviewer (D42 amendment 2)

- Owner decision 2026-10-15 (D42 amendment 2): Shopee wants "all features enabled for Shopee
  testing"; the sample-shop reviewer had only Duyệt. Branch `fasttrack/p32e-reviewer-all-features`
  from 9d6352b3 (deployed).
- Demo only, no backend change: `DemoShell` wraps only the pinned reviewer in the read-only
  provider. Sample mode runs every write on `lib/reviewer/sample-store.ts` (the P11 in-memory store,
  one per tab, shared by Quyết định and `/settings`): Từ chối, Duyệt → Thực thi → "Theo dõi lượt
  chạy (mô phỏng) ›" into the sample run (consent edits, photo, Seller Center, content drafts,
  Hoàn tác), Đo lường day-7 / day-14 "tua nhanh" (`simulateMeasurement`), Quy tắc (P14-F fields
  editable too), "Phân tích video" (file never read: canned P15 analysis). `SimulatedLabel`
  prints "Mô phỏng · không gửi tới TikTok" / "Mô phỏng · không lưu" for the sample reviewer only;
  the banner gets "Đặt lại dữ liệu mẫu". Connect / invites / ops stay hidden.
- Tests: `reviewer-all-features.test.tsx` (full session through the real shell — the only request
  is `GET /v1/reviewer/me`; labels absent for the signed-out sample; pinned reviewer unchanged);
  `reviewer-sample-mode.test.tsx` updated (Từ chối enabled).
- Gates (Node 20.20.2): `pnpm install --frozen-lockfile` OK; demo lint 0 errors (7 pre-existing
  warnings), type-check clean, vitest 152 files / 1926 passed (a later re-run: 1925 / 1926, the
  load-sensitive `ops-pages.test.tsx` timeout — passes 3 / 3 alone, DEBT); `build:demo --force` OK
  (example Supabase env); `check.sh --since 9d6352b3` 5/5 PASS. Landing untouched. Docs: DECISIONS D42 amendment
  2, contract header + §4 + §6, dictionary `reviewer.*`, MODULE.md, Services Information steps 6–9,
  ACCEPTANCE AC-32.12, PROGRESS P32-E, DEBT.
- Next: orchestrator merges, deploys, resubmits to Shopee with the updated Services Information.


## 2026-10-15 — P34-A agent (Claude Opus) — UI foundation for the public redesign (D44, AC-34.1)

- Branch `fasttrack/p34a-ui-foundation` from 64f7f913. Commits 3380f3cf … (see `git log 64f7f913..`).
- **Font**: Be Vietnam Pro 400/500/600/700 self-hosted with `next/font/local` (`apps/landing/src/app/fonts.ts`);
  one woff2 per weight (~30 KB) holding Google's Latin + Vietnamese unicode ranges, subset with
  fonttools from the upstream OFL TTFs (licence `src/app/fonts/OFL.txt`). No build-time fetch, so
  `build-release-artifact.sh` / `fasttrack-deploy.yml` need nothing new. `display: swap` +
  metric-matched Arial fallback (no CLS). `--juli-font-sans` is re-pointed to it in the landing, so
  the `@juli/ui` buttons and `html` use it too. The landing used to name Inter and never load it.
- **Tokens**: `apps/landing/src/styles/tokens.css` (`--lp-*`: colour incl. status pairs, dark band and
  blog category tints; responsive type scale D44.1; 4 px spacing + section rhythm; containers 1200/720;
  radii 10–24; frame/hero/float shadows). The only landing file allowed raw colours
  (`design-tokens.test.ts` allowlists it). Contrast measured: every text pair ≥ 4.5:1 (list in the
  file header); `--lp-pink` is accent-only (2.75:1). `packages/theme/tokens.css` untouched.
- **Components** `apps/landing/src/components/ui/` (barrel `index.ts`, styles `ui.css`, docs `README.md`
  with props, tokens and a recipe per mockup): SiteHeader (active state, `<details>` mobile menu,
  `signup` variant), SiteFooter, LinkButton/Button/TextLink, Section/Container/Eyebrow/Heading/
  SectionIntro/Card/CheckList, Shot/ShotFrame (chrome bar, backdrop, "Dữ liệu mẫu", mobile crop via
  `<picture media>` with its own width/height, top crop), FeatureRow, StatusPill, StepList
  (`LOOP_STEPS`), FunnelDiagram, FaqList (optional FAQPage JSON-LD), TocNav + `.ui-toc-layout`,
  Breadcrumb, Icon (12 line icons), BirdGlyph/BrandMark. `Picture` gained `mobileVariants`.
- **Assets** (`scripts/media.py glyph`, `mobile-crops`): bird glyph 64/96 AVIF+WebP; 18 mobile crops
  `cap-*-m-v1-*` (+ `*_MOBILE` in `components/product/screens.ts`), eyeballed at 390. Six shots with
  large text need none.
- **Migration**: every page now renders `SiteHeader`/`SiteFooter` (`/dang-ky` uses the signup
  header); old `landing-header.tsx`, `site-footer.tsx`, `site-logo.tsx`, `LOGO_WORDMARK` and the
  `lp-header*`/`lp-footer*`/`lp-logo` CSS removed (globals.css 1,077 → 844 lines). Header CTA changed
  per mockup: `header-demo-cta` → `header-login-link` (Demo) + `header-trial-cta` (/dang-ky); tests
  (cta, tracking: 7 tracked CTAs, sections, info, legal) updated. Page bodies untouched (B–E).
- **Gates** (Node 20.20.2): `pnpm install --frozen-lockfile` OK; landing lint 0 problems, type-check
  clean, vitest 13 files / 178 passed, `next build` OK (all pages static), `check:seo` 17/17;
  Playwright on the production build: `/`, `/san-pham`, `/dang-ky` at 1440 and 390, no horizontal
  overflow, computed font Be Vietnam Pro; header menu opened at 390; a throwaway preview page of every
  component at both widths (not committed). Screenshots: `fasttrack/design/p34/evidence/p34a/`.
  `check.sh --since 64f7f913` 5/5 PASS.
- For B–E: read `apps/landing/src/components/ui/README.md`. Next: B–E build pages on this branch's
  merge; orchestrator merges P34-A first.

## 2026-10-15 — P34-B agent (Claude Opus) — homepage to the D44 mockups (AC-34.2)

- Branch `fasttrack/p34b-home` from `fasttrack/p34a-ui-foundation` @ c95231e0 (see `git log c95231e0..`).
- **Built** (`app/page.tsx`, `components/home/{home-sections.tsx,home.module.css,hero-video.tsx,home-content.ts}`),
  section by section from `Main.dc.html` with the P34-A components: hero (badge eyebrow, H1, lead,
  `hero-trial-cta` → `SIGNUP_URL`, "Xem video 1 phút", note, `ShotFrame` pair `cap-dx-the` 7:5 +
  floating `cap-pt-pheu`, bird + dashed flight path) · marketplace strip (`StatusPill` live /
  integrating) · `StepList` loop · 3 `FeatureRow`s (cap-pt-luong + xep-hang stacked, cap-dx-the 3:2
  reversed, cap-dl-tang-them; mobile crops where they exist) · 4 data-safety `Card`s with `Icon` ·
  audiences · transparency card + company `dl` · dark pricing band (on-dark CTAs + 500.000đ card) ·
  FAQ split with `FaqList` (FAQPage JSON-LD only from the page) · header/footer as before.
  HomeMobile: hero shot on its backdrop with "Dữ liệu mẫu", no flourish/float; strip as a bordered
  card; stacked full-width CTAs; StepList rows.
- **Video** (D43.6 kept): "Xem video 1 phút" is a client `<button>` opening a modal `<dialog>`; the
  `<video preload="none" autoplay controls>` mounts on click and unmounts on close; the caption "Số
  liệu trong video là minh hoạ" sits under it. VideoObject schema unchanged.
- **Deviations from the mockup, on purpose**: (1) "Kết nối chính thức" card says sellers authorise on
  TikTok Shop's page, not "Partner Center" (that is the developer console; the old test forbids it).
  (2) Cap2 gets the D13/D24.5 bullets (Juli executes title/description/attributes; cover only from
  the seller's photo; price + promotions by the seller; video/LIVE scripted). (3) FAQ keeps the six
  sourced `HOME_FAQ` items + "Juli đo hiệu quả…" (7, not the mockup's 6 shortened questions).
  (4) Hero keeps the consent line (Điều khoản / Chính sách, `hero-consent-note`, TikTok review) and
  turns "Demo dùng dữ liệu mẫu" into a "Xem demo" link (`hero-demo-cta`). (5) Safety lead adds "not
  sold" + the privacy link (the dropped "Không bán dữ liệu" card). (6) Audiences keep the sourced
  longer bodies. (7) The old "GMV giảm, nhưng hụt ở đâu?" problem section and final CTA band are
  gone (not in the mockup; the dark band is the final CTA).
- **Tests changed intentionally**: `sections.test.tsx` (new H1 + H2 order, landmarks, StatusPill
  status, screenshots alt "(dữ liệu mẫu)" + sized + LCP priority, D13 strings, no `%`, company `dl`
  with mailto, FAQ question + answer shown, exactly one FAQPage, video dialog open/close),
  `cta.test.tsx` (2 trial CTAs; price stated as 500.000đ/tháng, no "500K", no table),
  `tiktok-tracking.test.tsx` (6 tracked CTAs). Old home-only `lp-home-*` CSS removed from
  `globals.css` (26 rules); rules `/san-pham` still uses stay.
- **Gates** (Node 20.20.2): `pnpm install --frozen-lockfile` OK; landing lint 0, type-check clean,
  vitest 13 files / 179 passed, `next build` OK, `check:seo` 17/17. Playwright on the production
  build: `/` at 1440 (6,664 px tall) and 390, `scrollWidth == clientWidth` at both, every image
  loaded; dialog opened at 1440. Screenshots `fasttrack/design/p34/evidence/p34b/home-{1440,390}-{top,full}.webp`,
  `home-1440-video.webp`.
  `PYTHON=… fasttrack/check.sh --since c95231e0` 5/5 PASS (migrations, isolation 12 passed, gitleaks,
  ruff and pytest n/a — no Python changed).
- Next: orchestrator merges P34-A, then this branch; owner to confirm the "500.000đ" price wording (DEBT).
