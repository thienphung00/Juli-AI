## Verdict A0 #598
overall: PARTIAL

objectives:
- Create four medallion schemas (`bronze`/`silver`/`gold`/`ops`) with service-role grants; gold-only client exposure + RLS
- Migrate `ops.*` checkpoints first (e.g. `analytics_backfill_partitions`); per-domain cutover starting orders/returns (A-7)
- Establish serving contract `gold.kpi_envelopes` with flexible `payload.kpis`; stub `gold.ml_feature_snapshots`
- Prove first-domain bronze→silver path; seed/empty gold envelope + compat view; retire legacy writers for migrated domain
- Exit gate: schemas + first domain cutover + serving contract live — **no** deployed material webhook handoff or five KPI precompute (deferred to A1)

as_built_gaps:
| claim | evidence | severity |
|-------|----------|----------|
| Four medallion schemas exist | Live DB (`docs/handoffs/phase-3.5-verify/db-relations.txt`, `external-refs.md`): only `auth/extensions/public/realtime/storage/vault`; no `bronze`/`silver`/`gold`/`ops` | **critical** |
| `gold.kpi_envelopes` serving contract | Live has `public.analytics_kpi_envelopes` (db-relations); no `gold.*`. ADR-046 Q3 = PK `shop_id` only; legacy #525 = `UNIQUE (shop_id, kind)` + `kind` column — shape mismatch not addressed in #598 | **critical** |
| Orders/returns bronze→silver cutover | `EtlConsumer` upserts directly to `public.orders`/`public.returns` via repos (`backend/src/juli_backend/services/etl/consumer.py`); no bronze append layer | **critical** |
| `ops.*` pipeline home | `AnalyticsBackfillPartition` still `public.analytics_backfill_partitions` (`models.py:781-813`); 512 rows live | **high** |
| Raw landing in bronze | `public.webhook_raw_events` (1936 rows, indexed by `received_at`/`event_type`) acts as ad-hoc raw store; PRD does not say migrate vs duplicate into `bronze.*` | **high** |
| One writer per table / layer isolation | Flat `public` mixes raw (`webhook_raw_events`), domain (`orders`, `analytics_performance_intervals`), ops (`analytics_backfill_partitions`); no schema grants | **high** |
| ML gold stub + silver SoT | No `gold.ml_feature_snapshots`; `docs/ml/ml_layer.md` not wired to silver paths in code | **medium** |
| Compat view for Demo continuity | No compat view or gold read path in local migrations (max `019_backfill_partitions.py`); Demo UI exists (`apps/demo/src/components/analytics-dashboard.tsx`) but backend envelope route not in this checkout | **medium** |

scores: {schema: PARTIAL, deps: PASS, scalability: PARTIAL, agent_clarity: PARTIAL}

