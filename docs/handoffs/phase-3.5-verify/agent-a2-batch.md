## Verdict A2 #602

**overall: PARTIAL**

**objectives:**
- Aligns with ADR-047 **Batch layer** definition: daily staggered per-shop reconcile, partition-resumable backfill, dual budgets, same `gold.kpi_envelopes` via Shared Compute Orchestrator, orthogonal to Speed, parallel with A1 after A0, does **not** block #599/#600.
- Correctly scopes fleet throughput vs Mock hourly exception (A1 owns hourly Fujiwa; A2 owns daily stagger for ~100 shops).
- Correctly defers read-replica isolation and columnar warehouse to 3.5-C / out of scope.
- **Gaps:** Postgres I/O budget is policy-only (not executor-specified); no deep modules table; no Context7 Postgres scalability patterns (GIN, batch inserts, pooling); as-built code is 2.9 backfill on flat `public.*`, not medallion batch reconcile.

**scalability_scorecard:**

| Dimension | Score | Notes |
|-----------|-------|-------|
| **dual_budgets** | PARTIAL | Partner API: prior art `CallBudgetGovernor` (400 soft / 499 hard, ADR-029). Postgres I/O: PRD intent only — no knobs, metrics, throttle points, or defer contract. |
| **stagger** | PASS (PRD) / FAIL (as-built) | PRD: deterministic shop→window, ~100 shops, no global hourly poll. Code: no stagger scheduler, Celery beat not wired for reconcile (`DAILY_SCORING_CRON_UTC` unused). |
| **mutex** | PARTIAL | PRD: batch defers when speed compute active (US #23). Code: ETL has per-shop `asyncio.Lock` + backpressure (`max_pending_per_shop=100`) — not a shared speed/batch compute mutex. |
| **checkpoints** | PASS (pattern) / PARTIAL (location) | ADR-029 partition resume proven: `public.analytics_backfill_partitions` (512 rows), `AnalyticsBackfillPartitionsRepo`, orchestrator skip/resume. Target `ops.*` migration not started; A0/A2 split unclear on owner. |
| **same_gold** | PASS | Locked: batch uses Shared Compute Orchestrator → same `gold.kpi_envelopes`; no forked serving table or KPI formula. Integration test requirement stated. |
| **agent_clarity** | PARTIAL | A2 vs A1 boundary clear in ADR-047/comments. **“Speed”** naming risks agents optimizing A1 for latency/cost; A1 hourly reconciler blurs OLTP vs scheduled backstop. |

**as_built_gaps:**
1. **Medallion absent** — live DB: auth, public, realtime, storage, vault only; no `bronze`/`silver`/`gold`/`ops` (`external-refs.md`).
2. **`analytics_backfill_partitions` still in `public`** — 512 rows; indexed `(shop_id, bucket, partition_date)`; ADR-046/A2 US #28 target `ops.*` unstarted.
3. **Serving gold not cut over** — `public.analytics_kpi_envelopes` exists (jsonb payload) but 0 rows; no `gold.kpi_envelopes`.
4. **Backfill writes flat silver analog** — `catalog_partition.py` / orchestrator upsert `public.analytics_performance_intervals`, not medallion bronze→silver→gold.
5. **Partner budget only** — `/Users/macos/Juli-AI-v2/backend/src/juli_backend/services/analytics_backfill/budget.py` governs HTTP attempts per run; no Postgres I/O governor, no per-credential+endpoint daily quotas, no structured defer reason codes beyond `stopped_reason=budget`.
6. **No batch reconcile scheduler** — stagger, fleet window assignment, config flag rollout (Further Notes) are PRD-only.
7. **No speed/batch mutex module** — PRD requirement not reflected in codebase.
8. **Webhook/ETL durability partial** — `EtlConsumer` has dedup (`processed_events`), DLQ, per-shop ordering, latency budget logging; material webhook→compute enqueue (A1) still the production gap per ADR-048.

**context7_alignment:**

| pattern | prd_coverage | gap |
|---------|--------------|-----|
| PostgreSQL JSONB GIN (`@>`, expression indexes) | A0 jsonb contract only | A2 silent on bronze payload / gold envelope indexing; `db-envelopes-extra.txt` shows no GIN on envelope payload |
| Batch INSERT / COPY for bronze append volume | Not mentioned | A2 says bronze append but no bulk-write strategy for fleet reconcile |
| Connection pooling for fleet batch workers | Not mentioned | Critical for ~100-shop staggered jobs against Supabase |
| Celery rate_limit / periodic stagger (`is_due`) | Stagger concept only | No scheduler mechanism, task rate limits, or dynamic defer |
| Redis lock / stampede patterns | Serving read-through referenced | No Redis shop compute lock for speed/batch mutex |

---

## Cross-issue contradictions (598–602)

| Topic | Status | Detail |
|-------|--------|--------|
| **Warehouse (ClickHouse)** | **Aligned** | All issues + ADR-047: Postgres medallion sufficient; no columnar warehouse for 3.5 exit. |
| **OAuth / seller_connect** | **Aligned** | Mock `production_read` Fujiwa only; Sign-in disabled; deferred to 3.5-C / Phase 3. |
| **Bestselling KPI** | **Aligned** | ADR-049 five KPIs everywhere; A-38/A-39 = A1 ops quota guard, not Demo card (#601, #600, #602 OOS). |
| **Read-replica** | **Aligned** | A2 documents 3.5-C follow-up; not an A2 exit gate (#602, ADR-047). |
| **A2 blocks #599 Decisions?** | **No contradiction (intent)** | #602, ADR-047, #599 comment: B blocked on **A1 only**. |
| **Stale “Phase 3.5-A” monolith** | **Contradiction (docs drift)** | **#599** body still says “Phase 3.5-A must exit first” / “blocked on Phase 3.5-A” in 6+ places; comment fixes to A1 but body not updated. **#600** still labels #598 as “Phase 3.5-A: Continuous CDP Analytics spine” (now A0 Foundation). Agents may treat A0+A2 as Decisions gate. |
| **Hourly vs daily reconcile** | **Aligned** | A1: hourly Fujiwa Mock only (#601, ADR-048). A2: daily stagger fleet (#602). #602 US #27 reinforces no duplication. |
| **`ops.*` partition migration owner** | **Soft contradiction** | **#598** A0 US #2 + cutover step (2): ops moves first. **#602** US #28: partitions in `ops.*`. Neither assigns exit gate — risk A2 starts before A0 completes ops migration. |
| **Decisions + staggered reconcile** | **Intentional asymmetry** | #599 US #30: daily stagger *should* refresh Decision candidates when A2 exists; exit gate remains A1-only. Not a blocker contradiction. |
| **Finance/video P1 fetches** | **Minor scope bleed** | #602 US #24 sequences finance/video as batch-friendly P1; #601 lists same as A1 P1 after P0. Acceptable if batch extends speed-deferred work, but Executor needs explicit “A1 defers → A2 batch plan” handoff to avoid duplicate fetch. |

**A2 does NOT incorrectly block #599:** Confirmed across ADR-047 dependency graph, #602 assumptions/OOS/US #15, and #599 comment. Decisions needs continuous KPI envelopes from **A1 Speed** (webhook-first `computed_at` advance), not fleet batch reconcile.

---

## Performance/scalability recommendations (max 10)

1. **Add a Postgres I/O budget spec to #602** — module name, env knobs (e.g. `BATCH_BRONZE_ROWS_PER_FLUSH`, `BATCH_SILVER_UPSERT_BATCH_SIZE`, `BATCH_MAX_CONCURRENT_SHOPS`), metrics (`batch_postgres_io_deferred_total{reason}`), defer semantics mirroring Partner budget (`finish("io_budget")`, do not mark partition complete).

2. **Define structured defer reason codes** — enum shared by scheduler: `partner_budget_exhausted`, `postgres_io_throttled`, `speed_mutex_active`, `gap_not_detected` (US #12); wire to observability fields in Further Notes.

3. **Assign `analytics_backfill_partitions` → `ops.*` to A0 exit** — A2 depends on A0; make Alembic move + repo schema prefix an A0 acceptance criterion so A2 batch reconcile lands on canonical ops home (ADR-046 Q2).

4. **Add #602 deep modules table** (mirror #599) — `StaggerScheduler`, `BatchFetchPlanner`, `PostgresIoBudgetGovernor`, `ShopComputeMutex`, `BatchReconcileOrchestrator` with public interfaces; reduces Executor improvisation.

5. **Specify stagger algorithm** — e.g. `window_start = base + hash(shop_id) % 1440` minutes, one reconcile window/shop/day, collision-free proof in CI; reference Celery Beat `is_due` or cron slot per shop stub.

6. **Specify shop compute mutex** — Redis lock key `compute:{shop_id}`, TTL, batch defer-on-contention test (US #23 negative path); distinguish from ETL ingest lock.

7. **Rename agent-facing layer labels** — A1 → **“Freshness layer (OLTP-shaped, event-driven)”**; A2 → **“Fleet throughput layer (OLAP-shaped, scheduled)”**; add explicit guardrail: *“Do not optimize A1 for fleet scale or cost; do not optimize A2 for webhook latency.”*

8. **Embed Context7 Postgres patterns in A0/A2** — A0: GIN or expression index plan for `gold.kpi_envelopes.payload`; A2: bronze bulk append via batched INSERT/COPY; fleet workers must use pooler (document Supabase pooler requirement).

9. **Clarify batch vs 2.9 backfill orchestrator** — A2 should extend/refactor `analytics_backfill` partition loop to write bronze + invoke Shared Compute, not continue upserting `public.analytics_performance_intervals` as long-term batch path.

10. **Scrub stale monolith references** — Update **#599** body and **#600** related-track line to **A0 → A1 → B** naming so Meta/Executor agents do not block Decisions on A2 or conflate #598 with full Analytics spine.

---

## Overall roadmap health for Decisions enablement

**Healthy with one documentation hazard.**

The dependency graph is architecturally sound: **A0 (schemas + serving contract) → A1 (webhook-first freshness + five KPIs) → #599 Decisions**, with **A2 parallel and non-blocking**. Warehouse, OAuth, Bestselling, and read-replica positions are consistent across 598–602 and ADRs.

Decisions enablement is correctly gated on **A1 Speed exit** (continuous shared compute trigger + `computed_at` on Demo Analytics), not batch fleet work. A2 improves **gap healing at scale** (and #599 US #30 will benefit once A2 ships) but must not appear on Decisions’ critical path.

Primary risk to Decisions timeline is **not A2** — it is (a) **#599/#600 stale “3.5-A” wording** misleading agents into over-scoping prerequisites, and (b) **A1 production webhook→compute gap** (ADR-048) remaining unimplemented. A0 medallion + ops migration should land first so A1/A2 batch paths do not accumulate more `public.*` debt.

**Executor readiness for A2 scalability:** PARTIAL — strong ADR alignment and 2.9 partition/checkpoint prior art, but dual-budget concreteness, stagger/mutex modules, and Context7 Postgres fleet patterns need PRD hardening before implementation.

[REDACTED]