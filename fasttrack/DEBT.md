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

- [ ] P9-C: the demo's KPI dashboard (`/analytics/[metricKey]`) is gone, so
  `GET /v1/demo/analytics` is no longer read by any page; only the shell's
  `AnalyticsDataProvider` (plan impact block) still calls it. Backend left
  untouched on purpose — retire the route (and that provider) at merge. Also
  dead now: `.analytics-dashboard` and sibling KPI-card rules in `globals.css`.

## P10-A — card payload, reasons + cooldown, consent edits (AC-10.1, 2026-10-09)

- [ ] Card `status: expired` = proposal older than 14 days (`card_view.PROPOSAL_VALIDITY_DAYS`)
  or the product's title changed since. A surfaced card whose basis is unchanged is
  not rewritten nightly, so its `computed_at` ages even while the scoring keeps
  re-confirming it; it reads `expired` after 14 days. "Product changed" looks at the
  title only (description/images are not stored).
- [ ] `before_after` is only filled from a run's `run_write_values`; a pending card has
  none (Juli drafts the "after" inside the run). The UI shows field names only until then.
- [ ] `tiktok_codes` lists TikTok-sourced evidence only; nightly cards carry Juli's
  local title reading (named "Juli đánh giá" in `reason_full`), so it is usually `[]`
  until the run-time diagnoses are stored on the card.
- [ ] `seller_sku` needs an inventory sync that carries `seller_sku`
  (`inventory_items.seller_sku`, migration 079); webhook snapshots do not, and
  nothing backfills existing rows — `null` until the next Search Inventory poll.
- [ ] Cooldown "clear change" compares with the rate the card was proposed on. After
  a revert that rate may already have moved because of Juli's own change, which can
  lift the cooldown at once; storing the rate at revert time would be stricter.
