# Debt — repay before merging into main

Every skipped gate or shortcut. Format: `- [ ] what — why skipped — how to repay`.

## Gates skipped by design (D4, D8)

- [ ] `pr.yml` does not run on this branch (typecheck, architecture/import-linter,
  bandit, nginx lints, demo/landing e2e, artifact gates, full regression,
  performance smoke) — speed — run the full `pr.yml` suite on the merge PR and
  fix what it finds.
- [ ] No Executor/Review artifacts, validators or ADRs — speed — write one ADR
  summarising DECISIONS.md D1–D19 before merge.
- [ ] `.claude` edit hooks and executor-cache pre-commit gate disabled —
  speed — restore `.claude/settings.json` hooks and `.pre-commit-config.yaml`
  entry from `main` in the merge PR.
- [x] ~~`fasttrack-deploy.yml` refuses demo/landing lanes~~ — repaid: demo by AC-7.9, landing on 2026-10-08 after the first real run failed its landing preflight (packages/contracts + pnpm-lock.yaml changed). The workflow now builds both artifacts with `build-release-artifact.sh` and hands them to deploy.sh.
- [ ] Deploy leaves the VPS clone `~/Juli-AI-v2` detached at the fast-track SHA
  — `release.yml`/`rollback.yml` re-checkout `main` first, but verify after the
  first fast-track deploy.
- [ ] Backup thresholds (≥1 MB, ≥10 TABLE DATA entries) are guesses — tune
  after the first real backup.
- [ ] `release.yml` release artifact / browser checks / GitHub release not
  produced for fasttrack deploys — speed — first deploy from `main` after merge
  runs the full release.

## P1 shortcuts and open risks

- [ ] A-33/A-31/A-36 returning daily intervals over a multi-day range is
  assumed, not verified against live TikTok — guarded (non-single-day rows are
  dropped and logged at ERROR) — verify on Fujiwa after first deploy.
- [ ] One `requests.Session` shared by 5 threads in parallel detail calls —
  works via urllib3's pool but not formally guaranteed — per-thread sessions if
  any flakiness shows.
- [ ] One Celery worker consumes all queues, so `ingest_priority` isn't truly
  ahead of `ingest_backfill` — add a dedicated worker if connects queue.
- [ ] Analytics list calls keep the 20-page incremental cap: catalogs > 1,000
  products are truncated with a warning.
- [ ] Partial ETL row rejections still advance the daily analytics cursor.
- [ ] First deploy bootstraps every already-connected shop (Fujiwa included):
  30-day fetch + history walk = a burst of vendor calls. Watch rate limits.
- [ ] Multi-day backfill windows carry no `conversion_rate` (list row only
  merged for single-day windows) — CVR history only from the daily pass;
  backfill it per day later if the model needs it.
- [ ] `fujiwa_poll_cycle` task still registered but unscheduled — delete
  after the fan-out is proven in production.

## P7-A shortcuts

- [ ] The daily diagnosis refetches all 60 A-34 days (plus orders, promotions,
  LIVE/video lists, product details: ~150–250 calls) per shop per day; the
  script's "days on disk are not refetched" cache is lost with the temp dir —
  cache daily A-34 rows (they are aggregates) or build from
  `analytics_performance_intervals` once its channel blocks are stored.
- [x] ~~The diagnosis fetch paces with `sleep 0.4 s` + 429 backoff, not the shared
  Redis per-endpoint rate limiter the poll path uses~~ — repaid (P7 integration,
  ebbe4df0): `shop_diagnosis_daily/pacing.py` takes each read's token from the
  poll's window (same key), waits instead of skipping, stops at 8 of 10.
- [x] ~~No per-shop lock on `build_shop_diagnosis`~~ — repaid (P7 integration,
  ebbe4df0): Redis lock `ingest:diagnosis:{shop}`, skip when held; a timed-out
  build keeps it until the TTL (budget + 300 s).
- [ ] The build task now skips (logs `shop_diagnosis_skipped reason=no_redis`)
  when `REDIS_URL` is unset — lock and rate limit live in Redis — the poll needs
  Redis too, so only a misconfigured worker hits it.
