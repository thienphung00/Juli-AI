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
