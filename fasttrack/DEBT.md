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
- [ ] Anonymous Phân tích sample is a 100 KB bundled JSON
  (`lib/shop-analysis/sample-report.json`, generated from a synthetic snapshot
  via `tests/support/shop_diagnosis.py` + `build_report`; generator kept out of
  the repo) — speed — commit the generator script or shrink the sample.
- [ ] Inter font is named in the stack but not loaded (mock imports Google
  Fonts) — no network at build — add `next/font` if the owner wants Inter
  everywhere.
- [ ] Demo header keeps the old mode switcher / "Làm mới Demo" controls inside
  the kit header (mobile alignment of "Đăng nhập" is off, pre-existing) —
  out of scope — redesign the header actions with the owner.
- [x] ~~e2e: static-asset-render ×3 and accessibility "Analytics chart…" failed after the D21 restyle~~ — repaid: specs follow D21 (flat kit background, gradient wordmark, KPI dashboard at `/analytics/gmv-tiktok`); 18/18 pass on both projects.
- [ ] vitest needs Node 20 locally: under Node 26 jsdom's `localStorage` is
  shadowed (270 failures on untouched main) — env — pin `.nvmrc` to 20.

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
