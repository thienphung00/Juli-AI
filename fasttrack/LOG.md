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