- [ ] A cooled-down proposal leaves its slot empty that scoring run (no fallback to the
  product's next lever or the next-ranked product).
- [ ] Consent edits: the conversation window keeps the model's original tool-call
  arguments; only the tool result carries the edited values the model reads next.
- [ ] "Không thực hiện" on a *revert* run's consent records a `decline` reason against
  the original card's lever too (cools it down) — harmless, not intended.
- [x] (P10-C sends `{reason_code, note?}`; verified at integration) `POST /v1/demo/runs/{id}/revert` now 422s without a body: the current demo UI
  (Hoàn tác button) breaks until P10-C sends `{reason_code, note?}`.

## P10-C — Quyết định UI to the artboards (AC-10.3)

- [x] (P10 integration 9849f24a: wired to the merged backend; decline fallback removed) Built against the contract with fixtures; P10-A/P10-B not merged here.
  Live until then: no `recommendation.card` → card degrades to the P7-B
  diagnosis (no SKU chip, KPI current only); `/decline` 404/405 falls back to
  the consent decline; `/measurement` 404 → completion-based waiting line + P8
  `revert-questions`. Re-check every screen against the merged backend.
- [x] (P10 integration 9849f24a: rows mapped to P10-B's tools, contract §7) Manual (promotion) timeline: P10-B's promotion tool names are unknown,
  so tools before the pause fill the three Juli rows in order and tools after
  it are "Kiểm tra trên TikTok"; the pause is the first `workflow.status`
  starting "Đang chờ" (contract only names "Đang chờ ảnh từ bạn"). Pin the
  names/narration with P10-B.
- [x] (P10 integration 8ba4e9ff: `decision_id` on runs list + detail) Runs carry no decision id: a run is joined to its card by this visit's
  approve response, else by product title (SKU in run titles / queue depends
  on it). Ask P10-B for `decision_id` on the runs list.
- [ ] Production router: on a page first loaded with a query
  (`/decisions?tab=…`) `router.replace` never commits; `DecisionsPageClient`
  now follows the requested href itself, but the URL bar may lag in that
  case. Root-cause (Next 16 static page + useSearchParams) before merge.
- [x] (owner 2026-10-09: darken) a11y: the artboards' greyed not-yet-reached stage chips / step labels
  (#8a8a94 on #f0eef0 / white, ~3.3:1) failed AA contrast; `--qd-faint` is now
  #6b6b76 and the e2e axe check no longer excludes them.
- [ ] Photo consent captions are "Hiện tại" / "Mới" only (the artboard adds
  size and background, which the contract does not carry).
- [ ] Old P8-F CSS (`.qd-card`, `.qd-run`, `.qd-step`, `.qd-queue`, …) in
  `globals.css` is now dead except the rules editor's; `batch.ts`
  `groupStages`/`runStages` only used by tests. Remove at merge.
- [ ] One vitest run (of five) failed once under load in the full suite; not
  reproduced in four reruns. Watch for a flaky async test in quyet-dinh*.

## P10-B — cover-image flow, promotion flow, measurement (AC-10.2)

- [ ] Photo checks: "plain background" and "product ≥ 70 % of frame" are
  heuristics (`services/lever_flows/photo_checks.py`, `heuristic: true` on the
  check): border-strip median colour (≥ 90 % of border pixels within 28/255)
  and the bounding box of pixels > 40/255 away from it, on its longer side
  (≥ 0.70). A product on a matching-colour background, a busy product that
  touches the border, or a soft gradient can be misjudged — replace with a
  segmentation model (or the vision inspector) once there are real rejects to
  tune on.
- [ ] Cover-image consent order follows ADR-069: `upload_product_image` stages
  the photo on TikTok (not visible on the listing) BEFORE the consent, and the
  CONFIRM is on `update_product_listing` (the step that changes the listing).
  A declined consent leaves an unattached image in the shop's TikTok media.
- [ ] The listing's current cover ("before") is fetched by the worker from
  TikTok's CDN (https + allowlisted `*.ibyteimg.com` / `*.tiktokcdn*.com` /
  `*.byteimg.com` / `*.ttwstatic.com`, no redirects, ≤ 5 MB) — the host list
  is from observed URLs, not a TikTok spec; a new CDN host means "before"
  shows as unavailable (logged, not fatal).
- [ ] Photos are served at `/v1/demo/photos/{shop_id}/{token}` without the
  auth header (an `<img>` cannot send one): the 32-byte random token is the
  capability, never expires, and bytes live in Postgres (`run_lever_photos`,
  ≤ 5 MB each). Move to object storage with signed, expiring URLs before this
  sees volume; add a retention job.
- [ ] Multipart is parsed with the standard library's MIME parser (no
  `python-multipart` dependency); the body is read whole (≤ 5 MB + 64 KB,
  checked from Content-Length first).
- [ ] Seller Center deep link: every promotion type opens the marketing-tools
  management page (`https://seller-vn.tiktok.com/promotion/marketing-tools/management`);
  per-tool create URLs are not published — verify the path in a real shop and
  link each tool directly.
- [ ] Promotion proposal rules are mine where the spec is silent: lowest SKU
  price; unset margin floor = 0 % (never below cost); unset cap = margin
  headroom alone; ≤ 50 %; shipping discount = price × d rounded down to
  1.000 ₫, at most 30.000 ₫, for orders from the price; flash sale = same
  price, "a slot within 7 days"; durations 30 / 7 / 14 / 30 days. The card
  pipeline does not yet carry a structured proposed discount.
- [ ] Promotion verification is a fixed Search Activities page (100 per type)
  + Get Activity for up to 20 candidates; vouchers (coupons) are not searched,
  so a shipping discount created as a voucher is "not found". The "new"
  promotion is told apart from one that already existed by an opaque ref of
  the activity id. Read-only endpoints unverified live for a seller shop.
- [ ] Re-checks: each "Tôi đã áp dụng" resumes the run; a not-found schedules
  a Celery countdown re-check every 30 min while `verify_attempts < 4`; at most
  12 checks per run. A click and a scheduled re-check racing each other: the
  second finds the run not waiting (or waiting again) and is a no-op / one more
  check — no lock.
- [ ] The impact reader does not measure promotion runs (no WRITE
  `tool_executions` row): their measurement stage follows the calendar from
  `measurement_start`, values are computed at request time, no
  `impact_readings` rows, no day-7 "Hoàn tác?" question (Seller Center:
  the seller turns the promotion off).
- [ ] Measurement: daily averages from `analytics_performance_intervals`
  (rates pooled), GMV thực tế = GMV/day after − before, NOT control-adjusted
  (the impact reader's DiD readings store rates at 2 decimals, too coarse for
  CTOR); "too little data" = < 10 of 14 post days, < 7 pre days or < 20 orders
  after; "đang tiến triển" from current + 20 % of the gap; calibration moves
  a quarter of the way to realised ÷ expected (clamped 0..2). All mine — tune
  with the first real readings.
- [ ] Calibration is stored per shop and lever (`lever_calibrations`) but not
  yet read by the ranking (P10-A / P3 consumer).
- [ ] The day-14 verdict is computed lazily by the first
  `GET .../measurement` at the final stage (a GET that writes once), not by a
  job — a run nobody opens is never calibrated.

## P10 integration (2026-10-09)

- [ ] "Không thực hiện" at a photo / Seller Center wait ends the run by writing
  the terminal row + `workflow.failed` event directly from the route
  (`lever_flows.end_wait_by_seller`, compare-and-set on `waiting_external`),
  like the reaper — not through the runner. A promotion re-check already
  scheduled finds the run not waiting and no-ops.
- [ ] Photo consent images come from `GET /v1/demo/runs/{id}` (fetched by the UI
  for cover-photo runs when the run / consent / terminal state changes); the
  consent payload itself still carries no URLs.
- [ ] The Python↔TS P10 contract test reads the TS interfaces as text (field
  names only); types/nullability are pinned by tsc, not by the test.
- [ ] `tests/integration/test_reaper_two_tenant.py` still fails on PG16 (pre-existing
  since before effa4d4a, see P10-B log) — not investigated here.
- [ ] Not re-shot against a live backend: fidelity screenshots are still P10-C's
  stubbed ones.
- [ ] Photo links `GET /v1/demo/photos/{shop}/{token}` are unauthenticated and
  never expire (random token only). Owner accepted for deploy 2026-10-09;
  switch to signed, expiring URLs later.

## P11 signed-out sample (2026-10-09)

- [ ] `RecommendationsView` / `RecommendationsPanel` / `InProgressPanel` and the old
  fixture review flow are no longer reachable from `/decisions` (only by URL:
  `/decisions/recommendations/*`, the replay run). Retire them with their tests and the
  replay-scenario build check once the replay journey is re-pointed or dropped.
- [ ] The sample keeps its state in memory only (a reload resets it); the applied
  TN-021 card is listed in Đề xuất (counts in the group title) so Đo lường can show
  its SKU — same as a real shop where applied cards are returned.
- [ ] Sample photo consent: "before" image is a placeholder (no sample asset); the
  "after" is the seller's file as a blob URL.
- [ ] Sample-mode notice ("Dữ liệu mẫu · … shop minh họa …") is not in the
  artboards; it follows Home / Phân tích's sample notice.
- [ ] Vitest needs Node 20/22: Node 26's built-in `localStorage` shadows jsdom's
  (undefined without `--localstorage-file`), failing ~243 storage tests locally.


## P12 Phân tích redesign (2026-10-10)

- [x] (P13) Home's signed-out sample is still the household shop of `lib/shop-analysis/sample-report.json`; Phân tích and Quyết định show the cosmetics sample shop. — repaid: Home (and the shell header) now read `lib/phan-tich/sample-data.ts`'s `sampleEnvelope()`; `sample-report.json` stays only as a signed-in report stub in two Quyết định e2e specs.
- [ ] `scripts/demo_analysis_sample.py --check` fails at HEAD before P12 (`ImportError: VideoWindowMetrics` from `rankings`); `sample-rankings.json` is no longer read by the app and is kept only for that script.
- [ ] Row facts with no data source: AOV rows show "Đơn hàng SKU 30 ngày" instead of the artboard's "Món mỗi đơn" / "Đơn 1 món"; "Kênh khác" only for hero products (5-channel profile); "Lý do" on Kéo lên rows is not shown; Video "Nguồn" (traffic source) and LIVE duration are not available.
- [ ] Voucher stat reads the share of orders at or above a running voucher's threshold (`above_after`), not redemptions; "Sắp tới" omits "chưa đăng ký" (no campaign-registration data).
- [ ] `nhom=<metric>` scrolls to and outlines the metric's group; it does not filter the other groups out.
- [ ] Old `.pt-*` rules in `globals.css` are now unused (no component emits them).
- [x] Reason completion message (a0382006) shows the reason box only in the visit the reason was given; the backend stores `reason_code` but no read returns it, so after a reload the older text (no reason box) shows. — **accepted by the owner, won't fix** (2026-10-10): reasons are for Juli's learning; the seller need not see them again.

## P13 signed-in, no shop → sample (2026-10-10)

- [x] (owner 2026-10-10: show the sample name) The shell header in the no-shop state still names "Chưa chọn shop" (no "cập nhật HH:MM" line) above the sample, while the page's notice names the sample shop "Cửa hàng Mẫu Hoa Mai". Deliberate (the header is the seller's identity), revisit if the owner wants the sample name there.
- [ ] The sample's daily GMV bars (Lịch sale) average 6,31 tr ₫/ngày in the prior window vs the streams' summed 6,95 tr ₫/ngày (last window agrees: 7,12 vs 7,16 tr). Only the bars show it (no total is printed from them); left as the P12 artboard values.
- [ ] `SignedInQuyetDinh`'s own `!shop` empty state is now unreachable from `/decisions` (the page client routes no-shop to the sample); kept for direct callers / tests.

