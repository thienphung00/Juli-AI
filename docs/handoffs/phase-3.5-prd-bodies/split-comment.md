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