- [x] ~~`fasttrack/check.sh` gitleaks step not run locally~~ — run in P7
  integration (gitleaks 8.30.1): clean over origin/main..HEAD (the deploy's
  default range). With `--since 0332c405` it flags one `generic-api-key` false
  positive in `tests/unit/test_traffic_source_check.py:577` (a fake
  `access_token=` string in a test, commit 686efe02 from `main` #2106).
- [ ] That false positive fails a local `check.sh --since <pre-sync ref>` —
  it came from main — allowlist it in `.gitleaks.toml` on the merge PR.
- [ ] The timeout (`SHOP_DIAGNOSIS_BUDGET_SECONDS`, default 1800 s) cancels the
  await but cannot stop the fetch thread mid-call.

## P7-B shortcuts and open risks

- [ ] Add-to-cart rate exists only for days fetched as single-day windows (A-34
  `add_cart_count` kept under `traffic_breakdown["A34_TOTAL"]`); the 30-day
  bootstrap and history backfill carry none, so new shops show it as null with a
  note for ~a month — fetch A-34 per day in the fast phase, or a column + backfill.
- [ ] Card funnel is all-channel (A-33 sums): no PRODUCT_CARD scope, so the
  ADR-106 amendment-2 channel-block funnel and the amendment-4 traffic-source
  check are not applied on cards (caveat on every card) — persist A-34 channel
  blocks per product-day.
- [ ] Listing evidence is local and title-only (`products` stores no description
  or images); most CTOR cards are "Chưa hỏi TikTok" until the diagnoses endpoint
  is called at scoring time — wire `get_product_diagnosis` into the scoring pass.
- [ ] Report-only levers not on cards: owner tests, Seller Center cards, gift
  fallback, ratings filter, flash sale / shipping gates (need orders, promotions,
  ratings in the store). BMSM threshold uses the mean-items fallback (no order
  histogram). Discount cap is never set (no seller setting stored).
- [ ] D22 recoverable GMV/day mixes the diagnosis's 14-day rate gap with 30-day
  volume and AOV; CTR-stage value multiplies by the product's own CTOR (the
  literal "gap × impressions × AOV" would price clicks as orders) — confirm with
  the owner; replaced by the P3 model anyway.
- [ ] A surfaced ADR-106 card keeps its evidence numbers from the day it was
  surfaced (ADR-087: an offer is not rewritten) and stays until the seller acts,
  even if the product leaves the top 10.
- [ ] Legacy rule-pipeline `optimize_product_2` cards on a shop with product
  analytics are rewritten in place (if their product ranks) or set to the new
  status `withdrawn`, even when already surfaced — a status string with no DB
  check constraint; readers that enumerate statuses should learn it.
- [ ] Per-workflow cap is a code default + env (`CDP_DECISION_EMISSION_WORKFLOW_MAX_ACTIVE`),
  not per-shop config.

## P7-C UI (2026-10-08)

- [x] ~~Decision evidence field names are assumed~~ — repaid (P7 integration,
  c446bb2d): mapper reads `recommendation.diagnosis/evidence` (typed in
  `@juli/contracts`), tested on a fixture captured from the backend endpoint test.
  The fixture is a copy — re-capture it if `demo_decisions.py` models change.
- [ ] "Từ chối" on a signed-in card only hides it for the session (no reject
  route) — no backend endpoint — add `POST /v1/demo/decisions/{id}/reject` and
  call it; the on-screen copy says the choice is not saved.
- [x] ~~Anonymous Phân tích sample is a 100 KB bundled JSON, generator kept
  out of the repo~~ — repaid by P8-E: `scripts/demo_analysis_sample.py`
  regenerates it byte-for-byte (plus `sample-rankings.json`); `--check` fails
  when stale. Still ~100 KB + 32 KB, lazy-loaded by the shell.
- [ ] Inter font is named in the stack but not loaded (mock imports Google
  Fonts) — no network at build — add `next/font` if the owner wants Inter
  everywhere.
- [x] ~~Demo header keeps the old mode switcher / "Làm mới Demo" controls inside
  the kit header~~ — repaid by P8-D (AC-8.5): header follows ADR-109 d.7; the
  mode switcher is gone, Đăng nhập / Làm mới Demo / Cài đặt sit in the
  shop-avatar menu.
