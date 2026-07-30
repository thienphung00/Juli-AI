## Assumptions

- Architect split locked in [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md): **A0 Foundation** is medallion + serving only; **Speed (A1)** and **Batch (A2)** are separate PRDs.
- Grill handoff ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)) is authoritative for physical model; no re-interview.
- **Fujiwa Mock Demo reference shop only** for prove-out; OAuth / multi-tenant deferred (3.5-C / ADR-045).
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))** and **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** are separate tracks; B blocked on **A1 Speed**, not A0 or A2.
- A0 exit does **not** require deployed material webhook handoff or five Demo KPI precompute — those are **A1**.
- Live baseline today is flat `public.*` (including `analytics_kpi_envelopes`, `webhook_raw_events`, `analytics_backfill_partitions`) — A0 must **name the cutover**, not invent greenfield-only schemas that orphan existing tables.

## Problem Statement

Phase 2.10 locked a logical CDP spine (ADR-038) but Postgres tables still live in flat `public` with mixed raw, domain, and serving rows. Without enforced **bronze → silver → gold → ops** layering, the platform cannot scale multi-shop ingest, enforce one writer per table, or expose only serving surfaces to Supabase clients — blocking safe Speed and Batch layer work.

Prospective sellers and internal teams need a **stable serving gold contract** (`gold.kpi_envelopes` with flexible `payload.kpis`) and per-domain cutover path before continuous webhook freshness (A1) or fleet reconcile (A2) land.

## Solution

Ship **Phase 3.5-A0 Foundation** — medallion physical model + serving layer — per [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) and [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md):

1. **Four schemas:** `bronze.*` (append-only raw), `silver.*` (idempotent domain upserts), `gold.*` (serving + optional ML stub), `ops.*` (pipeline checkpoints).
2. **One-way deps + one writer per table:** bronze→silver→gold; no reverse writes; schema grants harden bronze/silver/ops to service-role only.
3. **Serving gold contract:** `gold.kpi_envelopes` with flexible **`payload.kpis`** map (Q3 — no per-KPI Postgres columns). Redis is **never** SoT (read-through only when A1 lands).
4. **ML gold stub:** `gold.ml_feature_snapshots` may be empty; ML reads **silver** only.
5. **Per-domain cutover:** schemas first, then domain-by-domain migration with bounded dual-write; compat view over gold OK; **no long-term dual-write**.
6. **Gold client exposure:** views/RPC + RLS for Demo/public read path; bronze/silver/ops unreachable to anon PostgREST.
7. **Shared Compute Orchestrator hooks:** job boundary documented (Q4) — implementation wired in **A1**; A0 proves schema + first domain cutover + empty or seed envelope row.

**Mock mode only:** production_read on Fujiwa; Sign-in disabled.

### Locked cutover design (Executor must not invent)

**Legacy → gold (serving):**
- Source: `public.analytics_kpi_envelopes` (`UNIQUE (shop_id, kind)`, jsonb `payload`).
- Target: `gold.kpi_envelopes` per ADR-046 Q3 — row keyed by **`shop_id`** (no long-term `kind` column as serving PK).
- Provide a **compat view** (or thin adapter) preserving `payload.kpis` shape for Demo/Track B during cutover.
- Bounded dual-write window only; then retire legacy writer. Do **not** greenfield `gold.kpi_envelopes` while leaving `public.analytics_kpi_envelopes` as a parallel SoT.

**First-slice DDL (orders / returns A-7):**
- Bronze append tables for material webhook + targeted-fetch raw payloads for orders/returns (names in migration; index at least `(shop_id, received_at)` or equivalent).
- `silver.orders`, `silver.returns` (or silver equivalents) with idempotent natural keys matching today’s domain upserts (`tiktok_order_id` / `tiktok_return_id` per shop).
- **A-7 ownership:** A0 lands silver schema + upsert contract; A1 owns poll + webhook #11 reconcile logic and `cancellation_rate` KPI population.

**`public.webhook_raw_events` fate (pick one; document in migration notes):**
1. Migrate/shim into `bronze.*` as the raw landing table, **or**
2. Keep as read-only audit shim with bronze as the write path going forward — **no indefinite double-write**.

**Ops (A0 exit AC):** Move `public.analytics_backfill_partitions` → `ops.analytics_backfill_partitions` (or equivalent) so A2 Batch consumes canonical ops home.

### One-writer module map (post-cutover)