agent_risks:
- Executor may create `gold.kpi_envelopes` greenfield and miss cutover from live `public.analytics_kpi_envelopes` (`kind` column, nested payload shape from #525)
- No named bronze/silver DDL for orders/returns (e.g. `silver.orders` columns, dedupe keys, bronze append table name)
- `webhook_raw_events` fate unspecified — agent may double-write or leave orphan raw table
- `analytics_performance_intervals` (6662 rows, silver-equivalent data) not in A0 cutover sequence — agent may defer all analytics to A1 and block envelope shell
- Scalability mechanics absent from PRD: JSONB GIN on `payload`, batch INSERT/COPY for bronze append, TOAST monitoring (`external-refs.md` notes but #598 silent)
- "Orchestrator boundary documented in A0" — no target doc path; agent may skip or over-build compute wiring (ADR-046 Q4 says A1 wires full stages)

---

## Verdict A1 #601
overall: PARTIAL

objectives:
- Deployed material webhook → ETL → enqueue shop-scoped fetch-then-precompute (not test-only)
- Targeted Partner fetch (event→resource map); Shared Compute Orchestrator bronze→silver→gold per material trigger
- Precompute exactly five Demo KPIs into `gold.kpi_envelopes.payload.kpis` (ADR-049); Redis read-through; public Demo GET
- Speed-path hygiene: A-7 poll + webhook #11 reconcile; A-38/A-39 persist-or-stop; A-31/A-33 fan-out guard
- Hourly Fujiwa Mock reconciler only; exit = webhook-driven `computed_at` advances for all five KPIs on Demo Analytics

as_built_gaps:
| claim | evidence | severity |
|-------|----------|----------|
| Deployed material handoff → compute enqueue | `TikTokWebhookService.handle` handoffs to ETL only (`webhook.py:169-170`); `EtlConsumer.before_persist` hook exists but unwired (`consumer.py:164-165`); no Material Compute Dispatcher module | **critical** |
| Targeted fetch (not full poll) | `run_fujiwa_poll_cycle` runs all `_FUJIWA_POLL_STEPS` + full `sync_analytics` A-31–A-39 (`orchestrate.py:74-229`); #532 explicitly reuses full poll steps — conflicts with A1 P0 | **critical** |
| Shared Compute Orchestrator | No orchestrator module; backfill uses separate partition runners (`analytics_backfill/orchestrator.py`); ETL writes silver-surrogate tables directly | **critical** |
| Five KPI precompute → gold | Local checkout lacks `analytics_kpi_precompute` / migration 020; live has `public.analytics_kpi_envelopes` but column detail not in `db-key-tables.txt`; artifacts show only GMV (#526) on origin/main | **critical** |
| Hourly Fujiwa reconciler | No Celery beat / hourly job found; only manual `run_fujiwa_poll_cycle` (`workers/services/polling/orchestrate.py`) | **high** |
| Shop-scoped idempotent speed jobs | ETL idempotency via `public.processed_events` (`consumer.py:156-162`); no compute-job dedupe/mutex/coalesce (#532 #68 15-min coalesce not implemented locally) | **high** |
| A-31/A-33 fan-out guard | `sync_analytics` in poll path; backfill forbids A-33 bucket (`orchestrator.py:36-37`) but routine poll has no guard | **high** |
| Redis envelope cache | No envelope cache module in backend grep; required per ADR-038/047 Serving layer | **high** |
| Medallion prerequisite (A0) | Blocked: all ingest/compute targets flat `public.*` | **critical** |

scores: {schema: FAIL, deps: PASS, scalability: PARTIAL, agent_clarity: PARTIAL}

agent_risks:
- Agent may implement #532 pattern (reuse `_FUJIWA_POLL_STEPS` + full `sync_analytics`) and violate A1 "targeted fetch only" scalability requirement
- Material webhook catalog IDs (#1,#2,#5,#12,#27,#39,#67,#68) live in #532 body, not #601 — agent may mis-classify triggers
- `metric_id` keys not enumerated in #601 (ADR-049 table names KPIs but not keys like `gmv_tiktok`; #525 uses `gmv_tiktok`)
- A-7 "poll + webhook #11 reconcile" scoped to A1 but ADR-046 puts A-7 merge in silver — overlap with A0 first-domain cutover unclear
- Postgres I/O budget correctly deferred to A2, but A1 PRD silent on bronze append volume under webhook bursts (batch inserts, connection pool limits)
- "Reuse existing transform/compute callables" points to `aggregates/computed_kpis.py` and flat-table reads — agent may skip medallion stages entirely

---

## Cross-cut A0↔A1
- **Dependency graph is correct:** A0 → A1 → #599; A2 parallel after A0 (`ADR-047`, both issue bodies). A1 correctly blocked on medallion foundation.
- **Legacy 2.10 debt spans both:** Live `public.analytics_kpi_envelopes` + Phase 2.10 precompute work (#525–#528) predates medallion; A0 must define rename/migrate/compatibility before A1 populates five keys.
- **Raw vs domain split unfinished:** `webhook_raw_events` + ETL direct-upsert pattern is pre-medallion; A0 first-domain cutover and A1 speed path both need the same bronze→silver promotion boundary.
- **Poll spine is the main scalability antagonist:** Current Fujiwa orchestration and #532 design are poll-heavy; A1 targeted fetch is the critical scalability differentiator but is underspecified vs existing code paths.
- **Budget split is ADR-correct:** Partner-only budget exists (`analytics_backfill/budget.py`); dual Partner + Postgres I/O budgets belong to A2 — not a gap in A0/A1 PRDs.
- **#599 Decisions blocking:** Correctly on **A1 Speed only**, not A0 or A2 (`issue-599.md` Comment 2, `ADR-047` §3). Stale wording in #599 assumptions ("Phase 3.5-A must exit") should be read as A1 per the 2026-07-30 split comment.

---

## Recommendations (max 8)
1. **Add explicit legacy→gold cutover spec to #598:** map `public.analytics_kpi_envelopes (shop_id, kind)` → `gold.kpi_envelopes (shop_id PK)` with compat view preserving `payload.kpis` shape.
2. **Name first-slice DDL in #598:** bronze append table(s), `silver.orders`/`silver.returns` keys, and whether `public.webhook_raw_events` moves to `bronze.*` or stays as read-only shim.
3. **Add scalability acceptance criteria to #598:** bronze `(shop_id, received_at)` indexing, batch append guidance, optional GIN on `gold.kpi_envelopes.payload` for future containment queries.
4. **Supersede #532 poll-reuse in #601:** state explicitly that `_FUJIWA_POLL_STEPS` full cycle is **forbidden** on material webhook path; link Targeted Fetch Planner event→resource matrix.
5. **Inline material webhook catalog + metric_id keys in #601:** catalog IDs (#1,#2,#5,#12,#27,#39,#67,#68 coalesce) and five `payload.kpis` keys aligned with ADR-049/#525.
6. **Split A-7 ownership:** A0 = silver schema + upsert contract; A1 = poll + webhook #11 reconcile logic and cancellation-rate KPI — one sentence each in both issues.
7. **Define hourly reconciler in #601:** Celery beat task, same orchestrator entrypoint, `enqueue_reason=reconcile_hourly`, Fujiwa shop allowlist only.
8. **Add one-writer module map to #598:** which service owns bronze append, silver upsert, gold envelope write post-cutover — prevents A1 agent writing gold from poll workers directly.