- [x] ~~e2e: static-asset-render ×3 and accessibility "Analytics chart…" failed after the D21 restyle~~ — repaid: specs follow D21 (flat kit background, gradient wordmark, KPI dashboard at `/analytics/gmv-tiktok`); 18/18 pass on both projects.
- [ ] vitest needs Node 20 locally: under Node 26 jsdom's `localStorage` is
  shadowed (270 failures on untouched main) — env — pin `.nvmrc` to 20.

## P8-A Rankings (2026-10-08)

- [ ] Rankings are built only when the job builds the report: a shop whose
  report for the end date already exists (the deploy day) gets rankings from
  the next analytics day, or a `force=True` rebuild — idempotency key kept
  on the report — add a "rankings missing" check to `_plan` if the first day
  matters.
- [x] ~~`video_metrics` (P8-B's per-video window metrics) is a parameter of
  `build_and_store_shop_diagnosis` only; the worker task
  (`workers/tasks/shop_diagnosis.py`) does not pass it yet, so production
  stores no video rankings — P8-B / integration wires it.~~ — repaid (P8
  integration, fe21ec7b): the worker body passes `fetch_ranking_videos`; tests
  `test_the_worker_body_fetches_video_windows_with_the_snapshots_resources`,
  `test_a_failed_video_fetch_stores_the_report_and_the_other_13`.
- [ ] Interpretations of ADR-109 d.5 made without the owner: impressions use a
  single 1,000 floor for both "listed" and "Rõ" (ADR-108's 10 / 30 floors scaled
  to one number); "not listed" = under the floor on BOTH sides (max), "Rõ" =
  ADR-108 `label()` on (min side, test); a content row's impressions are measured
  against the prior window's mean per session / video; the fold threshold is 1 %
  of the stream's ΔGMV (not of the factor); closing "ít đơn" reads "ít lượt
  hiển thị" / "ít lượt bấm" on those metrics — confirm with the owner.
- [ ] LIVE rows come from `live/sessions.json` (fetch keeps the top 60 sessions
  by GMV over 60 days; session-level product impressions/clicks/SKU orders);
  sessions beyond the cap and the difference to the A-34 LIVE block land in
  "Thay đổi cơ cấu phiên LIVE". `live/products/*` is not read.
- [ ] Products with SKU orders but zero add-to-cart on a side (buy-now) cannot
  split CTOR into its two steps; they are left out of the step tables and sit
  in their mix row.
- [ ] New API symbols `DemoMetricRankingResponse` / `get_demo_metric_ranking`
  added to `check_module_drift.py`'s allowlist (as P7 did for
  `get_demo_analysis`) instead of documenting them in a backend/api MODULE.md.

## P8-B per-video 30/30 (2026-10-08)

- [ ] Date-range answer is from the spec only — no live call from the agent —
  owner runs `python scripts/shop_diagnosis_fetch.py --shop fujiwa --end 2026-10-06 --video-windows`
  and checks `basis=date_range` and plausible per-window impressions.
- [x] ~~`fetch_video_windows` is not called by `job.py` yet — P8-A owns the ranking
  job — orchestrator wires it after `fetch_snapshot` (same resources, same
  `load_snapshot`), passes the result to the ranking.~~ — repaid (P8 integration, fe21ec7b): `job.fetch_ranking_videos` calls it in the fetch thread with the snapshot's rate-limited resources; `video_windows.ranking_videos` converts to the ranking's `VideoWindowCounts`.
- [ ] Whole run falls back to `posted_in_window` when the FIRST details call
  fails (assumed to mean scope/endpoint refused); a single bad first video
  therefore degrades the day — heuristic — fall back only on scope/permission
  error codes once the live error shape is known.
- [ ] Fallback prior-window rows use 60-day snapshot totals (include days after
  the window) and impressions only where the snapshot's video-product file has
  the undocumented `product_impressions` — approximation, flagged by `basis` —
  drop the fallback once the live check confirms the date-ranged path.
- [ ] SKU orders per window come from the list only (details has none); a video
  missing from a window's list counts 0 even if the list hit its page cap —
  spec gap — record `hit_page_cap` like `fetch_orders` does.