## P14-C/F cost data and off-API rule fields (2026-10-10)

- [ ] Neither cost endpoint has been read live. Field names and shapes are from the docs + OAS; the `voucher_deduction_*` / `shipping_fee_deduction_platform_voucher` semantics (amount vs voucher-type code) and which finance fee lines a VN shop gets must be confirmed on the first live read before any ROI uses them.
- [ ] The app's granted scopes are unconfirmed: without `seller.finance.info` the finance pass stops every cycle with `order_costs_permission_denied` (logged, not surfaced in the UI).
- [ ] Backfill is slow by design: ≤ 10 price + ≤ 10 finance reads per 15-min cycle (~960 orders/day/shop). A shop with more orders than that in 60 days takes several days to fill; raise `ORDER_COSTS_*_PER_CYCLE` once the real per-endpoint limits are known.
- [ ] A settled order is not re-read for later refunds / adjustments (finance stops at the first non-empty answer); price detail is re-read when the order's `update_time` moves.
- [ ] `sku_deductions` and `shop_economics` have no consumer yet (D24.5 / D24.11 / D24.12 ROI and promotion proposals are later P14 work); `lever_flows/promotion.py` still reads `product_cost` / `max_discount_pct` / `min_margin_pct` directly and ignores `sku_cost` / the shop-wide cap.
- [ ] No packaging / handling cost per order field (considered; no D24 consumer yet).
- [ ] `live_schedule` is shop-local time with no time zone stored (assumed Asia/Ho_Chi_Minh).
- [ ] In the signed-out sample only the P14 group is read-only; the older groups remain editable in memory (P11 behaviour).

