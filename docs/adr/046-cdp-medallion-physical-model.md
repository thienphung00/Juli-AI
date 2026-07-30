# ADR-046: CDP medallion physical model — bronze / silver / gold / ops

**Status:** Accepted  
**Date:** 2026-07-30  
**Deciders:** grill-with-docs (Architect) — **Q1 approved** (physical model); **Q2 approved** (migration / cutover);
**Q3 approved** (serving gold envelope contract — flexible `payload`, not per-KPI columns);
**Q4 approved** (Shared Compute Orchestrator job boundary — one shop-scoped job per material trigger)

**Builds on:** [ADR-002](002-supabase-backend-service.md), [ADR-013](013-operations-pipeline-spine.md),
[ADR-029](029-phase-2.9-analytics-historical-backfill.md), [ADR-038](038-phase-2.10-dual-layer-pipeline.md),
[ADR-043](043-cdp-webhook-first-spine-dual-credential.md), [ADR-044](044-demo-analytics-main-kpi-override.md).  
**Amends:** [ADR-038](038-phase-2.10-dual-layer-pipeline.md) — names the Postgres **schema layers**
behind “raw → transform → precomputed envelopes”; [ADR-043](043-cdp-webhook-first-spine-dual-credential.md) —
physical home for webhook/targeted-fetch/reconcile/cold-start ingest and A-7 merge.  
**Relates to:** CDP slice **3.5-A0** (#598 — medallion foundation & serving gold), **3.5-A1 Speed**
 ([#601](https://github.com/thienphung00/Juli-AI/issues/601)) and **3.5-A2 Batch**
 ([#602](https://github.com/thienphung00/Juli-AI/issues/602)) ([ADR-047](047-cdp-lambda-layers-prd-split.md)), **3.5-B** (#599 —
Decisions on same compute trigger), **Demo UI fix** (#600 — separate Track B; consumes serving gold only).
**Lambda vs medallion:** bronze/silver/gold/ops are **storage layers**; Speed/Batch/Serving are
**freshness layers** — orthogonal naming ([ADR-047](047-cdp-lambda-layers-prd-split.md)).  
**Does not change:** Redis read-through (not SoT); webhook-first + targeted fetch policy (ADR-043);
Demo dual credential model; Phase 3.5-C OAuth/cold-start PRD (ADR-045); EXECUTION Phase 3.5 dashboard rebuild.

## Context

Phase 2.10 (ADR-038) locked the **logical** CDP spine — webhooks + fetch → raw Postgres →
transform/compute → precomputed KPI envelopes (+ Redis) — but tables still live in the default
`public` schema with mixed raw, domain, and serving rows. Phase 3.5-A needs a **physical model**
that scales to multi-shop ingest, enforces one writer per table, separates pipeline state from
customer data, and exposes only serving surfaces to Supabase clients — without adopting ClickHouse
or dual-write indefinitely.

Alternatives considered:

| Option | Outcome |
|--------|---------|
| Stay on flat `public` + ad hoc table names | Rejected — no layer enforcement, unclear RLS, dual-write drift |
| Postgres materialized views for gold | Rejected — refresh coupling, harder shop-scoped orchestration |
| Separate databases per layer | Rejected — ops cost, cross-layer joins, Supabase single-project constraint |
| **Medallion schemas in one Supabase Postgres (chosen)** | One project; schema-level isolation; incremental migration |

## Decision

1. **Four Postgres schemas in the existing Supabase project** — not separate databases:
   - **`bronze.*`** — append-only raw landing (webhook payloads, targeted Partner fetch rows,
     reconcile snapshots, cold-start backfill pages). No upserts that overwrite history.
   - **`silver.*`** — idempotent domain upserts after dedupe/normalize (orders, products,
     cancellations/A-7 merge, analytics intervals, etc.). One canonical row per domain key.
   - **`gold.*`** — precomputed **serving** and **ML** outputs forked from silver (see §4).
   - **`ops.*`** — pipeline state only (`analytics_backfill_partitions`, checkpoints,
     partition cursors). Not seller/customer data.

2. **Dependency rule (one-way):** `bronze → silver → gold`. No gold→silver or silver→bronze
   writes. **One writer per table** — a single service/module owns inserts/upserts for each
   table; readers may cross layers only downstream.

3. **Compute orchestration — not materialized views:** Shop-scoped jobs in the **Shared Compute
   Orchestrator** run bronze→silver→gold transforms. Gold tables are **written by compute jobs**,
   not maintained by Postgres `REFRESH MATERIALIZED VIEW`. Redis remains read-through cache of
   serving gold envelopes (ADR-038).

4. **Gold fork from silver (locked branch rule):**
   - **Serving gold:** `gold.kpi_envelopes` — Analytics/Decisions/Demo/Redis read model
     (successor to `analytics_kpi_envelopes` and related serving rows). **Physical shape and
     KPI flexibility rule:** [Serving gold envelope contract (Q3)](#serving-gold-envelope-contract-q3--locked).
   - **ML gold (stub allowed):** `gold.ml_feature_snapshots` — optional Phase 4/5 persistence
     for promoted artifact inputs. **ML training and inference read `silver.*` only** — never
     serving gold envelopes. The fork rule is locked now even if the ML gold table is empty/stubbed.

5. **Supabase exposure and RLS:**
   - **Expose only gold** to client roles — via views and/or RPC wrappers.
   - **`bronze`, `silver`, `ops` unreachable** to `anon` / PostgREST direct access.
   - **RLS on gold** — Mock/reference shop for public Demo now; session-bound `shop_id` when
     Login mode ships (ADR-043 / 3.5-C).

6. **Migration policy:** **Per-domain incremental cutover** — see [Migration / cutover](#migration--cutover-q2--locked). **No long-term dual-write.**

7. **Ingest paths map to bronze:**
   - Material webhooks → bronze append
   - Targeted fetch (ADR-043) → bronze append
   - Daily staggered reconcile → bronze append
   - Cold-start backfill (3.5-C) → bronze append with `ops` checkpoints

8. **Silver owns A-7 merge:** Cancellation/return domain normalization (poll + webhook #11
   reconcile) lands in silver upserts, not ad hoc gold-side joins.

## Migration / cutover (Q2 — locked)

**Principle:** Create schemas first, migrate **one domain at a time** through the medallion
layers. No big-bang table move. Demo/Mock must stay green for the full cutover.

### Schema bootstrap (first migration)

1. Alembic creates **`bronze`**, **`silver`**, **`gold`**, **`ops`** with service-role-only
   defaults on bronze/silver/ops; gold gets client-facing views/RPC + RLS as today.
2. No domain data moves until schemas + grants exist. **`ops.*`** may receive early moves
   (e.g. `analytics_backfill_partitions`) when low-risk.

### Per-domain cutover (not big-bang)

Each domain follows the same pattern in **issue-sized slices** (3.5-A / #598):

| Step | Action | Example (first slice) |
|------|--------|------------------------|
| 1 | Land raw in **bronze** (append-only) | Webhook + targeted-fetch payloads for orders |
| 2 | Promote to **silver** (idempotent upsert) | `silver.orders`, returns/cancellations (A-7 merge) |
| 3 | Fork to **gold** (compute write) | `gold.kpi_envelopes` from silver aggregates |
| 4 | Retire legacy **`public.*`** writer for that domain | Drop dual-write after bounded window |

Domains cut over independently — e.g. orders/returns → silver before or in parallel with
KPI envelope → `gold.kpi_envelopes`, but **each table** has its own short cutover window,
not a single fleet-wide flag day.

### Demo / Mock continuity during cutover

- **Serving reads stay on gold** — `apps/demo` and public Demo APIs read **`gold.kpi_envelopes`**
  (or a **temporary compatibility view** over gold that preserves the existing envelope
  contract until Track B #600 UI work lands).
- Mock/reference shop (`production_read`) must remain envelope-backed through cutover; no
  bronze/silver exposure to anon PostgREST.
- Track B (#600) does not block schema creation or per-domain backend cutover; UI consumes
  serving gold only.

### Dual-write boundary

- **Allowed:** a **short, per-table** cutover window where the orchestrator writes the new
  medallion table and a compatibility view (or thin adapter) keeps legacy readers working.
- **Forbidden:** indefinite parallel writes to `public.*` and `silver.*` / `gold.*` for the
  same domain key. When cutover completes for a table, the legacy writer stops and the old
  table/view is retired or becomes read-only shim until dropped.

### Bronze MVP scope for 3.5-A (#598)

**In scope for first prove-out:**

- Material **webhook** events + raw payloads → bronze append
- **Targeted Partner fetch** raw payloads for domains needed by the [ADR-044](044-demo-analytics-main-kpi-override.md)
  Demo Main KPI set → bronze append:
  - Orders / cancellations (A-7, webhook #11)
  - Product performance (A-34 — CTOR)
  - LIVE (A-28 — `live_hours`)
  - Shop performance (A-36 — GMV, AOV)

**Defer unless needed for Fujiwa prove-out:**

- Cold-start backfill pages → bronze (3.5-C / ADR-045)
- Daily staggered **reconcile** snapshots → bronze

If Fujiwa reference-shop envelopes require historical rows not covered by webhook + targeted
fetch alone, add reconcile/cold-start bronze **only for that gap** — do not block 3.5-A schema
and orders/KPI cutover on full 3.5-C scope.

### Suggested first cutover sequence (#598)

1. Schemas + grants + `ops` checkpoint moves (if any).
2. Orders (+ returns/cancellations A-7) → bronze → silver.
3. Compute → **`gold.kpi_envelopes`**; wire Demo/public read path to gold (compat view OK).
4. Retire legacy envelope/order writers for migrated domains.

Decisions wire (#599) attaches to the **same compute trigger** after serving gold is stable —
no second migration path.

## Shared Compute Orchestrator job boundary (Q4 — locked)

**Principle:** One **shop-scoped Shared Compute job** per **material trigger** (webhook,
targeted fetch completion, reconcile window, or scheduled refresh). Each job runs the full
medallion chain in **idempotent stages** — no partial gold writes without silver promotion.

### Per-trigger job stages (one orchestrator run)

| Stage | Action | Idempotency |
|-------|--------|-------------|
| 1 — Bronze | Append raw webhook/fetch payloads to `bronze.*` | Append-only; dedupe keys at silver |
| 2 — Silver | Upsert normalized domain rows (`silver.*`) | One canonical row per domain key |
| 3 — Gold | Write / refresh `gold.kpi_envelopes` (and Decisions inputs when #599 wires) | Full envelope rewrite or keyed upsert per shop |

**One job owns all three stages** for a given `(shop_id, trigger)` — not separate cron MV
refreshes or per-table gold writers. Decisions (#599) attaches to the **same compute trigger**
after serving gold is stable; no second migration path or parallel raw ingest.

### What one job does *not* do

- Cross-shop batching in a single job (each shop remains scoped)
- Visitor-triggered orchestrator runs on Mock Demo public reads
- Gold→silver or silver→bronze reverse writes
- Separate orchestrators per product layer (Analytics vs Decisions share the trigger)

## Serving gold envelope contract (Q3 — locked)

**Principle:** KPIs may be switched out over time. **Do not** hardcode one Postgres column per
B′ (or future) metric as the long-term schema. Serving gold stays stable; catalog contents evolve
inside a JSON payload.

### Table shape (`gold.kpi_envelopes`)

| Column | Role |
|--------|------|
| `shop_id` | Primary key — one envelope row per shop |
| `computed_at` | Shop-scoped envelope freshness; drives relative sync copy and live indicator |
| `envelope_version` | Contract/version stamp for readers (Demo, Decisions, Redis cache) |
| `payload` | **`jsonb`** (or equivalent) — all KPI entries live here |

### `payload` structure

- **`kpis`:** map keyed by **stable `metric_id`** (string) → per-metric object:
  - **`availability`** (required) — honest per-field state (`available` \| `unavailable` \| …);
    never fabricate values when unavailable
  - **`label`** (required) — seller-facing display name
  - **`series?`** — optional time series for chart cards
  - **`value?`** — optional scalar/structured current value when available
  - **`meta?`** — optional provenance, units, insight hints (not shop-readiness — see ADR-043)

The [ADR-044](044-demo-analytics-main-kpi-override.md) **Demo Main KPI set** (GMV, AOV, CTOR,
LIVE hours, Cancellation rate — **exactly five KPIs**; no sixth card) is the **initial catalog** —
first keys in `payload.kpis` for the reference shop — **not** frozen physical columns.
**Bestselling (A-38/A-39) is not** an initial serving-gold key (marketplace/platform metric ≠
merchant shop KPI).

### KPI swap policy (no gold column migration)

Adding, removing, or replacing a served KPI is a **catalog + payload** change only:

1. Add/remove/rename keys in `payload.kpis` (compute job writes the new map).
2. Update Demo/product catalog and ADR-044 (or successor ADR) when Demo selector changes.
3. **No** Alembic column add/drop on `gold.kpi_envelopes` per KPI swap.

Authenticated/dashboard catalogs may diverge from Demo B′ without schema churn — different
`metric_id` keys in the same payload shape.

### Cutover and Track B (#600)

During medallion cutover, a **compatibility view** (or thin RPC adapter) over
`gold.kpi_envelopes` may preserve legacy read paths. It must expose the **same flexible
payload shape** above — not a flattened per-KPI column projection — so Track B UI work (#600)
does not re-lock column names. Mock/reference shop stays envelope-backed through cutover.

### ML boundary (unchanged)

Serving `gold.kpi_envelopes` is **not** an ML feature source. Training and inference continue
to read **`silver.*` only**; optional `gold.ml_feature_snapshots` remains a separate fork.

## Consequences

- Alembic migrations gain schema creation (`CREATE SCHEMA IF NOT EXISTS …`) and
  `GRANT`/default-privilege hardening so bronze/silver/ops are service-role only.
- Issue **#598 (3.5-A0)** implements schema layout, serving gold contract, and first domain
  cutover; **A1 Speed** (ADR-047) adds webhook handoff + five Demo KPI precompute; **A2 Batch**
  adds fleet reconcile; **#599 (3.5-B)** reuses the same compute trigger into Decisions after
  A1 exits — no parallel raw path.
- **#600 (Demo UI)** stays Track B — UI reads serving gold via existing public Demo APIs;
  no bronze/silver exposure in `apps/demo`.
- `analytics_backfill_partitions` (and similar) **move to `ops.*`** over time; 2.9 backfill
  orchestrator continues to function during migration.
- ML module docs (`docs/ml/ml_layer.md`) should treat **silver** as feature-source SoT;
  `gold.ml_feature_snapshots` is optional acceleration, not the inference read path.
- Serving gold envelope contract is **locked** (Q3 — flexible `payload.kpis` map; ADR-044 B′ five
  as initial catalog keys, not DB columns). Shared Compute job boundary is **locked** (Q4 — one
  shop-scoped job per material trigger; bronze append → silver upsert → gold envelope write).
  Demo Main KPI catalog count is **locked at five** (Q5 — no sixth card; Bestselling removed).

## References

- Ubiquitous language: [`CONTEXT.md`](../../CONTEXT.md) — Bronze/Silver/Gold/Ops, one-writer rule,
  serving vs ML gold fork, **Serving KPI envelope contract** (Q3), **Shared Compute Orchestrator**
  job boundary (Q4).
- Pipeline spine: [ADR-038](038-phase-2.10-dual-layer-pipeline.md), [ADR-043](043-cdp-webhook-first-spine-dual-credential.md).