- [ ] `video_post_time` is parsed as naive shop-local time (spec says ISO 8601,
  no zone; Fujiwa shows "2025-10-28 13:28:37") — unverified — confirm in the
  live output.
- [ ] Details calls are keyed per video path in the poll's Redis window, so the
  shared gate never slows them; pacing is `sleep_s` (0.4 s) — same as the
  existing per-video product calls — key a shared bucket per endpoint family if
  TikTok throttles.
- [ ] ADR-109 Consequences says the video list carries totals "since posting";
  the spec says the list is date-ranged — doc — correct the ADR line when the
  live check confirms.

## P8 integration (2026-10-08)

- [ ] Every daily build now adds P8-B's video reads (2 list walks + ≤ 40
  details calls, 0.4 s pacing ≈ 17 s plus Redis-gate waits) inside the same
  1,800 s task budget — unmeasured on a live shop — check one build's
  `shop_video_windows_fetched` log (`calls`, `basis`) after the deploy.
- [ ] `ranking_videos` drops a window side whose product impressions are
  unknown (P8-B fallback without the snapshot's per-video file) or that has no
  activity; such videos land in "Thay đổi cơ cấu video". A run with zero
  usable videos still stores the two Video tables (closing rows only) —
  interpretation — confirm with the owner whether an empty table should be
  stored or skipped.
- [ ] `check_import_boundaries --strict` still reports the base's 56
  violations (P8-A's two new ones fixed in fc07b873); not run by check.sh.

## P8-G get_product_diagnoses (2026-10-08)

- [x] ~~A TikTok API error in `get_product_diagnoses` fails the run~~ — repaid: vendor/guard errors soft-fail to `unavailable=True` + WARNING log; programming errors still propagate.
- [ ] Label table covers only the codes in `listing_signals.py` plus prefix fallbacks
  (TITLE_/DESC_/MAIN_IMG_/PRICE); no price-diagnosis code is confirmed in the corpus,
  so "Giá kém cạnh tranh" is only the example wording — add exact labels once a
  live read shows the codes.
- [ ] Prompt budget headroom is 8 tokens (v3 composed = 2992 of 3000); frozen v1/v2
  composed prompts now exceed 3000 (not gated, production pins v3) — any further
  playbook text needs a v4 prompt or a trimmed table.
- [ ] Guidance lives in the step intent (the playbook table), not in v3.md, because
  released prompt prose is immutable (ADR-072 d.4).
- [ ] Not run live against TikTok (no credentials in this task); response shape
  (`products[].diagnoses[].diagnosis_results[]`) taken from `parse_tiktok_diagnoses`.

## P8-D shell + Trang chủ (2026-10-08)

- [ ] Header subline shows only "TikTok Shop": no API exposes the shop's ngành
  or SKU count — no data — add both to `GET /v1/demo/analysis` (or `/v1/shops`)
  and pass them to `shopSubline`.
- [x] ~~Signed-in Trang chủ + header read `/v1/demo/analysis` once in the shell;
  Phân tích still fetches its own copy (ranking toggle) — two requests on a
  visit to /analytics~~ — repaid by P8-E (AC-8.6): Phân tích reads
  `useShopReport()`; pinned by vitest "/analytics reads the report once" and the
  signed-in e2e (`analysisCalls` length 1).
- [ ] Dead code after the shell swap: `recommendationContext` in `demo-state`
  (fed only the retired assistance aside), the persisted `juli_demo_mode`, and
  the old `.demo-header/.demo-assistance/.demo-mode-switcher/.juli-primary-nav/
  .demo-launchers` rules in `globals.css` — scope — delete in a cleanup commit.
- [ ] Signed-in shell/Home are covered by vitest (injected loader, stubbed
  fetch) and a stubbed-route screenshot, not by an e2e against a real backend.
- [ ] Juli (locked) and the shop menu are a plain disclosure, not an ARIA
  `menu` with arrow-key roving — simpler — upgrade if user testing asks.

## P8-C Before/after + Hoàn tác, rule store, day-7 guardrail (2026-10-08)

- [ ] `set_by` ('team' | 'seller') on `PUT /v1/demo/rules/{key}` is taken from
  the request and only checked against that allowlist — the codebase has no
  team/staff role — any signed-in owner of the shop can claim `team` — add a
  team role (or an operator allowlist) and derive `set_by` from it.
  `set_by_user_id` is always the authenticated caller.
- [ ] Stored but not yet consumed: `product_cost` (+ CSV import service, no
  route), `min_margin_pct`, `max_discount_pct`, `protected_terms` — their
  consumers (gross-margin ranking D18, price cards, listing-write guard) do not
  exist yet — wire each when its consumer lands; protected terms should refuse
  an `update_product_listing` that drops one.
- [ ] Price is captured (read-back only, no sent-value fallback) but never
  reverted: a run that changed a price is refused ("Juli không tự hoàn tác giá")
  — D13 keeps price writes off — revisit if price writes are ever enabled.
- [ ] Attributes are not captured: `update_product_listing` passes the
  product's attributes through unchanged, so nothing to undo today — capture
  them when a lever writes attributes.
- [ ] Restoring photos re-sends the listing's previous image URIs as
  `main_images`; untested against the live API (staged-image writes are not
  wired in production either) — verify on the sandbox shop before relying on it.
  `GET .../changes` shows images as `{count}` only.
- [ ] The S-FR-8 live read (API pre-check) and the in-run re-check use the
  sandbox write resources, because agent writes go to the sandbox merchant only
  (`factories.py`) — when P5 writes to the real shop, the live reader and write
  resources must resolve per shop.
- [ ] The impact reader measures a revert's write like any listing change
  (impact readings are written for it); only the day-7 guardrail skips revert
  runs — decide whether revert executions should be excluded from impact
  readings / calibration.
- [ ] Day-7 bands are per metric over the impact reader's product-grain metrics
  (impressions, ctr, conversion_rate, items_sold, gmv, sku_orders,
  gmv_per_order), not per traffic stream; the question is raised on the first
  breaching execution of a run and stays one per run.
- [ ] The "Hoàn tác?" question is its own table and endpoints
  (`/v1/demo/revert-questions`), not an action card — Đo lường (P8-F) must read
  it there.
- [ ] `tests/unit/test_agent_workflow_task_wiring.py` (7 tests) fails without a
  `DATABASE_URL` in the environment (pre-existing; 29/29 pass with
  `DATABASE_URL=sqlite+aiosqlite:///:memory:`), so check.sh-style runs report it red.

## P8-E Phân tích UI (2026-10-08)

- [ ] The hero ranking toggle (GMV 60 ngày gộp / 30 ngày gần nhất) is gone from
  Phân tích: it needed a second `?ranking=30d` report fetch and ADR-109 does
  not show it — scope — re-add as an on-demand fetch in `HeroList` if the
  owner wants it.
- [ ] "✦ Juli gợi ý" says "Tối ưu <metric>: <reason from the report's numbers>
  · kéo GMV/ngày …" with no "Mục tiêu": the backend gives no per-stream target
  and no TikTok diagnosis per ranking row (the video's "TikTok chẩn đoán"
  column) — no data — add both to the ranking payload (P8-G's
  `get_product_diagnoses` codes, D22 recoverable GMV) and render them.
- [ ] The bottleneck uses the report's four factors only; when it is CTOR on
  Thẻ sản phẩm the default ranking is CTOR, not the weaker of its two steps
  (step contributions are only in the rankings payload, not the report) —
  simpler — pick the step from `product_card/add_to_cart_rate|orders_per_cart`
  `stream_factor_gmv` if the owner wants the video's "Đơn/thêm giỏ" default.
- [ ] Ranking direction defaults to "Kéo xuống" even when only "Kéo lên" has
  rows (e.g. sample LIVE × CTOR shows "Không có phiên LIVE nào…" + closing
  rows) — honest but one click more — auto-pick the non-empty side.
- [ ] Stream labels/subtitles and the slug map exist twice (Home's
  `home-metrics.ts` STREAMS and `lib/phan-tich/model.ts` STREAM_SPECS) —
  parallel work with P8-D — fold into one module.
- [ ] Contrast fixes for `.badge-success`, `.change-chip--*` and flat
  `.change-pill` are scoped to `.pt-page`; the kit rules themselves (used on
  Home, Quyết định) still use the raw status hue — scope — darken them in the
  kit block and re-run axe app-wide.
- [x] ~~Pre-existing, not P8-E: vitest `replay-scenario.test.ts` "is
  byte-identical to the fixture the capture tool produced" fails on the merge
  base (41584c55) too — the client copy of the golden scenario drifted from
  `tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json` (likely
  P8-G's playbook change) — re-copy the fixture in the integration.~~ —
  repaid by P8-F (d1695f17): fixture re-copied (only `prompt_sha256` moved);
  `expires_at` is rebased at runtime by `replay-scenario.ts` already.


## P8-F Quyết định UI (2026-10-09)

- [ ] Anonymous Quyết định is still the legacy fixture layout
  (`RecommendationsView` + mock In-Progress + the staged run route); only the
  signed-in branch has ADR-109's three sub-tabs, grouped cards, timeline and
  Đo lường — no sample decisions/run data exist for the anonymous door —
  generate a sample decisions + recorded run fixture (as P8-E did for
  rankings) and render `SignedInQuyetDinh`'s panels from it.
- [ ] Đo lường shows no numbers: there is no measurement read for a run
  (impact readings are not exposed under `/v1/demo`) — no API — after day 7
  each row says "Juli chưa có số đo"; add a per-run readings route (P6) and
  render before → after vs expected.
- [ ] Group header shows no "current → target rate": the backend gives per-card
  `current_rate`/`reference_rate` only, no group target — no data — only
  "GMV dự kiến = Σ recoverable GMV/ngày × 30 (ước tính theo quy tắc)".
- [ ] Card code is the TikTok product id (last 6 digits); the seller SKU code
  of the video ("SV-012") is not in the decisions payload — no data.
- [ ] "Mã TikTok" shows the lever evidence `detail` (source tiktok, else Juli's
  local check); raw codes are never shown and no label map exists client-side
  for codes without a detail — fine for now.
- [ ] Rules 422 messages are English from the backend; the editor shows a
  per-rule Vietnamese range sentence instead of the server text — backend
  should send `detail.message` in Vietnamese like `/revert`.
- [ ] "Bỏ" (drop a card) is session-only, as before (no reject route) — scope.
- [ ] Batch approve navigates to the first new run; a card whose approve
  failed is listed in an alert, not retried — honest, one click more.
- [ ] Upcoming timeline steps come from a client-side copy of the playbook
  order (`OPTIMIZE_PLAN` / `REVERT_PLAN` in `lib/quyet-dinh/timeline.ts`) —
  shown greyed without time/result — drifts if the playbook changes; a
  `workflow.started` payload listing the plan would remove it.
- [ ] A revert run is recognised by `GET …/changes` `reverts_run_id` (one read
  per selected run) because `GET /v1/demo/runs` items carry no
  `reverts_run_id` — add it to the list item.
- [ ] `/settings` signed in now shows only the rules editor; the old
  workflow-template/threshold tabs remain for anonymous only.

## P9-A — email sign-in (AC-9.1)

- [ ] Session lifetime unchanged from Google: the access token is stored with
  its refresh token but nothing refreshes it (same as the Google door) — after
  ~1 h API calls 401 and the seller signs in again. A shared refresh step
  (`POST /auth/v1/token?grant_type=refresh_token`) would fix both doors.
- [ ] Not exercised against a real Supabase project (no email provider enabled
  yet, no inbox): GoTrue shapes are from its docs/source and stubbed in tests.
  First owner-run sign-in is the live check (OTP, magic link, template code).
- [ ] `users.email` for an email-OTP seller is filled only if the token carries
  `email_verified: true` (top level or `user_metadata`); current hosted GoTrue
  sets it for email identities, older versions did not — then the column stays
  NULL (`claims.py` is strict on purpose). Check one row after the first sign-in.
- [ ] Code length: the UI says "6 chữ số" and accepts ≥ 6 digits; if the owner
  sets Email OTP Length ≠ 6 in Supabase the label is wrong.
- [ ] The magic link opens wherever the mail client opens it (often a new
  tab); sessionStorage is per tab, so the original tab stays signed out —
  same storage model as Google, accepted.

