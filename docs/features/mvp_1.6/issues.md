# MVP 1.6 — Phase 1.6 Issue Queue

**Parent PRD:** Local [`PRD.md`](PRD.md) · GitHub parent issue: [#152](https://github.com/thienphung00/Juli-AI/issues/152)

Process issues top-to-bottom. **#154** and **#155** can run in parallel after **#153**.

> **GitHub sync:** Authoritative Phase 1.6 issue set is **#152–#157** below (created 2026-06-08).

| Order | Issue | Title | Type | Blocked by | EXECUTION slice | Modules |
|-------|-------|-------|------|------------|-----------------|---------|
| 0 | [#152](https://github.com/thienphung00/Juli-AI/issues/152) | PRD: MVP 1.6 — Phase 1.6 New Seller Listing Workflow | AFK | — | (parent) | — |
| 1 | [#153](https://github.com/thienphung00/Juli-AI/issues/153) | Mock workflow fixtures — ProductDraft, Distributor, Opportunity catalogs | AFK | — | P1.6-1 | `mock-data/listing-workflow` |
| 2 | [#154](https://github.com/thienphung00/Juli-AI/issues/154) | Rules-based listing generation — extraction, compliance, readiness score | AFK | #153 | P1.6-3 | `workflows/new-seller/listing` (rules) |
| 3 | [#155](https://github.com/thienphung00/Juli-AI/issues/155) | E2E listing workflow UI — dual-path state machine from approved list_products | AFK | #153 | P1.6-2 | `workflows/new-seller/listing` (UI) |
| 4 | [#156](https://github.com/thienphung00/Juli-AI/issues/156) | CSV/JSON export — execute step from ProductDraft | AFK | #153, #154, #155 | P1.6-4 | export service |
| 5 | [#157](https://github.com/thienphung00/Juli-AI/issues/157) | Mock shop-progress tracking — listing milestone + task card widget | AFK | #156 | P1.6-5 | progress tracker, task card widget |

## Parallelization

After **#153** lands, **#154** (rules engine) and **#155** (UI shell + state machine) are disjoint and may run in parallel per `issue-workflow.mdc`. **#155** should integrate **#154** at draft review before **#156** export work begins.

**#156** requires both paths demoable through draft review. **#157** completes the exit gate (progress bar + widget after execute).

## ADR-020 constraints

- **In scope:** mock fixtures, rules-only generation, client-side export, session-scoped state
- **Out of scope:** cloud LLM, Postgres, TikTok API, approval queue (P2-7), Products API publish (P2-8)

## Next step

`focus` on **#153** (fixtures unblock all downstream slices).
