# Debt — repay before merging into main

Every skipped gate or shortcut. Format: `- [ ] what — why skipped — how to repay`.

> Closed items from the sections before 2026-10-12 (P0–P17) are in [`archive/DEBT-pre-2026-10-12.md`](archive/DEBT-pre-2026-10-12.md) (moved verbatim, P53 / D62); every open item is still here.

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
- [ ] The build task now skips (logs `shop_diagnosis_skipped reason=no_redis`)
  when `REDIS_URL` is unset — lock and rate limit live in Redis — the poll needs
  Redis too, so only a misconfigured worker hits it.
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

- [ ] "Từ chối" on a signed-in card only hides it for the session (no reject
  route) — no backend endpoint — add `POST /v1/demo/decisions/{id}/reject` and
  call it; the on-screen copy says the choice is not saved.
- [ ] Inter font is named in the stack but not loaded (mock imports Google
  Fonts) — no network at build — add `next/font` if the owner wants Inter
  everywhere.
- [ ] vitest needs Node 20 locally: under Node 26 jsdom's `localStorage` is
  shadowed (270 failures on untouched main) — env — pin `.nvmrc` to 20.

## P8-A Rankings (2026-10-08)

- [ ] Rankings are built only when the job builds the report: a shop whose
  report for the end date already exists (the deploy day) gets rankings from
  the next analytics day, or a `force=True` rebuild — idempotency key kept
  on the report — add a "rankings missing" check to `_plan` if the first day
  matters.
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
- [x] ~~`check_import_boundaries --strict` still reports the base's 56
  violations (P8-A's two new ones fixed in fc07b873); not run by check.sh.~~ — repaid in P53
  (D62): strict + baseline PASS; the baseline is the 54 grandfathered rows.

## P8-G get_product_diagnoses (2026-10-08)

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

## P10-C — Quyết định UI to the artboards (AC-10.3)

- [ ] Production router: on a page first loaded with a query
  (`/decisions?tab=…`) `router.replace` never commits; `DecisionsPageClient`
  now follows the requested href itself, but the URL bar may lag in that
  case. Root-cause (Next 16 static page + useSearchParams) before merge.
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
- [x] ~~`tests/integration/test_reaper_two_tenant.py` still fails on PG16 (pre-existing
  since before effa4d4a, see P10-B log) — not investigated here.~~ — repaid in P53 (D62): the
  per-workflow case wrote aware stamps into naive columns; red on a PG16 server in
  Asia/Ho_Chi_Minh, green after the fix in Asia/Ho_Chi_Minh, UTC and America/Los_Angeles.
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

- [ ] `scripts/demo_analysis_sample.py --check` fails at HEAD before P12 (`ImportError: VideoWindowMetrics` from `rankings`); `sample-rankings.json` is no longer read by the app and is kept only for that script.
- [ ] Row facts with no data source: AOV rows show "Đơn hàng SKU 30 ngày" instead of the artboard's "Món mỗi đơn" / "Đơn 1 món"; "Kênh khác" only for hero products (5-channel profile); "Lý do" on Kéo lên rows is not shown; Video "Nguồn" (traffic source) and LIVE duration are not available.
- [ ] Voucher stat reads the share of orders at or above a running voucher's threshold (`above_after`), not redemptions; "Sắp tới" omits "chưa đăng ký" (no campaign-registration data).
- [ ] `nhom=<metric>` scrolls to and outlines the metric's group; it does not filter the other groups out.
- [ ] Old `.pt-*` rules in `globals.css` are now unused (no component emits them).

## P13 signed-in, no shop → sample (2026-10-10)

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

- [ ] P14-E expires an open card at > 7 days (withdrawn + `expired_at`), the budget at ≥ 7 days (`expired` + `expired_at`); both now give the 7-day return, but the stored status differs by which ran first.
- [ ] 37 test/backend files fail `ruff format --check` when run over the whole tree from the repo root — the same 37 at ddef3245 (check.sh's changed-files ruff step is clean).
- [ ] `tests/integration/test_migrations.py::test_no_public_table_holds_update_beyond_its_call_site` (Postgres only) fails at ddef3245 already (7 tables granted UPDATE without a `GRANT_REQUIRED` call site: P8/P10 tables); P14-C's `081_order_cost_data` adds 3 more (`order_cost_fetches`, `order_finance_transactions`, `order_price_details`). Either register the call sites in `tests/unit/test_juli_app_grants_cover_mutations.py` or revoke the grants — owner/agent decision, not done in the integration.
  **D24.21 pass:** P14-C's three are gone from the list — `081` no longer grants UPDATE on `order_price_details` / `order_finance_transactions` (replaced by delete + insert), and `order_cost_fetches`' UPDATE is registered (`store.py` attempt counter). Still listed (7, pre-existing): `lever_calibrations`, `run_lever_flows`, `run_lever_photos`, `run_revert_questions`, `shop_diagnosis_reports`, `shop_metric_rankings`, `shop_rules`.

## D24.21 owner choices (2026-10-10)

- [ ] **ADR-087 d.6 replaced for dismissed cards** (D24.21 (3)): a legacy-workflow card the seller rejected / declined / reverted returns as a new revision 7 days later on the clock alone, basis moved or not. ADR-087's text ("the clock is a cap, never a trigger") is not amended yet; `persist.py` / `action_cards/MODULE.md` document the change. Executed cards keep the ADR-087 rule (clock + basis).
- [ ] Legacy-workflow cards (no ADR-106 lever, executor `other`) take the daily **Juli** slots, after the ADR-106 Juli cards (their priority scale is not comparable). The owner's slot list names only Juli / Seller Center / content; this mapping is the agent's choice.
- [ ] The Optimize Product plan keeps the top 30 **per executor type** (Juli / Seller Center), up to 60 drafts, so the Seller Center slot is not starved by a shop whose best 30 are Juli cards. The open limit (30) still caps what surfaces.
- [ ] Content-card priority now multiplies expected GMV by the lever's calibration × reason penalty (`video_script` / `live_script`); no content calibration is measured yet, so only seller reasons move it today.
- [ ] Banned terms are checked on the listing write at approve (Juli's proposal and the seller's edit) — the agent's drafting prompt does not receive them yet, so a proposal containing one must be edited by the seller before approval.
- [ ] A `max_open_cards` value stored under the old 1..5 range reads as 5 (clamped); no data migration.

## P15 content analysis (2026-10-10)

- [ ] **Deviation, owner review**: the "Phân tích video" block has no artboard; it reuses the
  ContentRun / Phân tích box styles (`.qv-va*` in `quyet-dinh.css`).
- [ ] **Deviation**: OCR and product-on-screen use `gpt-5.4-nano` vision on keyframes (low detail,
  near-duplicate frames not resent) instead of EasyOCR / PaddleOCR / OpenCLIP — all need torch or
  paddle (hundreds of MB) on the VPS. Scene cuts use the port of the content engine's
  `reference_analyze.py`, not PySceneDetect (BSD-3, but needs OpenCV). No new Python dependency.
- [ ] LIVE product timing from TikTok does not exist (A-26 per-minute metrics are shop-level, A-27
  has no timing): windows come from ASR mentions in the first 60 min; a product first named after
  that is "not found". The pipeline accepts timing hints (`live_timing_s`) for when an API appears.
- [ ] Per-shop cap override is read from `shop_rules` key `openai_monthly_cap_usd` (number) —
  not in `RULE_KEYS`, so only a direct write (P16's Ops console) sets it; P16 may move it, then
  change `costs.monthly_cap_usd`. D25.8's "alert the team" on cap is not done here.
- [ ] Cost figures are estimates: ASR by minutes × a static price table (`whisper-1` $0.006/min),
  vision / scoring by the token price table; not reconciled with OpenAI billing. Not measured
  against the live API (no key in this session) — only on mocked usage.
- [ ] A retry after a provider error restarts the pipeline from the beginning (stages already paid
  are paid again; ≤ 3 attempts).
- [ ] `content_analysis` shares the main worker (`-Q …,content_analysis`, prefork concurrency =
  CPUs); a dedicated `--concurrency 1` unit if analyses ever delay agent runs.
- [ ] Enqueue failure leaves the row `queued` with no automatic re-enqueue (runbook has the manual
  command); expired `awaiting_upload` rows are shown as expired but stay in the table.
- [ ] Uploads from a content run carry no Phân tích row (`content_ref` null), so they count as
  "đã tải lên", not best / weakest.
- [ ] nginx default `client_max_body_size` (1 MB) still applies to every other route — P10's 5 MB
  photo upload route has no override either (pre-existing; checked while adding the chunk location).
- [ ] Ops before deploy (owner): `apt install ffmpeg` on the VPS, create
  `/var/lib/juli/content-uploads` (0700), reinstall the worker unit and nginx vhosts.
- [ ] Demo vitest `rules-editor-off-api.test.tsx` failed 2 tests once in the full parallel run and
  passes alone (13/13) — timing flake under load, not P15 code.

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
## P17 onboarding speed (2026-10-10)

- [ ] Time to first card is an estimate (≈ 15–60 s, ≤ ~3–4 min when the shared A-34 window is busy); measure it on the first real connect from `shop_quick_scan_done.seconds_since_connect`.
- [ ] The quick scan runs "in parallel" only if the worker has ≥ 2 processes: the unit runs one `celery worker` (prefork, one process per CPU). On a 1-CPU VPS it queues behind the fast phase; a dedicated `-Q ingest_priority` worker (or `--concurrency 2`) is the fix.
- [ ] The quick scan and the fast phase share the A-34 rate-limit window (same endpoint key); the scan waits for it rather than skipping. No priority between them.
- [ ] A placeholder `products` row (Get Product title / status, `update_time` 1970-01-01) exists until the fast phase's product sync overwrites it; if that sync never runs, the row stays minimal (no price, category).
- [ ] Quick cards carry no 30/30 `evidence` block (A-34 gives one 14-day total, no daily rows); the payload's `evidence` is the empty-series reading until the full run re-scores the card.
- [ ] Only `QUICK_SCAN_TOP_PRODUCTS` (10) products are asked to TikTok; a weak product outside the top 10 by 14-day GMV cannot get a quick card (by design, D26 "top 5–10").
- [ ] A quick card whose product the full run proposes with another lever is withdrawn and replaced by a new revision the same day; the seller sees one card disappear and possibly another appear (Juli slot already counted for the day).
- [ ] The API's real look-back for shop analytics is undocumented; 180 is the documented limit of a sibling endpoint. The walk's out-of-range halving records TikTok's actual limit (`shop_history_done` reason `out_of_range`, `history_earliest_date`) — read it from the first production shop and note it in D25.12.
- [ ] Onboarding ETA is a fixed typical duration (900 s from the fast phase's start), not measured progress; the history step gives "còn N ngày", no time.
- [ ] `quick_scan_status = running` older than 15 min reads as failed in the status (worker died); the row itself is not repaired.
- [ ] `_marked_enqueue` keeps the `quick_scan_queued` marker for 2 h even when the enqueue returned no task id; a second bootstrap within 2 h does not retry a lost scan (the full diagnosis writes cards anyway).
- [ ] No MODULE.md for `services/onboarding` (not a `map.md` row yet).
- [ ] UI (fork): a failed onboarding read hides the strip and retries every 60 s (not 15 s), so cards stop refreshing on Quyết định until the next successful read.
- [ ] UI (fork): "Độ tin cậy: Tham khảo" shows only next to an expected GMV; a quick card without `expected_gmv_per_month` shows the chip but not the confidence.
- [ ] UI (fork): Home has no cards list, so the poll only re-reads Home's and Phân tích's report (once step 2 is done and the report was empty); Phân tích's per-cell "Xem đề xuất" counts are not refreshed.
- [ ] UI (fork): the first onboarding read does not re-read Quyết định's cards (it lands with the page's own read), so new cards appear from the second poll (~15 s after load).
- [x] (repaid in P53, D62: allowlist regenerated from the tree) Pre-existing, not P17: `tests/harness/test_module_md_sync_parser.py` (2) fails at 09960b20 too (P14 drift + stale `_WEEKLY_NOVELTY_CAP` entry); regenerate the allowlist in an integration pass.

## P27 (D32) shortcuts and open risks

- [ ] Per-channel CTOR / AOV need per-channel SKU orders: persist A-34's
  `seller_product_card_performance` (+ `shop_tab_performance`) blocks per product-day
  (`attributed_sku_orders`, `attributed_gmv`) — the same fetch DEBT P7-B already asks for.
  Until then a Mô tả / price card's CTOR is all-channel by necessity.
- [ ] Per-channel clicks are the mapper's `round(impressions × ctr)` from A-33; at TikTok's
  CTR precision the error is well under one click a day per channel, but it is derived, not a
  count TikTok reports.
- [ ] Category benchmarks (D29.3) are all-channel and are not used for a channel KPI.

## P29 merge (2026-10-13)

- [x] (repaid in P53, D62: the 8 deep imports go through `services.ops` / `services.action_cards`) Pre-existing, not P29-merge: `tests/unit/test_import_boundaries.py::test_strict_with_baseline_passes_for_known_production_debt`
  fails — `api/routes/ops.py` deep-imports `juli_backend.services.ops.access` and 5 more
  `services.ops.*` modules (cross-package depth 3 > 2). Fails on base 2190f2de too; check.sh does
  not select it — re-export the used names from `juli_backend.services.ops` (or baseline them) in
  the merge PR.
- [x] (repaid in P53, D62: declared on the check.sh step) Pre-existing, not P29-merge: `tests/unit/test_destructive_migration_isolation.py::test_ci_is_configured_to_declare_its_database_disposable`
  fails — `fasttrack-deploy.yml` sets `DATABASE_URL` but never `JULI_TEST_DATABASE_DISPOSABLE`
  (check.sh exports it itself, so the deploy works). Not selected by check.sh — declare it in the
  workflow env in the merge PR.
- [x] ~~`test_ops_round_trips.py` fleet bounds (costs/terms, 2 round trips per shop) failed when an
  earlier module in the same pytest process left shops in the shared database~~ — repaid: the module
  is on `_SHARED_STATE_MODULES` (own database), so it sees only its two tenants.

## P30 — metric-first trigger and card groups (2026-10-13)

- [ ] D39.1 tests four metrics per product at 1 × combined band, so noise alone opens more
  cards than the GMV gate (Fujiwa-like fixture: 2 cards instead of 1). Watch the first
  metric-first nights on Fujiwa; if too many, raise the trigger to the 2 × "clear" rule for
  metrics other than the GMV-explaining one, or roll a shop back with `diag_trigger = gmv_first`.
- [ ] Group verdicts are computed inside `apply_emission_budget` (the surfacing cadence). A shop
  whose budget stops running (no scoring) gets no day-14 verdict until it runs again; move to a
  nightly task if that matters.
- [ ] Late joiners: a draft of a key that arrives after its group launched is not added; it
  surfaces ungrouped unless 3 such drafts wait together. D34.6 (cross-shop result for small
  shops) and D34.7 (lever-effect table replacing ranking weights) are not built.
- [ ] `card_groups` / `card_group_members` grant juli_app UPDATE without a `GRANT_REQUIRED` call
  site in `tests/unit/test_juli_app_grants_cover_mutations.py` — same as the P8–P24 tables
  already listed for `test_no_public_table_holds_update_beyond_its_call_site` (Postgres only).
- [ ] No Playwright e2e for the Ops group view or the seller "Kết quả nhóm" line (vitest only).

## P31 — shrink before the trigger, stricter group verdict (2026-10-13)

- [x] ~~D41.3 "checked with the v0.3 power simulator first"~~ — done by the owner
  (`p31-power` report): false alarms ≤ 9.6 % in every design; power stays low on small groups
  (a median over ≤ 8 products rarely reaches p ≤ 0.10: 5 + 3 perfectly separated gives p = 6/56).
- [x] ~~Monte-Carlo margin on the 10 % gate~~ — replaced by T3.1: a flat 15 % gate, re-run at
  every measurement with the control's untouched post-launch pairs in the null pool.
- [ ] T3.1 re-gating stops at day 56 and only while the verdict reads "Đang đo"; a group whose
  controls are all approved by day 14 gains no new no-effect pairs and can stay "Đang đo".
  The comparison window stays days 0–13 (the only window the control is guaranteed untouched);
  a 28-day comparison as in the D34 #1 plan (D41.4) is not built.
- [ ] "Untouched" = the control's card not approved (`approved_at`); an external change on the
  product (D30.4) does not stop its pairs from joining the null pool.
- [ ] The false-alarm replay costs ≈ 1–3 s per measured comparison (500 draws × 200 bootstrap
  resamples) inside `apply_emission_budget`; fine for a few groups a night, move to a nightly
  task with more groups.
- [ ] The null data are each product's (days −28..−15, days −14..−1) pair: products with less
  than 7 days in the earlier window fall back to the arm-centred changes. A group launched on a
  newly connected shop gets the weaker fallback.
- [ ] Verdicts stored before P31 keep their 80 % interval and no `false_alarm`; they are not
  re-measured (only "Đang đo" verdicts are re-gated).
- [ ] Shrinkage priors are fit per (category, channel, calendar window) over every product the
  planner sees, gifts and excluded products included; categories are TikTok's leaf names as
  stored (`CatalogProduct.category`), which may be too fine — products with no category use the
  shop-wide prior. Not applied to the `gmv_first` path, Lượt hiển thị or AOV (not binomial).
- [ ] No Playwright e2e for the "Lọc nhiễu CTR / CTOR" row or the false-alarm text (vitest only).

## P32-A — partner reviewer trial account (2026-10-14)

- [ ] Revocation lag: the API caches a reviewer's account row for 15 s per worker
  (`REVIEWER_ACCOUNT_CACHE_SECONDS`); the Supabase ban stops new tokens at once, but an
  already-issued access token keeps working for those ≤ 15 s.
- [ ] The mask is a denylist over the response (entity keys + the shop's catalog + brand
  words + long digit runs + external URLs). A product title that appears only in free text
  and is NOT in `products` (e.g. a video caption quoting a product by a nickname) is only
  covered by the brand-word scrub. Extra words go in `REVIEWER_MASK_TERMS`.
- [ ] Product photos / video covers / any external URL become `null` for the reviewer (they
  identify the shop); the UI shows its empty states. A placeholder image would read better.
- [ ] The simulation shows the card's stored proposal when one exists, else "Juli soạn nội
  dung mới sau khi duyệt" — no model call (D24.1), so the reviewer usually sees the field and
  its current value, not a drafted new title.
- [ ] A reviewer's `users` row is provisioned on first sign-in like any user (one write to
  `users` per account, outside the no-write snapshot by design).
- [ ] The reviewer's run-focus page `/decisions/in-progress/<id>` still opens its own SSE stream
  if visited by URL; the server refuses it (403) and the page shows its error state.
- [ ] Batch "Duyệt N thẻ" is disabled for a reviewer (single-card simulation only).
- [ ] The no-write sweep posts `{}` bodies: a refused route answers 403 before the body is
  read, so it proves the gate, not each handler; a future allowlist entry is caught by
  `test_allowlist_is_pinned_to_real_routes` (only POST allowed is the simulation).
- [ ] Not exercised live: password sign-in against the real Supabase project, the
  provisioning command against production, the mask on real Fujiwa data (no deploy — P32
  integration step).
- [ ] (P53, D62: corpus figures, module_md allowlist and boundaries repaid; the
  prior-figure drift check and the GRANT UPDATE test remain — see P53-A below) Pre-existing guard drift not repaired here (fails at the base too): quality corpus
  6,417 recorded vs ~6,700 live (`test_test_quality`, `test_quality_reconcile`),
  `test_module_md_sync_parser` allowlist, 6 import-boundary deep imports in ops / workers,
  `test_no_public_table_holds_update_beyond_its_call_site`.
- [x] ~~Pre-existing time bomb (not P32):~~ repaid 2026-10-15 (card surfaced now in the test): `test_p10a_card_reasons_edits.py::test_the_decisions_list_carries_the_card_block`
  builds its card with `update_time=datetime(2026, 10, 1)`, so since ~2026-10-08 the card reads
  `expired` instead of `pending`; it fails on `fasttrack/optimize-product` @ 0e80c18b too. Pin the
  clock or build the card relative to now.
- [ ] Flaky isolation seed (pre-existing, seen 2026-10-15 in 1 of 4 `check.sh` runs):
  `test_two_tenant_isolation_proof.py::_seed_tenant_data` builds the user's phone from 4 hex chars
  of the uuid; a collision with another seeded user makes `ON CONFLICT DO NOTHING` skip the user
  and the shop insert then fails on `shops_user_id_fkey`. Use the full uuid in the phone. Can fail
  a deploy run — re-run if it is this test.

## P33-A shortcuts (2026-10-15)

- [ ] Lighthouse target (mobile Perf ≥ 95, LCP < 2.5 s) not demonstrated: local runs were taken
  on a host with load avg 9–18 (parallel agents) and swing 0.40–0.95 — re-run PageSpeed on the
  deployed site (AC-33.9) and record it.
- [ ] Residual PageSpeed flags that config cannot remove: "legacy JavaScript" = Next's built-in
  `polyfill-module` (1.4 KB, `next/dist/client/app-globals.js`; browserslist is already modern),
  "unused JavaScript" ≈ react-dom/Next runtime. Revisit only if a Next upgrade exposes a switch.
- [ ] `experimental.inlineCss` tried and rejected (FCP −0.6 s but TBT ×3: CSS duplicated into
  the RSC payload). Re-measure on a quiet host or after a Next upgrade.
- [ ] Images are pre-generated by `apps/landing/scripts/media.py` (Pillow ≥ 11.2, macOS Arial
  font path for the OG card) instead of `next/image`, so the VPS artifact needs no `sharp`. The
  script is not run in CI; `brand` rewrites the `-v1` files in place — bump names before
  regenerating.
- [x] (repaid by P33-B 512c3993: `<Picture>` poster with srcset 640/1280 + click-to-load `HeroVideo`, VideoObject on `/`) Hero `<video>` still renders with `controls` and a 1280 px WebP poster on mobile (D43.6
  poster + click-to-load + VideoObject is P33-B's; helpers `HERO_VIDEO`, `HERO_VIDEO_SCHEMA`,
  `<Picture>` are ready).
- [ ] `/product/` (trailing slash) goes 308 → `/product` → 301 → `/san-pham` (two hops). Nothing
  links it; add an explicit rule if Search Console shows it.
- [ ] Demo vitest under heavy host load: `no-shop-sample.test.tsx` and a few others time out /
  race (2 files failed in one full run, passed 3/3 in isolation and on the base) — not caused by
  P33-A, watch in CI.
- [ ] `@juli/brand` `JuliLogo` still renders the 50 KB PNG with `width: auto` and no
  width/height attributes (the demo uses it); the landing switched to `SiteLogo`.

## P33-B shortcuts (2026-10-15)

- [x] (owner, D43 additions 1: video stays, caption is enough) The sales demo video itself still shows unsourced figures ("+5–10%", "+1–3% GMV mỗi
  tháng", "29 giờ") and a run where Juli applies "Giảm giá sản phẩm 30 ngày" (contradicts D13 /
  D24.5: promotions are the seller's). The page labels it "Số liệu trong video là minh hoạ";
  owner decides: re-cut the video (juli-content-engine `sales-demo-02`) or drop it from the hero.
- [x] (owner, D43 additions 3: no disconnect button; copy now says contact Juli, the team
  disconnects) No seller-facing "Ngắt kết nối" in the app.
- [x] (owner, D43 additions 4: keep them) Old `public/media/juli-demo-poster-v1-*` files are
  unreferenced but kept.
- [ ] Homepage / `/san-pham` link `/san-pham/phan-tich-shop`, `/san-pham/de-xuat-va-thuc-thi`,
  `/san-pham/do-luong-gmv`, `/ket-noi/tiktok-shop`, `/blog`, which 404 on this branch alone;
  they exist only after P33-C / P33-D integrate. Integration must not ship B without C and D.
- [ ] Lighthouse not re-run for the new homepage (host loaded by parallel agents); AC-33.9 runs
  PageSpeed after deploy. The poster `<img>` (priority, 640/1280 srcset, 7–15 KB AVIF) should be
  the LCP element.
- [ ] Commit 2f16f2eb alone fails `sections.test.tsx` (old poster path pinned); green from
  512c3993. Squash-irrelevant, noted for bisects.
- [ ] Every "Dùng thử miễn phí 3 tháng" CTA links `/dang-ky` (P33-F's page), which 404s on this
  branch alone; `check:seo` does not check links, so nothing was allow-listed. Integrate with P33-F.
- [ ] Trial CTA clicks to `/dang-ky` reuse the custom `StartDemo` Pixel event (content_name =
  the CTA's testid) for continuity; a dedicated event for the form submit is P33-F's.
- [ ] Demo vitest under host load avg ~35: `quyet-dinh-p10` and `ops-pages` (3 tests) failed in the
  full run, passed 70/70 together with `demo-landing` alone — the known load flake, not P33-B.

## P33-C shortcuts (2026-10-15)
- [ ] `/blog` is linked from all four capability pages (`BLOG_PATH` in
  `apps/landing/src/components/product/capability-page.tsx`) and 404s until P33-D's `/blog` merges.
  If P33-D ships a different path, change the constant.
- [ ] **Owner check before deploy**: the pages describe Juli writing title / description (and the
  cover with the seller's photo) to the seller's shop after Duyệt + xác nhận, as `/privacy` does.
  In code, agent writes still resolve to the sandbox merchant (`factories.py`, DEBT above, P5 not
  started), so confirm real-shop writes are live (or accept the wording as the product's flow)
  before publishing. Attributes are deliberately NOT claimed (`update_product_listing` writes
  title / description / main_images only).
- [ ] Seller self-serve disconnect: the copy says "thu hồi uỷ quyền trong TikTok Shop hoặc email
  lienhe@app-juli.com"; there is no seller-side button in the app (only Ops "Huỷ kết nối").
- [ ] Screenshots are crops of the demo sample at a fixed date (cards dated 15/10/2026); the
  connect and onboarding shots render real components over a mocked `/v1/shops` and
  `/v1/shops/me/onboarding` (fictional "Shop Mỹ Phẩm Ví Dụ", chushop@vi-du.vn). Re-shoot (`-v2`)
  when the app UI changes; the capture scripts were ad hoc (scratch Playwright), not committed.
- [ ] The FAQ H2 on each page has no screenshot (AC-33.7 "one per H2" read as per content H2).
- [ ] Measurement page explains delayed-control groups as "đang thử nghiệm" (opt-in per shop,
  default off); update the wording when groups become default.
## P33-D shortcuts (2026-10-15)
- [ ] **Owner approval of the three posts is pending** (AC-33.8): they deploy as noindex drafts.
  Flip `status` in `apps/landing/src/content/blog/posts.ts` per post and record it.
- [ ] Post 3 (tools) vendor facts came from WebFetch summaries of vendor homepages (2026-10-15);
  re-read by hand before publishing: BigSeller paid tiers (not found), KiotViet "TikTok" in the
  channel list (site says "TikTok", not "TikTok Shop"), Sapo / Haravan / FastMoss / Kalodata trial
  lengths (7 / 14 / 7 / 7 days), FastMoss and Kalodata Vietnam coverage (not stated on the pages
  read). Juli's own claims to confirm with the owner: "Juli không in vận đơn / không quản lý kho
  đa sàn", "hiện chỉ kết nối TikTok Shop".
- [ ] `blog.test.tsx` allow-lists P33-C's four pages (`PENDING_PAGES`) because they do not exist
  on this branch; remove the allow-list at integration so every post link must resolve.
- [ ] No per-post OG image or in-article images (posts use the default 1200×630 card; no
  `public/media/blog-*`). Add a cover per post when the owner publishes.
- [ ] "3,000+ words" counts space-separated tokens (Vietnamese syllables), the same way Word and
  most SEO tools count Vietnamese text.
- [ ] Blog drafts are linked from nowhere in production, but their URLs are guessable and render
  (noindex). If the owner wants them unreachable before approval, gate them with a 404 in
  production instead (would also drop them from `check:seo`).
## P33-F shortcuts (2026-10-15)
- [ ] No retention job for `trial_signups`: the privacy text promises deletion after 12 months for
  prospects who never became customers and within 30 days on request. Today deletion is manual
  (`DELETE FROM trial_signups WHERE …` as `juli_ops`, or an Admin action that does not exist yet).
  Add a nightly purge (like `ops-audit-retention`) and an Ops "Xoá" button.
- [ ] `TRIAL_SIGNUP_IP_SALT` falls back to a fixed in-code constant when unset, so the IP hash is
  only as private as that constant (an IPv4 HMAC with a known key is brute-forceable). Set the env
  in production; then make it required.
- [ ] Without `TRIAL_SIGNUP_RELAY_KEY` on both the API and the landing, the per-IP limit counts the
  landing server's address for every visitor (5 sign-ups / hour site-wide). Set it before launch.
- [ ] The landing calls `https://api.app-juli.com` through Cloudflare server-to-server
  (`TRIAL_SIGNUP_API_URL` overrides). If a Cloudflare bot rule ever challenges it, the form answers
  "Chưa gửi được"; a loopback URL is not usable today because the API lane alternates 8000/8020.
- [ ] The team e-mail is sent after the response (FastAPI background task) through the ops SMTP
  mailer; a crash between commit and send loses the mail but not the row (the Ops tab still lists
  it). No retry.
- [ ] The trial itself is not tracked (who is in a 3-month trial, when it ends) — D43 additions
  P33-B §2 says no trial tracking or billing is built; "Đã kết nối shop" on a sign-up is set by hand.
- [ ] The no-JS fallback shows a generic "Thông tin chưa đúng" notice (`/dang-ky#loi-du-lieu`)
  without per-field messages; browsers' own constraint validation catches nearly all of it first.
- [ ] Load-sensitive demo test (seen 2026-10-15, P33 integration): `connect-shop-page.test.tsx >
  renders the connect-shop screen for a real signed-in session` failed once in the full demo run
  (1917 / 1918) on a loaded host and passes 3 / 3 alone — same family as the P33-A/B timeouts.
- [ ] P32-D (reviewer on the sample shop): no Playwright e2e for the `shop: null` reviewer — the
  existing `apps/demo/e2e/auth/reviewer-sign-in.spec.ts` covers the Fujiwa-pin mode only. Sample mode
  is covered in vitest through the real `DemoShell` (`reviewer-sample-mode.test.tsx`: banner, no
  connect strip, simulated Duyệt → Thực thi, the only request is `GET /v1/reviewer/me`). The
  in-browser sample simulation (`lib/reviewer/sample-simulation.ts`) is a hand port of
  `services/reviewer/simulation.py`; a change to one must be mirrored in the other.
- [ ] P32-E (all features simulated in sample mode): the reviewer's sample store is module state —
  a full page reload (not client-side navigation) starts the sample over, as does sign-out; not
  persisted to browser storage on purpose (nothing to clean, nothing stale). Still no Playwright
  e2e for sample mode (see P32-D above); coverage is the vitest full-session test
  `reviewer-all-features.test.tsx` through the real shell. The day-7 / day-14 "tua nhanh" values are
  invented from the card's own target (`sampleSimulatedMeasurement`), always "Đạt" — not a model of
  a real outcome. `/decisions/in-progress/<run id>` and `/decisions/recommendations/<id>` are not
  reviewer-sample-aware (sample run ids never route there).
- [ ] Load-sensitive demo test (seen 2026-10-15, P32-E gates): `ops-pages.test.tsx > saves the
  scenario and sets it as the shop target` timed out once (5.6 s) in a full demo run (1925 / 1926)
  and passes 3 / 3 alone; the previous full run on the same code was 1926 / 1926. Untouched by P32-E.
- [ ] P34-A (UI foundation): mobile crops of the `cap-*` screenshots are cut from the published
  1280 WebP (the original PNG captures are not in the repo), so they are re-encoded from a lossy
  source; crop boxes are fractions in `MOBILE_CROPS` (`scripts/media.py`), eyeballed once at 390.
  Re-capture the six large-text shots or any crop at native mobile size if a page needs sharper text.
- [ ] P34-A: all four font weights are preloaded (~123 KB woff2); `next/font/local` cannot preload a
  subset of one family's files. Re-measure LCP in AC-34.7; if needed drop 500 or 700 (700 is used only
  by the "Juli AI" wordmark) or set `preload: false`.
- [ ] P34-A: `TocNav` active state is static (`activeId` prop), no scroll-spy; the TOC renders its
  link list twice (desktop list + mobile `<details>`), one hidden by CSS.
- [ ] P34-A: `ui.css` sets body to 17 px / 1.65 site-wide; old `lp-*` page sections (until B–E
  redesign them) inherit it, so some legacy blocks render slightly larger than before.
- [ ] P34-B (homepage): `cap-dx-the` (hero card + "Đề xuất và thực thi" row) has no mobile crop, so
  at 390 px it shows the whole card scaled to ~322 px wide (legible, small). A native mobile capture
  (`MOBILE_CROPS` in `scripts/media.py` + `*_MOBILE` in `components/product/screens.ts`, P34-A/C files)
  would match HomeMobile's "ảnh cắt riêng cho mobile" caption better.
- [ ] P34-B: the homepage now states the price as "500.000đ/tháng" (hero note, dark band card, FAQ),
  as the approved mockup and /terms §5 do; D43.2 had said "từ 500K". `cta.test.tsx` was changed on
  purpose (no "500K", price card present). Owner to confirm the wording at integration.
- [ ] P34-B: `trial-signup-cta` (old final CTA) and the hero "Xem demo" button are gone: the mockup
  merges pricing + final CTA into one dark band (`pricing-trial-cta` "Đăng ký dùng thử",
  `trial-demo-cta` "Xem demo với dữ liệu mẫu"); `hero-demo-cta` is now the "Xem demo" link in the
  hero note. TikTok reports lose the `trial-signup-cta` content_name from deploy on (6 tracked CTAs
  on `/`, was 7).
- [ ] P34-B: `globals.css` still holds the `lp-home-*` rules `/san-pham` uses (hero, section, grid,
  card, steps, final, link, list, price); remove them when P34-C's redesign drops those classes.
- [ ] P34-B: the hero product shot is the approved mockup's `cap-dx-the` image, which shows sample
  figures ("+2,1 tr đ/tháng", "▲9,3 %") inside the screenshot; captioned "Dữ liệu mẫu" (D44.3), but
  it is an image, so the page's "no % in text" test does not see it.
- [ ] P34-C (product pages): `.ui-card > p` (ui.css) overrides `Eyebrow` (a `<p>`) inside a `Card` —
  it renders grey 15 px. `/san-pham` works around it in `overview.module.css`; fix in `ui.css`
  (e.g. `.ui-card > p:not(.ui-eyebrow)`) — P34-A owns it.
- [ ] P34-C: `FunnelDiagram` wraps awkwardly at 390 px (the `=` and the dark GMV box drop to their
  own rows); a vertical layout ≤ 640 px in `ui.css` would read better. Shared component, not changed.
- [ ] P34-C: the TOC (`.ui-toc` sticky) and the sticky header disappear / repeat in Playwright
  full-page captures; the evidence script forces them `position: static` (evidence only, not shipped).
- [ ] P34-C: `globals.css` `.lp-breadcrumb` is now unused (it was only `/san-pham`); `.lp-page-faq`,
  `lp-home-*` stay used by the homepage until P34-B lands. Remove dead `lp-*` rules at integration.
- [ ] P34-C: capability hero shots reuse section screenshots (Phân tích hero = the luồng + phễu
  shots, as in the mockup; Đo lường = mục tiêu + tăng thêm), so those images appear twice on the page.
  A dedicated wide hero capture per page would avoid the repeat.
- [ ] P34-D (blog): all three posts are drafts, so production `/blog` shows only the H1 and the
  "đang được biên tập" empty state (no pills, no cards) until the owner publishes one; the mockup
  look is visible under `pnpm dev`. The mockup's dashed "Bài tiếp theo · 2 bài mỗi tháng" card and
  the "Mẫu ảnh bìa" spec band were not built (a cadence promise / a design note, not page content);
  the old "Juli AI làm gì cho shop của bạn" product-links list on `/blog` was dropped.
- [ ] P34-D: topic pills filter client-side (toggle buttons + CSS on `data-filter`); no per-topic
  URL (`/blog/chu-de/…` would need new registry routes in `lib/seo`) — add when there are enough
  posts to be worth indexing per topic. Without JS all posts show and the pills do nothing.
- [ ] P34-D: shared-file notes for the orchestrator — `components/ui/README.md` Blog recipe should
  point at `components/blog/post-card.tsx` / `category-filter.tsx` and `content/blog/README.md`
  ("Topic and cover"); the post page still uses `.lp-blog__h2` (blog.css) rather than a `Heading`
  size for in-body H2s (24→30 px, smaller than `article` 24→34, chosen for the 720 px column).
- [ ] P34-D: the cover generator encodes AVIF/WebP through `media.py optimize` (needs Pillow with
  AVIF: `PYTHON=juli/.venv/bin/python`); the "Hướng dẫn" (guide) motif (checklist) is my design —
  the mockup shows only its grey tint — and its accent token is ink, so the ticked box is black.
- [ ] P34-E: `SiteHeader variant="signup"` wraps at 390 px ("Juli / AI" and "Đã có tài khoản? /
  Đăng nhập" on two lines each, see `evidence/p34e/dang-ky-390-top.webp`). Shared component
  (`components/ui/site-header`), not P34-E's to edit: shorten to "Đăng nhập" below 640 px or
  `white-space: nowrap` the brand.
- [ ] P34-E: the legal template lives in `app/privacy/legal-template.tsx` (+ `legal.module.css`)
  and /terms imports it from there, because P34-E owns only the page folders. Move it to
  `components/legal/` when convenient.
- [ ] P34-E: `globals.css` keeps `.lp-legal__contact-link` (still used by `/ket-noi/tiktok-shop`
  and `components/product/capability-page.tsx`, P34-C) and all `lp-page-*` rules (used by
  `/san-pham`, `/ket-noi`, `/blog`, `not-found`, home). Delete them once B–D no longer use them.
- [ ] P34-E: `Icon` has no map-pin / building icon, so /contact's address card uses
  `shield-check`. Add a `map-pin` to `components/ui/icon.tsx` (P34-A owner) and swap it in.
- [ ] P34-E: the `/dang-ky` aside uses the mobile crop `cap-kn-ket-noi-m-v1-627` at every width
  (the 1280×341 desktop strip is unreadable in a ~460 px panel); on phones its text is small.
  A purpose-made crop of the connect card would read better.
- [ ] P34-F (demo auth screen, D44.5): the OTP view cannot say "Còn N lần thử" or tell a wrong code
  from an expired one — GoTrue answers both with `otp_expired` (403) and exposes no attempt count, so
  one message ("Mã không đúng hoặc đã hết hạn…") carries "Gửi mã mới" once the 60 s resend floor
  passes. The mockup's "Mã có hiệu lực trong 10 phút" is left out: the project's OTP expiry is not
  pinned in the repo.
- [ ] P34-F: Be Vietnam Pro on the auth screen comes from the demo root layout's existing
  `next/font/google` variable (latin + vietnamese, `display: swap`, no `adjustFontFallback`, set up for
  Quyết định); P34-A had not chosen the landing's loading approach when P34-F finished. If the landing
  self-hosts or changes weights/fallback metrics, align the demo in P34 integration.
- [ ] P34-F: input / outline-button borders are `#8b8b94`, darker than the mockup's `#cfcfd6`, to
  reach 3:1 non-text contrast (WCAG 1.4.11). Owner may prefer the lighter mockup value.
- [ ] P34-F: `/` now renders bare (no shell) while the session and the sample-entry choice resolve,
  so a signed-in seller or a returning sample visitor sees a blank "Đang tải…" for one tick before
  the shell appears (previously the shell framed it). The auth screen itself never flashes the shell.
- [ ] P34-F: from `/`, "Tài khoản đối tác" is a full navigation to `/auth/email#doi-tac` (same layout,
  partner view) rather than an in-page swap: the partner form calls `GET /v1/reviewer/me`, and the
  landing's module graph must stay free of `/v1/*` (`replay-module-graph.test.ts`). On `/auth/email`
  the swap is in place.
- [ ] Pre-existing, seen during P34-F (not caused by it — no diff under ops): `e2e/ops/ops.spec.ts`
  fails 1 test on desktop and 4 on mobile against a local build. "Chẩn đoán & KPI" expects 6
  `ops-setting` rows and gets 8 (the spec is stale against the code), and three mobile tests time
  out at 1.5 min.

- [ ] P36 (D45.6): a card-drawn group's client-facing verdict keeps the P31 rule (one fitted θ);
  the D45.6 group-size rule is only stored beside it (`verdict.ops_rule`) and shown in Ops. Switching
  card groups to D45.6 changes the seller's "Kết quả nhóm" sentence, so it waits for the owner.
- [ ] P36: the v0.3 power check (`juli-sim-pilot/v03/power_p31.py`) simulates CTR only and has no
  days −42..−29 window, so for ≥ 15 products the simulated false-alarm replay runs the one-window θ
  while the verdict runs two windows (the backend's replay uses triples when the data has them).
  CTOR / AOV power is not simulated; the research run `20261015-212942` §4a is the only estimate.
- [ ] P36 (D45.4): traffic needed for AOV assumes an order-value CV of 0.6 (research assumption;
  daily totals have no per-order values); items per order has no traffic formula.
- [ ] P36: `e2e/ops/ops.spec.ts` "Chẩn đoán & KPI" row count (already stale, see P34-F) grows by the
  three group tunables (`group_two_window_min`, `group_guard_ctr_drop`, `group_drift_sigma`).
- [x] P37 (owner): D47.2 says a failed / cancelled / timed-out run puts the card back to "Chờ duyệt";
  the sample does that. The real backend only does it for `failed`
  (`services/agent/runner/conversation_store.py` ~381, `workers/tasks/agent_workflow.py` ~932);
  `cancelled` (e.g. `confirmation_expired`) and `timed_out` (`external_wait_expired`) leave the card
  `approved`, so `card_view._status` would show "Đang thực hiện" for good. Decide whether the
  backend should reactivate on those two as well.
  **Closed by D47.5 / P38** (branch `fasttrack/run-reactivate`): one helper,
  `services/agent/card_reactivation.py`, for all three statuses.
- [ ] P37 (owner): content cards ("Juli soạn · bạn làm") record no listing write, so after "Tôi đã
  đăng" the sample card stays "Đang thực hiện" — the same as the real `_status` (P14-E sample used to
  say "Đã áp dụng"). If content should read "Đã áp dụng", change `_status` and the sample together.
- [ ] P37: the real `GET /v1/demo/decisions` lists only `active` cards, so a decided card leaves the
  real Đề xuất on the next load; the sample Quyết định keeps every card with its chip (what the real
  screen shows in-session through its local overrides). Phân tích's sample uses the desk list.
- [ ] P37: `advanceTime` / `failRun` are store seams (tests); no UI exposes them. A reviewer "tua
  nhanh 7 ngày" on Đề xuất (or a seeded failing card) would let a partner see expiry / failure.
- [ ] P37: `fasttrack/shopee-isv-services-information.md` step 1 says to choose "Tài khoản đối tác
  (đăng nhập bằng mật khẩu)"; the auth screen's footer link reads only "Tài khoản đối tác". Giving
  the direct URL `https://demo.app-juli.com/auth/email#doi-tac` would be clearer for the reviewer.
- [ ] P38 (D47.5): a run Ops cancels by disconnecting the shop (`ops/disconnect.py` sets
  `cancel_requested`) also puts its card back to `active` when it ends `cancelled`; the shop is
  inactive, so nothing shows it, and a reconnect would see the card "Chờ duyệt" again.
- [ ] P38 (D47.5): the reactivation writes a structured log line
  (`action_card_reactivated_after_run`), not a card-event row — there is no card event log on this
  branch (the `docs/card-event-log` grill is separate). Same as the failed path before.

- [ ] P39 (D48.5): "ROI và ngân sách GMV Max" has no page copy by design (Juli runs no ads); it is
  owed as a blog post later, owner-approved like the other drafts.
- [ ] P39: the `/san-pham` title had to fit 60 characters with the " | Juli AI" suffix, so it reads
  "Phần mềm AI phân tích, vận hành TMĐT TikTok Shop" (no "và", no "cho nhà bán"); the meta
  description carries the full "phân tích và vận hành cho nhà bán TMĐT". Owner may prefer another
  ≤ 50-character wording.
- [ ] P41: legacy pre-P10 routes `/decisions/recommendations/*`, `/decisions/in-progress/*` and
  `/settings/workflows/*` (`lib/workflows/*`, `lib/recommendations.ts`) still word steps with API
  identifiers (`activity_id`, `category_id`, `package_id`, "no-op", "Ship by Seller — gửi
  self_shipment"). No current screen links to them; a seller reaches them only by typing the URL.
  Remove the routes or reword them if they come back.
- [ ] P41: the sample LIVE card says "Trần giảm giá 10 % · biên tối thiểu 30 %" and the Seller
  Center summary "≥ 30 % bạn đặt · trần giảm 10 % bạn đặt", while the sample rules hold
  `default_max_discount_pct` 15 and no `min_margin_pct`. Align the sample rules or the canned text.
- [ ] P41: the simulate response (`POST /v1/reviewer/decisions/{id}/simulate`, contract p32 §4) still
  carries `request` (method, path, operation); the dialog no longer shows it. Drop it from the
  contract if nothing else reads it.
- [ ] P43: `/cong-cu/tinh-gmv` links the "GMV là gì" post (and its four "Tăng …" sections) only once
  the post is published (`components/gmv-calculator/post-href.ts`); while it is a draft the title shows
  as plain text, because an indexable page never links a noindex draft (check:seo). Nothing to do on
  publish, but re-run `check:seo` then. There is no `/cong-cu` index page (breadcrumb is Trang chủ →
  Công cụ tính GMV); add one if a second tool ships.
- [ ] P43: the calculator reads one period only, so it cannot name a weakest step from data. A
  "so với kỳ trước" mode (two periods, log split of the GMV change as in the post's Bước 2) would make
  that honest; not built (scope of D49.1).
- [ ] P45 (D52): the EB SE comes from the verdict's 90 % bootstrap interval of the difference of
  medians, which D41 found too optimistic for 2–5 products; a too-small SE makes the shrunk lift
  stay close to the raw one for exactly the small groups the guard is for. Revisit with the first
  real D34 groups (e.g. a permutation-based SE, or a floor from `group_design.drift_floor`).
- [ ] P45 (D52): the stored `eb` always uses the default prior (the measuring pipeline runs in the
  shop's tenant scope and cannot read other shops); the pooled prior is recomputed at read time on
  the Ops groups page and is not stored. If a stored pooled value is wanted (e.g. for an audit
  trail), add an Ops-run job that writes it under `juli_ops`.
- [ ] P45 (D52): draws pool card groups (P31 rule) and Ops groups (D45.6 rule) of the same lever
  × metric × channel alike; `group_eb_min_groups` / `group_eb_prior_sd` are read from the shop being
  viewed, so two shops can show different priors for the same lever type.
- [ ] P47 (D55.1): the order-line store keys `order_items` by (order, SKU), so TikTok's per-unit
  lines of one SKU collapse into one row (quantity 1, one unit's value). Net values therefore use
  only *shares* (removed ÷ placed per product-day) applied to the analytics numbers, never order
  sums; the shares are biased only if multi-unit orders are cancelled / refunded at a different
  rate. Fix the store key (or sum lines before the upsert) before order sums are used anywhere.
- [ ] P47: a refund counts when `silver.returns.status` contains COMPLETE / SUCCESS and the type is
  not an exchange (`item_swap`); `derive_return_type` folds REFUND_ONLY / RETURN_AND_REFUND into
  `other`. Status strings are TikTok's as stored and were not checked against a live read in P47.
- [ ] P47: the poll cycle syncs orders and returns but not cancellations (`sync_cancellations` runs
  only in Shared Compute targeted fetch); a whole cancelled order is seen through
  `silver.orders.status`, but one SKU cancelled inside an order that is not cancelled is missed.
- [ ] P47: refunds land after the order; at day 14 the after-window's late refunds are not in yet,
  so its net values can still fall a little (both arms alike). A re-check (T3.1) picks them up.
- [ ] P47: order coverage for Fujiwa was not checked (no live read): if the shop's orders do not
  reach back to day −42 of a group, its verdict stays on TikTok's GMV and Ops says so.
- [ ] P47: the EB pooled prior mixes a card group's primary AOV (TikTok GMV, it stays gross for the
  seller) with net AOV of Ops groups / `metrics` of the same lever type
  (`ops_group_lift_draws()` reads `primary` and `metrics.*.primary`); a new migration would be
  needed to read `net` instead.
- [ ] P47: only the group verdicts and their plan line use net values. Other Ops screens (Tổng
  quan "GMV 30 ngày", Mô phỏng GMV/ngày, Chẩn đoán) still show TikTok's GMV without the "gồm đơn
  huỷ/hoàn" note; the chi-số guide §5.5 and glossary say it. Label them if the owner wants.
- [ ] P47: TikTok's analytics carry refund numbers the mapper drops (A-34
  `total_performance.refunds`, A-33 `intervals[].cancel_and_refunds`, both "documented" in
  `schema_expectations.py`, unverified live). Storing them (mapper + migration) would give per-day
  refunds on the same rows, and could check the order-based shares.

- **Trial sign-up purge job (D60.4, D43 additions 3)**: sign-ups that do not become customers must
  be deleted after 12 months; no job exists yet. Due before 10/2027 (first sign-ups 10/2026). Another session's branch `fasttrack/p50b-privacy-api` adds a Postgres purge; check whether it covers `trial_signups` before building one.

## P53-C2 — legacy routes removed (2026-10-18)

- [ ] `lib/workflows/*` (11 folders), `lib/reviews.ts`, `lib/plan-reviews.ts`, `lib/executions.ts`,
  `lib/recommendations.ts` stay: `components/demo-state.tsx` still imports them (mock execution
  records, replenish payloads). Phase 2: cut demo-state's dependency, then delete them.
- [ ] `RepeatConsentBlock` (`components/repeat-consent-block.tsx`) is mounted nowhere now (its only
  hosts were the in-progress detail view and `InProgressPanel`); kept with `lib/repeat-consent.ts`
  because consent code is TOO-RISKY. Its rendered tests went with the hosts; the pure eligibility /
  gate tests stay. Owner: delete or re-host.
- [ ] `globals.css` still carries rules for removed components (`.option-picker*`, `.run-*`,
  `.app-shell--run`, `.app-content--run`, `.demo-plan*`, `.demo-review*`, `.repeat-consent*` …) and
  imports `@juli/theme/run-surface-tokens.css`; nothing in the demo sets `data-juli-surface="run"`
  any more. Prune with a CSS-coverage pass (TOP 15 #10 css part).
- [ ] `packages/ui` `RecommendationCard` has no app consumer now (only its own test).
- [ ] Still-orphan demo files not touched here (no closure dependency, audit TOP 15 #4–#6):
  `decision-evidence-block.tsx`, `lib/decision-evidence.ts`, `home-activity-tracker.tsx`,
  `impact-reading-figure.tsx`, `lib/impact-provenance.ts`, `lib/shop-analysis/sample-*.json`.
- [ ] Pre-existing, not from P53: `e2e/exit-gate/responsive-parity.spec.ts:69` expects the rail
  wordmark link "Juli — Trang chủ"; 5e981b18 renamed it to "Juli: Trang chủ" (em-dash sweep), so the
  test fails on desktop and mobile-web. One-line spec fix.
- [ ] `agent-runtime/config/slice-routing.yml` (lines 915, 1724) still lists the deleted
  `e2e/exit-gate/decisions-journey.spec.ts` under `loadWhenNeeded` (harmless hint, no test reads it).

## P53-A cleanup (2026-10-18, D62)

- [ ] **P23 nightly product-history fan-out turns on in production with this merge** (owner
  approved, D62). Before it, `workers/tasks/__init__.py` never imported `product_history`, so a
  fresh worker registered none of its six tasks: the 20:53 UTC beat, the webhook re-reads
  (types 15/16/18 → Get Product, 63/39 → Get Activity) and the approval baseline capture were all
  answered "Received unregistered task" and dropped (Celery rejects them; nothing queues up).
  Scope and volume once deployed: one `product_history_daily` per shop returned by
  `enumerate_pollable_shops` (active, a usable read credential, not the sandbox auth) **and** past
  its fast phase; one at a time per shop (Redis lock, 1,500 s budget). Per shop per night: Search
  Products at 100 per page, up to 150 Get Product (600 on the shop's first run, its baseline),
  Search Activities × 4 statuses, up to 100 Get Activity (400 on the first run, the backfill).
  Every read takes a token from the poll's shared Redis window (8 of the poll's 10 per minute,
  same key: app key, shop, endpoint path) and waits rather than skips; 429s back off. Get
  Product / Get Activity paths carry the id, so their windows are per product / activity: the
  per-shop cap on them is the 150/600 and 100/400 budgets, not the window. The webhook tasks
  are `rate_limit="30/m"` per worker. Watch after the first deploy: the first night is every
  shop's baseline (up to ~1,000 detail reads per shop), TikTok 429 counts in the worker log,
  `product_history_*_failed` lines, and that `celery inspect registered` lists
  `juli_backend.product_history_fanout`. Webhook deliveries dropped before the deploy can be
  replayed with `celery call juli_backend.product_history_replay_webhooks`.
- [ ] The deferred/074 tail is still pinned to `093_ops_group_lift_draws` in 7 more tests
  (`test_users_phone_placeholder_cleanup`, `test_lever_flows_wiring`, `test_order_costs`,
  `test_ops_d28_terms`, `test_ingest_gateway`, `test_p23_product_history`, `test_ops_d27`); only
  `test_trial_signups` reads the head from the tree. P50-B re-pins them to 094; make them read
  the head the same way (one helper) after P50 merges.
- [x] ~~`test_test_quality::test_reconciliation_reproduces_from_the_tree_it_describes` stays red:
  the `and_no_mock_assert_called` layer reads 115 against the prior ~97, a drift of 18 above the
  #1682 tolerance of 15. The 9 new tests are `tests/integration/test_ops_round_trips.py`'s
  round-trip tests, which assert through the same-file `_check` helper that layer does not
  credit (the headline, 49, is unchanged). Owner: raise `PRIOR_FIGURE_LAYER_DRIFT` with that
  reason, or retire the #1682 claim; not done here because it loosens a check.~~ Repaid P55 (D64):
  the claim is evaluated over a recorded fixed set (`eval/quality_prior_figure_set.json`),
  reads 106 (drift 9 ≤ 15, tolerance unchanged).
- [ ] `python -m eval.ratchets check` (pr.yml) still fails on 284 `unused_ts_exports` identities
  (apps/landing, apps/connector, apps/demo: fast-track UI work) and 1 `broken_doc_refs`
  (`apps/landing/src/content/blog/README.md` → `/path`). `test_ratchets` passes (it checks
  suppressions only; the 7 new suppressions were removed, not baselined). Ratifying the TS
  exports needs `measure --write`, which the ratchet forbids; delete or use them, then `tighten`.
- [ ] B4 partly blocked: `apps/dashboard/package-lock.json` is the pr.yml `frontend` job's
  `npm ci` lockfile (and pinned by `test_issue_397_demo_workspace_contract`,
  `test_phase_2_5_workspace_tooling`); root `done.md` is read by the blocking `check_done_md`
  gate in pr.yml (`agent-runtime/scripts/validate/check_done_md.py` exists — the audit looked in
  `scripts/validate/`). Delete the lockfile with the dashboard (C1) and `done.md` when the
  pr.yml validate gates are retired.
- [ ] DECISIONS has two **D59** entries (blog tiers, 2026-10-18; Gate C, 2026-10-18). Renumber
  one (and its references) in a docs pass.
  P55 left it: 75 `D59` references across `fasttrack/*.md` and the apps mix the two, so it is
  not a trivially safe rename.
- [ ] `tests/unit/test_fujiwa_poll_beat.py`, `test_worker_impact_reader_schedule.py`,
  `test_workflow_run_reaper.py` and `test_shop_diagnosis_daily.py` still read
  `celery_app.tasks` in-process, so they can pass on another module's import. Only the beat
  test moved to a fresh interpreter.


## P53-C1 — apps/dashboard deleted (2026-10-18)

- [ ] `juli-web` on the VPS is not retired, only its source is gone. Still in the repo and
  untouched on purpose (they run on the live VPS): `infra/systemd/juli-web.service`
  (`WorkingDirectory=…/apps/dashboard`), `infra/scripts/env/web.env.example`,
  `fetch-secrets.sh` (writes `/etc/juli/web.env` from `juli/web/production`),
  `refresh-secrets.sh` (restarts `juli-web` when web.env changes), and
  `rollback-release.sh` (restarts `juli-web` and waits for `127.0.0.1:3000` — so
  `rollback.yml` likely fails its health check since #842 unless something still answers
  on :3000). Repay: owner checks on the VPS `systemctl is-enabled juli-web; systemctl
  is-active juli-web; curl -sI 127.0.0.1:3000`, then one change drops `juli-web` from those
  three scripts, deletes the unit + `web.env.example` + the AWS secret, and updates
  `tests/unit/test_phase_2_5_deploy_config.py` / `test_demo_runtime_packaging.py` (they still
  read the unit file).
- [ ] GitHub branch protection may list the old `frontend` check as required; the job no longer
  exists, so a required `frontend` context would block every merge. Repay: owner removes it in
  Settings → Branches (status-check is the aggregate gate).
- [ ] `.github/dependabot.yml` npm entry for `/apps/dashboard` removed here, but Dependabot reads
  its config from `main` (frozen), so dashboard PRs keep coming until this merges to `main`.
- [ ] `scripts/capture-ui-screenshots.mjs` + root `screenshots*` scripts + `screenshots/` still
  target the old dashboard (localhost:3000) — left for audit item C7.
- [ ] Historical docs still name `apps/dashboard` (ADRs, `docs/product/**`, `docs/handoffs/**`,
  `agent-runtime/artifacts/**`, `agent-runtime/config/slice-routing.yml` /
  `slices/**`, `tests/fixtures/mmu9`, `eval/**` datasets and the ratchet baseline's
  `unused_ts_exports` rows). Records, not instructions; left as-is. The runbooks that
  describe the dashboard deploy carry a HISTORICAL banner. Ratchet check: no new violations
  vs 1f7dfe64 (the 11 new broken doc links were fixed).
- [ ] `apps/demo/next.config.ts` comment still says "matches juli-web / App Review" — left so
  `apps/demo` stays byte-identical in this change.

## P55 — deploy gates (2026-10-19, D64)

- [ ] `packages/theme` tests are not in the `frontend` deploy gate: 2 of 79 are stale against the
  fast-track demo (`run-surface-tokens.test.ts` reads the deleted
  `apps/demo/src/lib/run-surface/tokens.ts`, and the dark-palette sweep finds `#121214` in
  `apps/demo/src/app/auth-screen.css`). Repay: owner decides whether ADR-102's run-surface /
  no-dark-palette contract still holds for the fast-track demo; update the tests (or the CSS),
  then add `pnpm --filter @juli/theme test` back to the job.
- [ ] Demo vitest has load-dependent races that showed on a loaded laptop (load avg 9–24) and
  passed alone and in a later full run: `home.test.tsx` (mock-data notice),
  `connect-shop-page.test.tsx` (reads `fetchSpy.mock.calls[0]` right after the heading
  renders), and two 5 s timeouts (`rules-editor-off-api`, `ops-p23-diag`). If the `frontend`
  job flakes on a deploy, "Re-run failed jobs" re-runs it and `deploy` only. Repay: await the
  fetch in `connect-shop-page.test.tsx` (`await waitFor(() => expect(fetchSpy).toHaveBeenCalled())`)
  and give the two editor tests an explicit timeout.
- [ ] `test_action_card_refresh_cooldown::test_slow_backing_store_does_not_stall_the_event_loop`
  failed once under heavy load (the #2058 contention flake; its bound is `wait_for` 0.6 s) and
  passed 3/3 alone. Same re-run advice.
- [ ] The prior-figure fixed set only shrinks (`reconcile --write` prunes; it never adds). If a
  recorded helper-style test is rewritten with a direct `assert`, the set loses it and the claim
  drops by one, as it should. Adding an identity is a hand edit that review must see.

## P58 — production bugs from the 2026-10-19 worker log (D67)

- [ ] The exception line of `product_history_promotions_failed` was not in the pasted grep, so the
  exact value is inferred, not seen: `fromtimestamp` (normalize.py:53 at `efb1df92`) raises only
  for an out-of-range number. A millisecond `update_time` is the documented-in-repo shape
  (`services/shop_diagnosis/promotions.py`). The fix accepts every numeric shape. Repay: after
  the next nightly run, confirm `product_history_promotions_swept` for the shop and
  `skipped: []`.
- [ ] Other per-shop jobs read `credential.shop_cipher` directly without the backfill:
  `services/product_history/job.py` `plan_reads`, `shop_diagnosis_daily/job.py`,
  `onboarding/quick_scan.py`, `analytics_backfill/orchestrator.py`, `agent/composition.py`.
  They rely on bootstrap / poll (which do backfill) having run first. The quick scan runs
  *beside* bootstrap, so on a cipher-less shop's first connect it can still hit 106013 once.
  Repay: route those through `backfill_shop_cipher` too, or have `TikTokClient` refuse a
  202309 shop-scoped path with no cipher before sending (needs a path list from the OAS).
- [ ] Bootstrap failures in general still retry on every fan-out tick (15 min) forever: the
  fan-out enqueues any shop whose fast phase is not done, and `bootstrap_queued` dedupes only
  while a task is queued. P58 ends the loop for the missing-cipher case (the shop leaves the
  enumeration). Any other permanent failure (for example a scope the seller did not grant) still
  loops. Repay: back off on `shop_ingestion_state.failed_at` (for example skip for 1 h × 2ⁿ
  failures, capped at a day) and surface the shop in Ops.
- [ ] `exc.request.url` on the re-raised `requests` errors still holds the signed query. Nothing
  logs it today; a future `logger.error(..., extra={"url": exc.request.url})` would.
- [ ] `test_juli_app_grants_cover_mutations.py` whole-tree scans take 13–15 s alone and time out
  at pytest.ini's 30 s under load (seen twice during P58). Same class as P55's
  `test_credentials_in_url_guard` scans. Repay: `pytest.mark.timeout(120)` on the two scans.