## P14 card limits and learning (2026-10-10)

- [ ] The seller rule "Số thẻ mở cùng lúc" (`max_open_cards`) still has its P8-C range 1–5 and reports 5 when unset (`shop_rules.max_open_cards`, Quy tắc UI "Mặc định"); since D24.17 an unset rule means 30. When set it lowers the 30. Owner to decide: drop the rule, or re-range it to 1–30.
- [ ] The per-day / per-week surfacing counts reuse `decision_emission_novelty_ledger` as a surfacing log (`workflow_key` = `<card id hex>@<yyyymmdd>`) to avoid a migration; a dedicated column/table would be clearer once the migration chain is free.
- [ ] Legacy (non-ADR-106) workflow cards: a dismissed card still needs a basis change to return (ADR-087 d.6), unlike D24.17's "after 7 days"; expired ones do return after 7 days. Optimize Product follows D24.17 fully.
- [ ] *(content half resolved by the P14 integration, aace1159: `CONTENT_WORKFLOW_KEYS` is P14-E's `content_video` / `content_live`, plus payload `card_executor: "juli_drafts"`.)* `CAMPAIGN_PLAN_WORKFLOW_KEYS` (`campaign_plan`) and `CONTENT_WORKFLOW_KEYS` (empty; or payload `executor_type` video/live) are hooks: no producer writes those cards yet. Campaign plans have no "valid until registration closes" clock yet (they never expire).
- [ ] Withdrawal "out of stock" reads `inventory_items` quantity sum (no rows = unknown, kept); "metric at target" uses the current funnel window's rate against the card's `reference_rate`.
- [ ] `optimize_product/shop_report.py` (internal HTML report) still says "Đòn bẩy giá và Seller Center"; not seller-facing app copy, left.

## P14-E content cards (2026-10-10)

- [x] *(resolved by the P14 integration, aace1159 — the budget counts them; the ≤ 5/week creation sub-limit stays.)* Day-1 content slot: emission surfaces content cards like any other candidate
  until the card-limits work counts them (`workflow_key in
  content_cards.CONTENT_WORKFLOW_KEYS`, or payload `card_executor == "juli_drafts"`).
  The ≤ 5/week sub-limit is enforced at creation (new rows per ISO week), not at
  surfacing.
- [ ] Seller tone and banned words: no rule key exists yet (P14-F, merged in the P14 integration, added none either — still open); the run reads
  `shop_rules` rows `content_tone` / `tone` and `banned_terms` / `banned_words` if the
  seller-rules work adds them (unvalidated until then). Protected terms and the
  per-SKU discount cap are read today.
- [ ] LIVE candidate CTOR is the SESSION's (the ranking has no per-product split);
  a session featuring N products shares its loss 1/N. The run and the measurement use
  the product's own per-session CTOR (`get_live_products_performance`).
- [ ] Basket position: TikTok's LIVE product list carries no position field today;
  `basket_position` is read only if one of `position` / `basket_position` /
  `display_position` / `sort_order` / `order` appears, else omitted.
- [ ] Video measurement reads the shop video list over the window (per-video totals);
  a video posted near day 0 counts its whole window, not day-by-day.
- [ ] The content run's state lives in `workflow_runs.state["content_run"]` (no
  migration this phase); a dedicated table would make readings queryable.
