# ADR-112: Ingestion runs as prioritised per-shop jobs under one shared rate coordinator, lands every payload in partitioned bronze first, and maps it to shared silver with versioned, replayable mappers

**Status:** Accepted (owner, 2026-10-20, grill D70)
**Date:** 2026-10-20
**Related ADRs / decisions:** fast-track D70.1–3, D70.7, D70.8, D70.14, D70.15, D70.16 (grill
`docs/product/data-platform/GRILL_LOG.md`, gap map `GAP_MAP_FASTTRACK.md`); builds on
[ADR-009](009-entity-centric-data-model.md) (canonical keys), [ADR-029](029-phase-2.9-analytics-historical-backfill.md)
(call budget, partitions), [ADR-046](046-cdp-medallion-physical-model.md) (medallion, cutover by domain),
[ADR-089](089-fleet-scoped-work-under-tenant-isolation.md) (fleet work under RLS),
[ADR-101](101-tests-derive-from-captured-fixtures.md) (fixtures), [ADR-104](104-poll-steps-report-outcomes-inside-the-cycle-budget.md) /
[ADR-105](105-a-poll-cycle-has-a-verdict-and-leaves-a-record.md) (step outcomes, cycle verdict, #1950),
[ADR-111](111-shopee-isv-resubmission-reviewer-trial-account.md) (Shopee). Fast-track: P1-B (per-shop fan-out),
D25.12 / P17 / D26 (connect history, quick scan), D30 / P23 (product history), D31 / P24 (ingest gateway,
`shops.platform`), P8-C (`run_write_values`). Siblings: ADR-113 (shop data D70.4–6), ADR-107 amended
(D70.9, D70.11), ADR-114 (experiments), ADR-115 (training data, model gate).
**Amends:** ADR-029, ADR-046, ADR-104, ADR-105 (dated notes appended to each).

## Context

Every shop must be ingested automatically — connect → backfill → poll — for two platforms (TikTok
now, Shopee later), fast enough that the first recommendation arrives early, and reproducibly
enough that a mapper bug can be fixed by replay rather than by re-fetching. The branch already has
much of the skeleton (gap map §A/§B):

- **Per-shop orchestration exists.** `workers/tasks/shop_ingestion.py` (P1-B): `shop-poll-fanout`
  every 15 min → `bootstrap_shop` (queue `ingest_priority`), `shop_history_backfill` (queue
  `ingest_backfill`), `poll_shop`, `shop_history_extend` (nightly), Redis per-shop `cycle` /
  `history` locks (`workers/services/polling/shop_lock.py`), `_CycleDeadline`. State in
  `shop_ingestion_state` (MIG/074): status, `fast_done_at`, `history_done_at`,
  `history_earliest_date`, `analytics_through_date`, … — 60 days on connect, 180 nightly (D25.12).
- **Rate limiting is a fixed-window counter, not a coordinator.** `integrations/tiktok/rate_limiter.py`
  (`INCR` + `EXPIRE`, key `ratelimit:{app}:{shop}:{endpoint}`; its docstring says "token bucket", it
  is not). Seven call sites build their own instance: `workers/services/polling/sync.py`,
  `orchestrate.py`, `analytics_range.py`, `services/shop_diagnosis_daily/pacing.py`,
  `services/action_cards/refresh.py`, `services/tiktok/poll_resources.py`,
  `services/cdp_speed/targeted_fetch_executor.py`. No priorities, no 429-driven back-off, no
  fairness between shops. `services/analytics_backfill/budget.py` (`CallBudgetGovernor`, 400 / 499
  attempts per run, ADR-029) caps one run, not the fleet.
- **Bronze is per-domain and partial.** `bronze.order_raw_payloads` / `return_raw_payloads`
  (MIG/023), ctor / live-hours bronze (MIG/029), `ingest_raw_payloads` (MIG/088, extension source,
  already has `platform` + `dataset`). No bronze for products, promotions or video; no `endpoint`
  column; no partitioning (`ops.analytics_backfill_partitions`, MIG/019/022, is a checkpoint table,
  not a Postgres partition); retention only for `ops_audit_retention` / `privacy_account_purge`.
- **Silver rows do not know their source.** No `bronze_id`, no `mapper_version`, no replay path.
- **#1950 is still open.** `persisted` counts rows the ETL sent to the DLQ (see decision 5).
- **One shop is still hard-wired.** `DEMO_REFERENCE_SHOP_ID` drives the daily analytics top-up and
  the hourly mock reconcile; legacy `workers/tasks/fujiwa_poll_beat.py` still polls `shop_id=None`.

The grill decided the shape (D70.1 A, D70.2 A, D70.3 A, D70.7 A, D70.8 A, D70.14 A, D70.15 A). This
ADR turns it into tables, modules and jobs on top of what exists; it does not rebuild P1-B.

## Decision

### 1. Platform boundary: adapters below bronze, one silver above it (D70.1)

1. **Adapter per platform**, `backend/src/juli_backend/services/ingestion/adapters/{tiktok,shopee}/`,
   implementing one protocol `PlatformAdapter`: `endpoints()` (catalogue: endpoint key, version,
   `endpoint_group`, priority class, `max_depth_days`, page size), `fetch_page(job, cursor) →
   Page(payloads, next_cursor, http_status)`, auth refresh and pagination. Signing, paging and
   vendor error codes stay inside the adapter; `integrations/tiktok/client.py` is its transport.
   Nothing above bronze imports an adapter.
2. **Generic bronze**: `bronze.platform_raw_payloads` (next migration after 094), range-partitioned
   by `received_at` (decision 4):
   `id uuid`, `received_at timestamptz`, `shop_id uuid`, `platform varchar(16)`, `endpoint
   varchar(64)`, `endpoint_version varchar(16)`, `request_hash char(64)` (canonical params),
   `data_date date NULL` (business day the payload describes), `job_id uuid NULL`, `page_no int`,
   `payload jsonb`, `payload_hash char(64)`, `map_status varchar(12)` (`pending` | `mapped` |
   `failed` | `skipped`), `map_error varchar(500)`, `mapper_version_applied int NULL`.
   PK `(id, received_at)`; indexes `(shop_id, platform, endpoint, received_at)`,
   `(shop_id, platform, endpoint, data_date)`, partial `(received_at) WHERE map_status = 'failed'`.
   No unique constraint on content: re-pulls (D70.5's 7-day re-pull) keep every version.
   RLS: shop-owned, two-tenant pattern (ADR-089).
3. **Existing bronze is kept, not converted.** MIG/023 / MIG/029 tables keep their writers until
   their domain is cut over (decision 6), then become read-only and age out through the archive job
   (decision 4, month-range mode). `ingest_raw_payloads` (MIG/088) is registered as a second
   bronze source for the mapper registry (`endpoint := dataset`); it is not repartitioned.
4. **Silver is shared**: ADR-009 canonical entities keyed `(shop_id, platform_object_id)` plus
   `platform`; platform-neutral metric names and a `channel` column (tables in ADR-113). Impact
   readers, recommenders and models read silver only.
5. **Infra tables become platform-generic additively**: `platform varchar(16) NOT NULL DEFAULT
   'tiktok'` on `tiktok_sync_state` (MIG/009/071), `tiktok_credentials` (MIG/001),
   `webhook_raw_events` (MIG/016). Renames to `sync_state` / `platform_credentials` are deferred to
   D70.16 P8 (Shopee adapter), behind compatibility views.

### 2. Job queue and rate coordinator (D70.2)

1. **`ops.ingest_jobs`** (next migration after 094; `ops` schema, MIG/021 grants):
   `id uuid PK`, `platform`, `shop_id`, `kind` (`fetch` | `replay` | `archive` | `partition_maint`
   | `reconcile`), `endpoint`, `endpoint_group`, `range_start date NULL`, `range_end date NULL`,
   `priority smallint` (0 / 1 / 2 / 3), `source` (`connect` | `history` | `poll` | `webhook` |
   `replay` | `manual`), `status` (`queued` | `leased` | `done` | `failed` | `dead` | `cancelled`),
   `attempts`, `max_attempts`, `next_attempt_at`, `lease_owner`, `lease_expires_at`,
   `cursor jsonb` (page token / offset — resumable), `pages_done`, `rows_fetched`,
   `rows_persisted`, `rows_failed`, `rows_duplicate`, `last_http_status`, `last_error`,
   `mapper_version_target int NULL` (replay), `parent_job_id`, `created_at`, `updated_at`,
   `done_at`.
   Indexes: claim `(priority, next_attempt_at) WHERE status = 'queued'`; `(shop_id, status)`;
   de-duplication unique partial `(platform, shop_id, kind, endpoint, range_start, range_end)
   WHERE status IN ('queued', 'leased')` so a backed-up producer cannot stack copies (replaces the
   `bootstrap_queued` / `history_queued` Redis markers once P1-B producers move onto jobs).
   Enumeration and claim go through SECURITY DEFINER functions `ops.ingest_claim_jobs(worker,
   n)` / `ops.ingest_finish_job(...)`; data writes then run under `with_sticky_shop_scope` for the
   job's shop (ADR-089). Shops never read this table; they read readiness (§3).
   Plus `ops.ingest_shop_turns(platform, shop_id, last_served_at)` for round-robin.
2. **Priorities.** P0 = catalogue + product detail / images + 30-day product performance.
   P1 = deep history, orders / returns, promotions, video / live. P2 = scheduled polls and
   webhook-triggered targeted re-reads. P3 = replay / archive / maintenance (no API tokens; queue
   `ingest_replay`, runs only on idle capacity).
3. **Rate coordinator**, `services/ingestion/rate_coordinator.py`: a token bucket per
   `(platform, app_id, shop_id, endpoint_group)` in Redis, refill-and-take in one Lua script
   (key `ratebucket:{platform}:{app}:{shop}:{group}`, fields `tokens`, `ts`, `rate`). Ceilings
   (`rate`, `burst`) come from the adapter catalogue; the TikTok default is ADR-029's calibrated
   ~10 req / 60 s per endpoint group until measured otherwise.
   - **429 lowering (AIMD):** a `RateLimitError` (TikTok `100005`, HTTP 429) halves that bucket's
     `rate` (floor 1 / 300 s) and sets the job's `next_attempt_at` from the vendor's reset or
     exponential back-off; a 429 does not consume `attempts`. Each clean 10 minutes restores
     +10 % up to the ceiling. Every lowering is logged and counted (§7 SLOs).
   - **P2 reserve:** P0 / P1 may take a token only while `tokens > reserve × burst`
     (`INGEST_P2_RESERVE_FRACTION`, default 0.2); P2 may drain the bucket. A fleet of cold starts
     can therefore never starve existing shops' polls.
   - **Existing limiter becomes a façade.** `integrations/tiktok/rate_limiter.RateLimiter` keeps its
     signature (`acquire`, `is_exhausted`, `time_until_reset`) and delegates to the coordinator with
     an endpoint → group map, so the seven legacy call sites and the new adapter share one budget
     during parallel write (D70.14 (1)). Its docstring is corrected. `CallBudgetGovernor` remains
     the per-job attempt cap.
4. **Worker loop**, task `juli_backend.ingest_drain` (`workers/tasks/ingest_drain.py`): claims the
   top N queued jobs ordered by `priority, ingest_shop_turns.last_served_at, next_attempt_at`; for
   each, tries the coordinator; leases on success (`FOR UPDATE SKIP LOCKED`), skips otherwise;
   runs inside `_CycleDeadline`; after every page commits bronze rows + `cursor` + counters in one
   transaction. A killed worker's lease expires and the next claim resumes from `cursor`.
   Routing: `ingest_drain(max_priority=0)` on `ingest_priority`, `(1)` on `ingest_backfill`,
   `(2)` on the default queue, `(3)` on `ingest_replay`; beat `ingest-drain-tick` (every minute,
   off the :00 slot — #1659) keeps one drain alive per queue.
5. **P1-B tasks become producers.** `bootstrap_shop` enqueues the shop's P0 then P1 jobs;
   `shop_history_backfill` / `shop_history_extend` enqueue monthly P1 chunks (ADR-029 partition
   logic reused from `services/analytics_backfill/*_partition.py`); `shop_poll_fanout` enqueues P2
   jobs; webhook re-reads (`services/product_history/webhooks.py`) enqueue P2 `webhook` jobs.
   `shop_quick_scan` (D26) waits on P0 completion instead of its own fetch. The per-shop Redis
   locks stay until each domain's cutover; leases supersede them per job afterwards.

### 3. Readiness levels per shop (D70.3)

1. **Columns on `shop_ingestion_state`** (next migration after 094): `readiness_level smallint NOT
   NULL DEFAULT 0`, `readiness_l1_at`, `readiness_l2_at`, `readiness_l3_at timestamptz NULL`,
   `readiness_detail jsonb` (per endpoint: days covered vs required, `depth_unmeasured`).
   Levels only rise; a regression (e.g. lost credential) is a status, not a lower level.
2. **Definitions.** L1 = all P0 jobs done (catalogue + detail / images + 30 days of performance) →
   first recommendation, labelled *sơ bộ*, only levers measurable within 30 days. L2 = 90 days of
   performance + orders + promotions → label removed, levers needing a long base unlocked (ADR-077
   14-day pre-period + controls). L3 = every endpoint at its `max_depth_days`, measured read-only on
   Fujiwa (D70.16 P0, still open) and written into the adapter catalogue; until measured, L3 is
   unreachable and `readiness_detail` says so → training data (ADR-115).
3. **Evaluator** `services/ingestion/readiness.py::evaluate(shop_id)`, run by `ingest_finish_job`
   after every job for that shop. It is the single source for the UI label, the recommenders'
   lever gate (each lever declares `min_readiness`) and the model gate.
4. **Relation to D25.12.** Connect history stays 60 days (`SHOP_HISTORY_CONNECT_DAYS`), but days
   61–90 are enqueued as P1 immediately, not nightly, so L2 is not held hostage by the nightly
   trickle; beyond 90 days history is ordinary P1 under the coordinator, and the
   `shop-history-extend` beat retires at P5. `fast_done_at` / `history_done_at` stay for D26.

### 4. Partitions, retention, archive, replay source (D70.7)

1. **Native monthly range partitions** (no extension; Supabase + Postgres 16 CI) for
   `bronze.platform_raw_payloads` and the ADR-113 silver series (product × day × channel,
   SKU × day, shop × day, inventory history). Children `<table>_pYYYYMM`; no DEFAULT partition, so
   a missing month fails loudly instead of filling a default that later blocks attach.
2. **Registry** `ops.partitioned_tables(table_name PK, partition_column, retention_months NULL,
   archive bool, months_ahead smallint DEFAULT 2)`.
3. **Pre-create job** `juli_backend.ingest_partition_maintain` (kind `partition_maint`, daily):
   creates months through `now + months_ahead`, asserts each registered table has them, fails the
   job (and the D15 SLO) otherwise.
4. **Retention.** Silver: forever. Bronze: 13 full months in Postgres, then
   `juli_backend.bronze_archive_month` (kind `archive`): export the month to Parquet
   (`bronze/<table>/<YYYY-MM>/part-NNN.parquet`, private object-storage bucket `bronze-archive`),
   write `manifest.json` (row count, sha256 per file, min / max `received_at`, schema version,
   mapper versions seen), read back and verify hashes and counts, record in
   `ops.bronze_archives(table_name, month, storage_uri, manifest_sha256, row_count, exported_at,
   verified_at, detached_at, dropped_at)`, `DETACH PARTITION … CONCURRENTLY`, drop after a 7-day
   grace. Legacy bronze tables (MIG/023/029/088) use the same job in month-range mode
   (export → verify → `DELETE` by month).
5. **Replay from archive** reads Parquet via the manifest and feeds the same mapper (§5); it never
   re-inserts into Postgres bronze. Silver therefore carries `bronze_id` + `bronze_received_at`
   (no FK — a FK would block detach), which stay resolvable through the manifest.

### 5. Bronze-first, versioned mappers, replay, honest counts (D70.8, closes #1950)

1. **Order of operations per page:** adapter fetch → insert bronze rows (`map_status='pending'`) +
   job cursor in one transaction → commit → mapper. A mapper crash never loses the payload.
2. **Mapper registry** `services/ingestion/mappers/registry.py`, keyed `(platform, endpoint)`;
   each mapper is a pure function bronze row → silver rows with an integer `MAPPER_VERSION`.
   Existing transforms in `services/etl/` (`transform.py`, `silver_promotion.py`) are wrapped, not
   rewritten.
3. **Every silver row carries `bronze_id uuid`, `bronze_received_at timestamptz`,
   `mapper_version int`** (the latter is D70.12's known-at). Upsert on the silver natural key with
   `ON CONFLICT … DO UPDATE … WHERE (excluded.bronze_received_at, excluded.mapper_version) >
   (t.bronze_received_at, t.mapper_version)` — idempotent, and an older payload can never overwrite
   a newer one.
4. **Bronze status** is set after the silver write: `mapped` + `mapper_version_applied`, or
   `failed` + `map_error`. **Only `mapped` counts as persisted.** Job counters split
   `rows_persisted` / `rows_duplicate` / `rows_failed`.
5. **Replay** = a P3 `replay` job `(platform, shop, endpoint, range, mapper_version_target)` over
   bronze rows with `mapper_version_applied < target OR map_status = 'failed'`, from Postgres or the
   archive. Bumping a mapper version is a PR that ships the mapper, its fixture test and the replay
   enqueue together.
6. **#1950 in today's code, fixed first (gap map P1 item 6).** The bug lives in
   `services/ingestion/handoff.py::make_etl_handoff`: the inner `handoff` awaits
   `consumer.ingest(...)` and discards the returned `ProcessOutcome`
   (`services/etl/consumer.py`: `PROCESSED` / `DUPLICATE` / `DLQ`) because `HandoffFn` is typed
   `-> None`; `_CountingHandoff.__call__` in `workers/services/polling/sync.py` then increments
   `persisted` on any non-raising return, so a DLQ'd row is "persisted" and flows into
   `tiktok_sync_state.last_persisted` (ADR-105 Consequences). Fix: `HandoffFn` returns
   `ProcessOutcome`; `_CountingHandoff` counts `PROCESSED` → `persisted`, `DUPLICATE` → new
   `duplicate`, `DLQ` → `failed`. Watermark gating treats `persisted + duplicate > 0` as landed
   (a duplicate is already in Postgres); `_step_failed_the_cycle` is unchanged in shape.
7. **Shopee** = a new adapter + mappers + redacted fixtures; nothing above bronze changes.

### 6. Cutover on Fujiwa, then the fleet (D70.14)

1. **Parallel write.** On Fujiwa the new adapter + mappers write new bronze / silver from P2-priority
   jobs while every reader stays on legacy tables; both paths draw on the same coordinator
   buckets (§2.3). The extra calls are accepted for one shop.
2. **Daily reconcile** `juli_backend.ingest_reconcile_daily` (kind `reconcile`) writes
   `ops.ingest_reconcile_results(shop_id, domain, metric, day, new_value, legacy_value,
   a34_value NULL, abs_diff, rel_diff, within_tolerance, run_at)`, PK `(shop_id, domain, metric,
   day, run_at)`. Three-way: new silver ↔ legacy tables ↔ the A-34 script snapshot (sim-pilot
   capture of 2026-10-08) for the days it covers. Tolerances per `(domain, metric)` in config
   (proposed: counts exact, GMV ≤ 0.5 %, traffic ≤ 1 %). A domain is eligible after **7**
   consecutive in-tolerance days (proposed N; owner may change).
3. **Cutover per domain, one PR + flag each, in order:** orders / returns
   (`INGEST_SILVER_READ_ORDERS`) → products (`…_PRODUCTS`) → performance (`…_PERFORMANCE`) →
   promotions / content (`…_PROMOTIONS_CONTENT`). Rollback = flag off. The legacy writer of a domain
   is deleted in a follow-up PR 14 days after its flag goes on — no long-lived double write
   (ADR-046).
4. **Fleet.** Shops other than Fujiwa enter the new layer only after Fujiwa's performance domain is
   cut; first through `INGEST_PLATFORM_SHOP_ALLOWLIST`, then all.
5. **Remove the hard-wired shop** (P5). Files that change:
   - `backend/src/juli_backend/workers/tasks/analytics_backfill_topup.py` (env read at line 35,
     scope notes lines 9 / 143) → replaced by per-shop P1 / P2 jobs; deleted.
   - `backend/src/juli_backend/workers/tasks/mock_analytics_reconcile.py` (lines 4, 61) → envelope
     recompute per shop after mapper completion (ADR-046 Q4 shared compute); deleted.
   - `backend/src/juli_backend/workers/celery_app.py` → beats `mock-analytics-hourly-reconcile`
     (line 58) and `analytics-backfill-topup` (line 72) removed; `ingest-*` beats added.
   - `backend/src/juli_backend/workers/tasks/impact_reader.py` docstring (line 8) — the
     "other shops are suppressed" note goes; `backend/src/juli_backend/workers/MODULE.md:11`.
   - `backend/src/juli_backend/workers/tasks/fujiwa_poll_beat.py` (`shop_id=None`) — deleted at
     the orders cutover.
   - `infra/scripts/restore-analytics-history.sh` (lines 20, 58–59: require `SHOP_ID`, no
     fallback), `infra/scripts/env/api.env.example:74` (comment narrowed to the Demo binding).
   - Tests: `tests/unit/test_worker_analytics_backfill_topup.py`,
     `tests/unit/test_mock_analytics_hourly_reconcile.py`,
     `tests/integration/test_mock_analytics_reconcile_two_tenant.py` — deleted with their tasks.
   - **Kept:** `api/routes/demo_analytics.py:33` (`get_demo_reference_shop_id`) and the
     `demo_decisions` / `demo_execution` mentions — a read-only public Demo display binding
     ([ADR-094](094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md)), not ingestion; their tests stay.

### 7. Production bar (D70.15)

1. **Test layers** (CI tier in brackets; DB invariants on real Postgres, never SQLite):
   (1) mapper on redacted real fixtures + replay determinism — same bronze → same silver
   (ADR-101) [issue]; (2) Postgres: partition create / detach / drop, idempotent upsert and
   newer-wins, D4 versions, D11 three-way revert check, two-tenant RLS on every new table [issue,
   Postgres; not `migration_heavy`-deselected]; (3) coordinator: ~50 shops against a fake API that
   429s above a threshold — 429 rate under target, new shop's P0 within its deadline, old shops'
   P2 not late [issue]; (4) fault tolerance: kill the worker mid-backfill → resume from `cursor`,
   no loss, no duplicate silver [issue, Postgres]; (5) adapter contract against the TikTok
   sandbox [`merge_group`]; (6) leakage (ADR-115) [issue]; (7) the D14 daily reconcile [production
   job + its own unit tests].
2. **Per-shop SLOs** (written to `ops.ingest_shop_slo(shop_id, day, …)` by a daily job, shown on the
   Ops console, MIG/083): freshness per endpoint group (P2 ≤ 30 min behind), completeness vs the
   shop's readiness target, 429 rate (< 1 % of calls), queue lag per priority (P0 ≤ 15 min from
   connect), mapper failures (`map_status='failed'` = 0 unexplained), ADR-105 poll verdict. A
   breach writes an alert row and a structured log (only production-visible after #1978).
3. **Runbooks** under `docs/runbooks/`: `ingest-shop-stuck-backfill`, `ingest-token-expired`,
   `ingest-mapper-replay`, `ingest-bronze-archive-restore`, `ingest-domain-rollback`.

## Migration path (D70.16)

- **P1 (before the layer):** #1950 fix (§5.6) — independent, small.
- **P2 foundation:** `ops.ingest_jobs`, `ops.ingest_shop_turns`, rate coordinator + `RateLimiter`
  façade, `ingest_drain`, `bronze.platform_raw_payloads`, `platform` columns (§1.5),
  `ops.partitioned_tables` + `ingest_partition_maintain`, archive job (dry-run until month 14),
  `ops.ingest_shop_slo` skeleton. P1-B producers enqueue jobs; legacy steps unchanged.
- **P3 TikTok adapter + mappers:** performance by channel, products, orders / returns; parallel
  write on Fujiwa; `ingest_reconcile_daily`; per-domain flags flip in §6.3 order.
- **P5 cold start for many shops:** readiness columns + evaluator + lever gating; remove
  `DEMO_REFERENCE_SHOP_ID` from ingestion (§6.5); retire `shop-history-extend`; allowlist, then all
  shops.

## Consequences

**Positive.** One budget for the whole fleet, so a cold start cannot 429 an established shop; every
payload survives mapper bugs and can be replayed; `persisted` finally means a committed row;
readiness is one number the UI, recommenders and models agree on; Shopee is an adapter, not a fork.

**Negative.** A second bronze path exists until each domain cuts over; Fujiwa pays ~2× calls during
parallel write; partitioned tables need the PK to include `received_at` / the date and forbid FKs
into bronze; an object-storage dependency for the archive; `last_persisted` values drop after the
#1950 fix (expected, not a regression).

**Follow-ups / owner.** (a) Measure `max_depth_days` per endpoint on Fujiwa (P0 open). (b) Confirm
reconcile tolerances and N = 7. (c) Confirm the archive bucket (Supabase Storage assumed).
(d) Days 61–90 at P1 on connect changes D25.12's cadence — owner to confirm. (e) Renames of
`tiktok_*` infra tables at P8.

## Alternatives considered

- **Shared adapter with platform switches** — rejected: vendor quirks leak into every
  layer; Shopee would fork the code anyway.
- **Keep Celery queues as the scheduler, no job table** — rejected: not resumable per
  page, no fairness, no reserve, priorities only as coarse as queues.
- **Per-shop fixed windows, no shared coordinator** — rejected: the 46 % success at
  ~1,000 calls / run (ADR-029) is the result.
- **Readiness as a boolean or derived on the fly** — rejected: three consumers would
  re-derive it differently.
- **pg_partman / TimescaleDB** — rejected: extension availability on Supabase and CI.
  Keeping bronze forever in Postgres — rejected on cost.
- **Map in the fetch transaction / overwrite in place** — rejected: a mapper bug then
  loses the payload and cannot be replayed.
- **Big-bang cutover / long-lived double write** — rejected by ADR-046.

## Verification

All seven D70.15 layers apply (§7.1). DB invariants — partitions, newer-wins upsert, claim / lease
with `SKIP LOCKED`, RLS on `bronze.platform_raw_payloads` and the `ops.ingest_*` functions — run on
real Postgres 16 in the issue tier with `DATABASE_URL` set (a skipped Postgres test is not a pass).
The #1950 fix is pinned by a unit test that feeds a `DLQ` outcome and asserts `persisted == 0,
failed == 1`, plus the existing `tests/integration` cycle replay. Sandbox contract runs in
`merge_group`.
