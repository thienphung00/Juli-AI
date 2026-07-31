# Issue #598: Phase 3.5-A0: CDP medallion foundation & serving gold
State: OPEN
Labels: enhancement, PRD

## Assumptions

- Architect split locked in [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md): **A0 Foundation** is medallion + serving only; **Speed (A1)** and **Batch (A2)** are separate PRDs.
- Grill handoff ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)) is authoritative for physical model; no re-interview.
- **Fujiwa Mock Demo reference shop only** for prove-out; OAuth / multi-tenant deferred (3.5-C / ADR-050).
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))** and **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** are separate tracks; B blocked on **A1 Speed**, not A0 or A2.
- A0 exit does **not** require deployed material webhook handoff or five Demo KPI precompute — those are **A1**.

## Problem Statement

Phase 2.10 locked a logical CDP spine (ADR-038) but Postgres tables still live in flat `public` with mixed raw, domain, and serving rows. Without enforced **bronze → silver → gold → ops** layering, the platform cannot scale multi-shop ingest, enforce one writer per table, or expose only serving surfaces to Supabase clients — blocking safe Speed and Batch layer work.

Prospective sellers and internal teams need a **stable serving gold contract** (`gold.kpi_envelopes` with flexible `payload.kpis`) and per-domain cutover path before continuous webhook freshness (A1) or fleet reconcile (A2) land.

## Solution

Ship **Phase 3.5-A0 Foundation** — medallion physical model + serving layer — per [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) and [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md):

1. **Four schemas:** `bronze.*` (append-only raw), `silver.*` (idempotent domain upserts), `gold.*` (serving + optional ML stub), `ops.*` (pipeline checkpoints).
2. **One-way deps + one writer per table:** bronze→silver→gold; no reverse writes; schema grants harden bronze/silver/ops to service-role only.
3. **Serving gold contract:** `gold.kpi_envelopes` with flexible **`payload.kpis`** map (Q3 — no per-KPI Postgres columns).
4. **ML gold stub:** `gold.ml_feature_snapshots` may be empty; ML reads **silver** only.
5. **Per-domain cutover:** schemas first, then domain-by-domain migration with bounded dual-write; compat view over gold OK; **no long-term dual-write**.
6. **Gold client exposure:** views/RPC + RLS for Demo/public read path; bronze/silver/ops unreachable to anon PostgREST.
7. **Shared Compute Orchestrator hooks:** job boundary defined (Q4) — implementation wired in **A1**; A0 proves schema + first domain cutover + empty or seed envelope row.

**Mock mode only:** production_read on Fujiwa; Sign-in disabled.

## User Stories

1. As a **platform operator**, I want four medallion schemas created with correct grants, so that layer isolation is enforceable before ingest cutover.
2. As a **platform operator**, I want `ops.*` pipeline tables migrated first when low-risk, so that backfill partitions have a canonical home.
3. As a **backend engineer**, I want `gold.kpi_envelopes` with flexible `payload.kpis` jsonb, so that KPI catalog swaps never require column migrations (ADR-046 Q3).
4. As a **backend engineer**, I want a compat view preserving legacy read shapes during cutover, so that Mock Demo stays green while domains migrate.
5. As a **backend engineer**, I want the first domain (orders + returns/cancellations A-7) cut over bronze→silver, so that cutover pattern is proven before Speed layer (A1).
6. As a **security reviewer**, I want bronze/silver/ops blocked from anon PostgREST, so that raw ingest is not public.
7. As a **Demo UI implementer (Track B)**, I want serving gold contract documented and reachable via compat view, so that #600 can consume `payload.kpis` shape before A1 populates five KPI keys.
8. As a **data platform owner**, I want one writer per table enforced by module ownership, so that dual-write drift cannot persist indefinitely.
9. As a **future ML engineer**, I want `gold.ml_feature_snapshots` stubbed and silver documented as feature SoT, so that ML gold fork rule is locked without blocking A0.
10. As a **product owner**, I want A0 exit independent of webhook enqueue, so that foundation merges before Speed/Batch parallel work.

## Implementation Decisions

