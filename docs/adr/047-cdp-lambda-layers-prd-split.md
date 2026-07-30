# ADR-047: CDP Lambda layers and Phase 3.5 Analytics PRD split (A0 / A1 / A2)

**Status:** Accepted  
**Date:** 2026-07-30  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-038](038-phase-2.10-dual-layer-pipeline.md), [ADR-043](043-cdp-webhook-first-spine-dual-credential.md),
[ADR-044](044-demo-analytics-main-kpi-override.md), [ADR-046](046-cdp-medallion-physical-model.md).  
**Amends:** [ADR-043](043-cdp-webhook-first-spine-dual-credential.md) — names **Speed** vs **Batch**
compute paths and PRD sequencing; [ADR-046](046-cdp-medallion-physical-model.md) — clarifies that
medallion schemas are **orthogonal** to Lambda layer naming; splits former monolithic **3.5-A**
into three PRD slices.  
**Relates to:** **3.5-A0 Foundation** ([#598](https://github.com/thienphung00/Juli-AI/issues/598)),
**3.5-A1 Speed** ([#601](https://github.com/thienphung00/Juli-AI/issues/601)),
**3.5-A2 Batch** ([#602](https://github.com/thienphung00/Juli-AI/issues/602)),
**3.5-B** ([#599](https://github.com/thienphung00/Juli-AI/issues/599)),
**Demo UI fix** Track B ([#600](https://github.com/thienphung00/Juli-AI/issues/600)).  
**Does not change:** Medallion four-schema layout (ADR-046); flexible `gold.kpi_envelopes.payload.kpis`
(Q3); Shared Compute Orchestrator job boundary (Q4); Demo Main KPI set of **exactly five** (ADR-044);
OAuth / Sign-in scope (3.5-C / ADR-045); columnar warehouse requirement.

## Context

Phase 3.5 Analytics CDP work was filed as a single **3.5-A** PRD ([#598](https://github.com/thienphung00/Juli-AI/issues/598))
bundling medallion foundation, webhook-first speed path, reconcile/batch backstop, and five Demo KPI
precompute. That coupling made exit gates ambiguous (schema cutover vs continuous freshness vs fleet
reconcile) and blocked **3.5-B** Decisions on an oversized prerequisite.

[ADR-046](046-cdp-medallion-physical-model.md) locked the **medallion physical model**
(`bronze` / `silver` / `gold` / `ops`) — a **storage and dependency** layout. Separately, the product
needs **Lambda Architecture** naming for **how freshness is produced**:

| Lambda layer | Shape | Role in Juli CDP |
|--------------|-------|------------------|
| **Speed layer** | OLTP-shaped — event-driven, low-latency | Material webhook handoff → targeted fetch → Shared Compute → `gold.kpi_envelopes` |
| **Batch layer** | OLAP-shaped — scheduled, throughput-oriented | Daily staggered reconcile, cold-start checkpoints, partition backfill — same gold writes |
| **Serving layer** | Read model | `gold.kpi_envelopes` (+ Redis read-through); product reads gold only |

Speed and Batch are **orthogonal to medallion layers**: both paths run bronze→silver→gold through
the Shared Compute Orchestrator; they differ in **trigger and budget**, not in schema names.
Neither path requires a columnar warehouse now — Postgres medallion + Redis remains the serving stack.

Alternatives considered:

| Option | Outcome |
|--------|---------|
| Keep monolithic 3.5-A PRD | Rejected — unclear exit; Decisions blocked on batch scope |
| Separate databases for Speed vs Batch | Rejected — violates ADR-046 single Supabase project |
| ClickHouse / warehouse for Batch now | Rejected — deferred; Postgres batch jobs sufficient for Phase 3.5 |
| **Three PRD slices A0 / A1 / A2 (chosen)** | Foundation → Speed → optional Batch parallel; clear gates |

## Decision

### 1. Lambda layer definitions (locked)

1. **Serving layer:** `gold.kpi_envelopes` (flexible `payload.kpis` per ADR-046 Q3) plus required
   Redis read-through. Analytics, Decisions, and Demo read **serving gold only** — not speed/batch
   job queues or bronze/silver tables.

2. **Speed layer (OLTP-shaped):** Deployed material webhook handoff → ETL → enqueue → **targeted
   Partner fetch** → Shared Compute Orchestrator (bronze append → silver upsert → gold envelope
   write). Primary freshness driver for Mock Fujiwa prove-out. **Hourly Mock reference-shop reconcile**
   remains the narrow speed-adjacent exception (single tenant, ADR-043).

3. **Batch layer (OLAP-shaped):** **Daily staggered per-shop reconcile**, cold-start checkpoint
   pages (when required), and partition-resumable backfill — scheduled throughput jobs that write the
   **same** `gold.kpi_envelopes` via the same orchestrator stages. Governed by **two budgets:**
   - **Partner API budget** — rate limits, call caps per credential+endpoint
   - **Postgres I/O budget** — write/read pressure on bronze/silver promotion

4. **Orthogonality:** Medallion = where data lives; Lambda = how freshness is scheduled. A speed
   job and a batch job both append bronze, upsert silver, and write gold — they must not fork KPI
   formulas or maintain parallel serving tables.

### 2. PRD slice split (locked)

| PRD | Name | Scope | Exit gate | Depends on |
|-----|------|-------|-----------|------------|
| **3.5-A0** | Foundation — Medallion + serving | `bronze`/`silver`/`gold`/`ops` schemas; flexible `gold.kpi_envelopes`; per-domain one-writer cutover (ADR-046); gold client exposure; ML gold stub OK | Schemas + first domain cutover + serving gold contract live; **no** full speed webhook path required | — |
| **3.5-A1** | Speed layer | Deployed material handoff → targeted fetch → Shared Compute → gold; **five Demo KPIs** (ADR-044); hourly Fujiwa only | Webhook-driven `computed_at` advances on Demo Analytics for B′ five KPIs | **A0** |
| **3.5-A2** | Batch layer | Daily staggered reconcile; cold-start checkpoints when needed; dual budgets (Partner API + Postgres I/O); batch writes same gold | Fleet backstop scheduler + budget guards proven; reconcile heals gaps without speed-path duplication | **A0**; may **parallel A1** after A0 |
| **3.5-B** | Decisions | Rules scoring on shared compute trigger ([#599](https://github.com/thienphung00/Juli-AI/issues/599)) | Decision feed freshness on continuous spine | **A1** (not full A2) |
| **Demo UI** | Track B ([#600](https://github.com/thienphung00/Juli-AI/issues/600)) | CDP-honest Analytics + Decision automation UX | Browser-verified Demo | Parallel; fixtures until A1 contract |

### 3. Dependency graph (locked)

```
A0 (Foundation) ──→ A1 (Speed) ──→ B (Decisions #599)
       │
       └──→ A2 (Batch)     [parallel with A1 after A0]

#600 Demo UI  ∥  fixtures / A1 envelope contract
```

- **3.5-B ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** is blocked on **A1 Speed**
  exit — Decisions need continuous KPI envelopes from the speed path, not full batch fleet reconcile.
- **A2 Batch** does not block B or Demo UI exit.
- **Read-replica isolation** for cold-start fleet scale is **Phase 3 / 3.5-C** scope — not an A2 exit
  requirement (ADR-045 C2).

### 4. Scope moves from former monolithic 3.5-A

| Former #598 theme | New home |
|-------------------|----------|
| Medallion schema bootstrap, grants, RLS | **A0** |
| Per-domain cutover, compat view | **A0** |
| `gold.kpi_envelopes` flexible payload | **A0** (contract) + **A1** (five KPI keys populated) |
| Deployed material handoff + targeted fetch | **A1** |
| A-7 cancellations, A-38/A-39 ops guard, fan-out guard | **A1** (speed-path ingest hygiene) |
| Five Demo Main KPI precompute | **A1** |
| Hourly Fujiwa reconciler | **A1** (narrow Mock exception) |
| Daily staggered reconcile scheduler | **A2** |
| Cold-start bronze/checkpoints (fleet) | **A2** (when gap requires; full engine 3.5-C) |
| Partner API + Postgres I/O budgets | **A2** |

### 5. Explicit non-requirements

- **No columnar warehouse** for Phase 3.5 Analytics exit.
- **No OAuth / seller_connect** in A0–A2 (ADR-043, ADR-045).
- **No Bestselling (A-38/A-39)** as Demo KPI — five KPIs only (ADR-044).
- **ML gold stub** (`gold.ml_feature_snapshots`) allowed empty in A0; ML reads **silver** only.

## Consequences

- GitHub **#598** retitled and trimmed to **Phase 3.5-A0: CDP medallion foundation & serving gold**; **#601** (A1 Speed) and **#602** (A2 Batch) filed as full PRD issues.
- Comments on #598, #599, #600 document the split and dependency graph.
- [CONTEXT.md](../../CONTEXT.md) gains **Speed layer**, **Batch layer**, **Serving layer (CDP Lambda)**
  terms; **CDP slice 3.5-A** term updated to reference A0/A1/A2.
- Implementation issues should label slice (`3.5-A0`, `3.5-A1`, `3.5-A2`) in titles or bodies.
- Release-evidence plans for public Demo/API changes remain required per ADR-035 when A1 wiring ships.

## References

- Ubiquitous language: [`CONTEXT.md`](../../CONTEXT.md) — Speed/Batch/Serving layers, medallion model.
- Physical model: [ADR-046](046-cdp-medallion-physical-model.md).
- Ingest policy: [ADR-043](043-cdp-webhook-first-spine-dual-credential.md).
- Demo KPI catalog: [ADR-044](044-demo-analytics-main-kpi-override.md).