- [ ] Seller-edited final text is stored per run (`edited_blocks`) but not yet exported
  to the SFT dataset (D24.8).
- [ ] UI: the publish-wait box has no Không thực hiện button (artboard has none); the
  backend accepts decline there. Card list is the P10 single column (artboard shows a
  2-column grid) and keeps the P10 uplift chip / group GMV line.
- [ ] Pre-existing local failures unrelated to P14-E (also fail at 7590ba9d):
  `test_cross_tenant_probe`, `test_destructive_migration_isolation`, 7 of
  `test_agent_workflow_task_wiring` (env: DATABASE_URL / CI flags).

## P14 integration (2026-10-10)

- [ ] Ranking across producers: P14-E content cards take `priority` 1..N among content candidates only, while Optimize Product cards number their own list; the budget sorts all `active` drafts by `priority`, so after day 1 a content card with priority 1 competes as an equal of the top Optimize card. A shared scale (e.g. by recoverable GMV/day) is not decided.
- [ ] P14-E's ≤ 5/week sub-limit counts per ISO week in UTC (`created_at`), the budget's weeks are the shop's (UTC+7, Monday); a few hours' offset on Sunday night/Monday morning.
- [ ] P14-E expires an open card at > 7 days (withdrawn + `expired_at`), the budget at ≥ 7 days (`expired` + `expired_at`); both now give the 7-day return, but the stored status differs by which ran first.
- [ ] PROGRESS cites AC `14E.6` for the P14-E UI row; ACCEPTANCE has only AC-14E.1–14E.5 (as on `fasttrack/p14-content`).
- [ ] 37 test/backend files fail `ruff format --check` when run over the whole tree from the repo root — the same 37 at ddef3245 (check.sh's changed-files ruff step is clean).
- [ ] `tests/integration/test_migrations.py::test_no_public_table_holds_update_beyond_its_call_site` (Postgres only) fails at ddef3245 already (7 tables granted UPDATE without a `GRANT_REQUIRED` call site: P8/P10 tables); P14-C's `081_order_cost_data` adds 3 more (`order_cost_fetches`, `order_finance_transactions`, `order_price_details`). Either register the call sites in `tests/unit/test_juli_app_grants_cover_mutations.py` or revoke the grants — owner/agent decision, not done in the integration.

## P16 Juli Ops (2026-10-10)

- [ ] **OpsSimulate artboard not yet explicitly reviewed by the owner** — implemented as
  drawn (incl. D25.11 window / trend); review requested.
- [ ] Simulation history: reports carry `daily_streams` / `daily_products` only from P16 on;
  until the daily job has run on P16 code a shop has no simulation data at all, and a shop
  never has more than its stored reports' days (≤ 60 today) — windows 7 / 14 / 30 are
  computable, **90 needs 180 days** and shows "Chưa đủ dữ liệu". No backfill of older days.
- [ ] Per-product volatility rows for Video / LIVE are products by traffic source (A-34),
  not per video / per LIVE session: no stored daily series exists per video or session.
- [ ] TikTok scope names in `services/ops/scopes.py`: only `seller.order.info` and
  `seller.finance.info` are documented in this repo; `data.shop_analytics.public.read`,
  `seller.product.basic`, `seller.promotion.info` are UNVERIFIED — check in Partner Center
  and set `TIKTOK_REQUIRED_SCOPES` if they differ.
- [ ] "Huỷ kết nối": TikTok has no token-revoke API — Juli destroys its stored tokens; the
  seller must remove the app in Seller Center to revoke TikTok's side. Pending runs get
  `cancel_requested` (the existing cancel path); a run parked in `waiting_*` stays in that
  status until its own expiry/reaper picks the flag up.
- [ ] `promotion_api_enabled` override is stored, shown and audited but gates nothing:
  Juli makes no promotion write (D13).
- [ ] Invite / disconnect e-mails need SMTP (`OPS_SMTP_*`); without it Ops shows the
  accept link to forward and the disconnect notice is only logged. The seller who opens
  an invite signed out must sign in and re-open the link (no deep-link resume).
- [ ] "Xem như shop": the live run event stream (SSE) is not mirrored — run details show,
  the event timeline is in Ops run detail (`/v1/ops/shops/{id}/runs/{run}`). The seller
  "Juli" tab is shown but not available in view-as.
- [ ] Ops "Quy tắc" writes commit the rule first and the audit row in a second
  transaction (the seller handler commits itself); a crash between the two would leave an
  unaudited rule change.
- [ ] D24.21 (2) implemented here ("Số thẻ mở cùng lúc" 5–30, default 30): existing seller
  rows below 5 are clamped up to 5 when read.
- [ ] Ops pages are desktop-first (1440 px artboards); below 900 px the columns stack,
  not separately designed.
- [ ] `public UPDATE grants` integration test (`test_no_public_table_holds_update_beyond_its_call_site`)
  still fails as at the P14 base (pre-existing, P14 tables); P16 adds no new table UPDATE
  for `juli_app` (only `users.staff_access_consent_at`, column-level).