- **Phase boundary:** A0 = medallion + serving contract + first domain cutover only ([ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md)).
- **Architecture:** [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) locked; builds on [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md), [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md).
- **Cutover sequence:** (1) schema bootstrap + grants, (2) ops table moves if any, (3) orders/returns → bronze→silver, (4) seed or empty `gold.kpi_envelopes` + compat view, (5) retire legacy writers for migrated domain.
- **Orchestrator:** Q4 job boundary documented; full bronze→silver→gold stages wired in **A1 Speed**.
- **Demo KPI keys:** five KPI precompute is **A1** ([ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md)); A0 may expose honest unavailable envelope shell.
- **Credential model:** Mock production_read Fujiwa only; OAuth out of scope.

## Testing Decisions

- Schema existence, grant isolation (bronze/silver/ops not anon-readable), one-writer module ownership tests.
- First domain cutover integration: bronze append → silver upsert without gold KPI formula dependency.
- Compat view returns `payload.kpis` shape for reference shop.
- No live Partner calls required for A0 exit in PR-safe lane.

## Out of Scope

- **A1 Speed** — deployed material handoff, targeted fetch, five Demo KPI precompute, hourly Fujiwa reconciler
- **A2 Batch** — daily staggered reconcile, dual budgets, cold-start fleet engine
- **3.5-B Decisions ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** — blocked on A1
- **Track B Demo UI ([#600](https://github.com/thienphung00/Juli-AI/issues/600))**
- OAuth, Sign-in, seller_connect (3.5-C)
- Bestselling as Demo KPI; columnar warehouse
- Long-term dual-write to legacy `public.*`

## Further Notes

- **Follow-ups:** [A1 Speed #601](https://github.com/thienphung00/Juli-AI/issues/601) after A0 exit; [A2 Batch #602](https://github.com/thienphung00/Juli-AI/issues/602) may parallel A1.
- **Rollout:** Schema migrations via Alembic + migration safety gate (ADR-027); verify Mock Demo reads compat view after first domain cutover.
- **Architect locks:** [ADR-046](docs/adr/046-cdp-medallion-physical-model.md), [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).



## Comment 1

**Superseding catalog / medallion locks (2026-07-30):** Issue body updated to match accepted [ADR-049](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/049-demo-analytics-main-kpi-override.md) (exactly **five** Demo Main KPIs; Bestselling removed) and [ADR-046](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/046-cdp-medallion-physical-model.md) (bronze/silver/gold/ops, flexible `gold.kpi_envelopes.payload.kpis`, Shared Compute Orchestrator, per-domain cutover, no long-term dual-write). Decisions remain [#599](https://github.com/thienphung00/Juli-AI/issues/599) next.


## Comment 2

## Architect-approved PRD split (ADR-047)

Phase 3.5 Analytics CDP is now split using **Lambda Architecture** naming ([ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md)). Medallion schemas (`bronze`/`silver`/`gold`/`ops`) are **orthogonal** to Lambda layers (Speed / Batch / Serving).

### PRD slices

| PRD | Issue | Scope |
|-----|-------|--------|
| **3.5-A0 Foundation** | **#598** (this issue) | Medallion + serving gold; per-domain cutover; flexible `payload.kpis`; exit **without** full speed webhook path |
| **3.5-A1 Speed** | [#601](https://github.com/thienphung00/Juli-AI/issues/601) | OLTP-shaped: deployed material handoff → targeted fetch → Shared Compute → gold; **five Demo KPIs**; hourly Fujiwa only |
| **3.5-A2 Batch** | [#602](https://github.com/thienphung00/Juli-AI/issues/602) | OLAP-shaped: daily staggered reconcile, checkpoints, **Partner API + Postgres I/O budgets**; same gold writes |
| **3.5-B Decisions** | [#599](https://github.com/thienphung00/Juli-AI/issues/599) | Unchanged — blocked on **A1**, not A2 |
| **Demo UI Track B** | [#600](https://github.com/thienphung00/Juli-AI/issues/600) | Parallel; fixtures until A1 envelope keys land |

### Dependency graph

```
A0 (#598) ──→ A1 (#601) ──→ B (#599)
     │
     └──→ A2 (#602)     [may parallel A1 after A0]

#600 Demo UI  ∥  fixtures / A1 contract
```

**Former monolithic 3.5-A scope** moved: webhook handoff, five KPI precompute, hourly Fujiwa → **A1**; daily staggered reconcile, dual budgets → **A2**.

No columnar warehouse required for Phase 3.5 exit. Five Demo KPIs only (ADR-049); no Bestselling; OAuth out of scope.