| Layer / table | Owning module (words) | Readers |
|---------------|----------------------|---------|
| Bronze raw append (orders/returns payloads) | Ingest / ETL bronze writer | Silver promotion only |
| `silver.orders` / `silver.returns` | Domain silver upsert service | Gold compute, ML (future) |
| `gold.kpi_envelopes` | Shared Compute Orchestrator gold writer (**wired in A1**; A0 seeds empty/shell) | Demo/API, Redis cache (A1), Decisions (#599) |
| `ops.analytics_backfill_partitions` | Backfill / batch partition repo | A2 scheduler |
| `gold.ml_feature_snapshots` | Stub / empty OK | None required for A0 exit |

### Scalability ACs (foundation — not fleet governors)

- Bronze append path must support **batched** inserts (no row-at-a-time loops as the long-term pattern).
- Optional GIN / expression index plan on `gold.kpi_envelopes.payload` when containment queries are required (document if deferred to first query need).
- Fleet Postgres I/O **governors** belong to **A2**, not A0.

## User Stories

1. As a **platform operator**, I want four medallion schemas created with correct grants, so that layer isolation is enforceable before ingest cutover.
2. As a **platform operator**, I want `ops.*` pipeline tables migrated first when low-risk — including **`analytics_backfill_partitions`** — so that backfill partitions have a canonical home before A2.
3. As a **backend engineer**, I want `gold.kpi_envelopes` with flexible `payload.kpis` jsonb, so that KPI catalog swaps never require column migrations (ADR-046 Q3).
4. As a **backend engineer**, I want an explicit cutover from `public.analytics_kpi_envelopes` plus a compat view, so that Mock Demo stays green and Executors do not orphan the live table.
5. As a **backend engineer**, I want the first domain (orders + returns/cancellations A-7) cut over bronze→silver, so that cutover pattern is proven before Speed layer (A1).
6. As a **security reviewer**, I want bronze/silver/ops blocked from anon PostgREST, so that raw ingest is not public.
7. As a **Demo UI implementer (Track B)**, I want serving gold contract documented and reachable via compat view, so that #600 can consume `payload.kpis` shape before A1 populates five KPI keys.
8. As a **data platform owner**, I want one writer per table enforced by the module map above, so that dual-write drift cannot persist indefinitely.
9. As a **future ML engineer**, I want `gold.ml_feature_snapshots` stubbed and silver documented as feature SoT, so that ML gold fork rule is locked without blocking A0.
10. As a **product owner**, I want A0 exit independent of webhook enqueue, so that foundation merges before Speed/Batch parallel work.
11. As a **backend engineer**, I want `webhook_raw_events` fate decided in this PRD, so that A1 does not double-write raw.

## Implementation Decisions

- **Phase boundary:** A0 = medallion + serving contract + first domain cutover only ([ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md)).
- **Architecture:** [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) locked; builds on [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md), [ADR-043](docs/adr/043-cdp-webhook-first-spine-dual-credential.md).
- **Cutover sequence:** (1) schema bootstrap + grants, (2) **ops move of `analytics_backfill_partitions`**, (3) orders/returns → bronze→silver, (4) migrate/seed `gold.kpi_envelopes` from legacy envelope table + compat view, (5) retire legacy writers for migrated domain.
- **Orchestrator:** Q4 job boundary documented; full bronze→silver→gold stages wired in **A1 Speed**.
- **Demo KPI keys:** five KPI precompute is **A1** ([ADR-044](docs/adr/044-demo-analytics-main-kpi-override.md)); A0 may expose honest unavailable envelope shell with `payload.kpis` shape.
- **Credential model:** Mock production_read Fujiwa only; OAuth out of scope.

## Testing Decisions

- Schema existence, grant isolation (bronze/silver/ops not anon-readable), one-writer module ownership tests.
- First domain cutover integration: bronze append → silver upsert without gold KPI formula dependency.
- Compat view returns `payload.kpis` shape for reference shop; legacy `analytics_kpi_envelopes` not left as competing write SoT after cutover window.
- Ops partition table readable under `ops.*` after migration.
- No live Partner calls required for A0 exit in PR-safe lane.

## Out of Scope

- **A1 Speed** — deployed material handoff, targeted fetch, five Demo KPI precompute, hourly Fujiwa reconciler
- **A2 Batch** — daily staggered reconcile, dual budgets (Partner + Postgres I/O), cold-start fleet engine
- **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** — blocked on A1
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))**
- OAuth, Sign-in, seller_connect (3.5-C)
- Bestselling as Demo KPI; columnar warehouse
- Long-term dual-write to legacy `public.*`
- Fleet Postgres I/O governors (A2)

## Further Notes

- **Follow-ups:** [A1 Speed #601](https://github.com/thienphung00/Juli-AI/issues/601) after A0 exit; [A2 Batch #602](https://github.com/thienphung00/Juli-AI/issues/602) may parallel A1.
- **Rollout:** Schema migrations via Alembic + migration safety gate (ADR-027); verify Mock Demo reads compat view after first domain cutover.
- **Architect locks:** [ADR-046](docs/adr/046-cdp-medallion-physical-model.md), [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).
