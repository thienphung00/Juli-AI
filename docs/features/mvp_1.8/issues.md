# MVP 1.8 — Phase 1.8 Issue Queue

**Parent PRD (orchestration):** Local [`PRD-orchestration.md`](PRD-orchestration.md) · GitHub parent issue: [#175](https://github.com/thienphung00/Juli-AI/issues/175)

**Design-system PRD (separate slice):** Local [`PRD.md`](PRD.md) · GitHub: [#174](https://github.com/thienphung00/Juli-AI/issues/174) (P1.8-8)

Process orchestration issues top-to-bottom. **#177** and **#178** can run in parallel after **#176**. **#174** (tokens) can run in parallel with Layer 0–1.

> **GitHub sync:** Authoritative Phase 1.8 orchestration issue set is **#175–#182** below (created 2026-06-12). Design polish remains **#174**.

| Order | Issue | Title | Type | Blocked by | EXECUTION slice | Modules |
|-------|-------|-------|------|------------|-----------------|---------|
| 0 | [#175](https://github.com/thienphung00/Juli-AI/issues/175) | PRD: MVP 1.8 — Operations-System Orchestration (P1.8-1…7) | AFK | — | (parent) | — |
| 1 | [#176](https://github.com/thienphung00/Juli-AI/issues/176) | Unified operational data model fixtures + traceability map | AFK | — | P1.8-2 | `mock-data/operations/` |
| 2 | [#177](https://github.com/thienphung00/Juli-AI/issues/177) | Shop profile classification + workflow catalog mapping | AFK | #176 | P1.8-1 | `operations/classification.ts` |
| 3 | [#178](https://github.com/thienphung00/Juli-AI/issues/178) | Health Check subsystem — `health_check_results` | AFK | #176 | P1.8-3 | `operations/health-check.ts` |
| 4 | [#179](https://github.com/thienphung00/Juli-AI/issues/179) | Workflow ranking + `useOperationsPipeline` hook | AFK | #177, #178 | P1.8-4 | `operations/recommendations.ts`, `use-operations-pipeline.ts` |
| 5 | [#180](https://github.com/thienphung00/Juli-AI/issues/180) | Rules-only reasoning panel — Why / Impact / Next Steps | AFK | #179 | P1.8-5 | `workflows/operations/` (reasoning) |
| 6 | [#181](https://github.com/thienphung00/Juli-AI/issues/181) | Unified approval gate + routing to P1.6/P1.7 executors | AFK | #180 | P1.8-6 | `SellerHomeShell`, `workflows/operations/` |
| 7 | [#182](https://github.com/thienphung00/Juli-AI/issues/182) | Outcome tracking — metrics + cadence tabs | AFK | #181 | P1.8-7 | `workflows/operations/` (outcomes) |
| — | [#174](https://github.com/thienphung00/Juli-AI/issues/174) | Design-system & interaction polish (P1.8-8) | AFK | — | P1.8-8 | `globals.css`, tokens, migration |

## Parallelization

After **#176** lands, **#177** (classification) and **#178** (health check) are disjoint pure-logic modules and may run in parallel per `issue-workflow.mdc`.

**#174** (design tokens) is independent of orchestration logic — land early so **#180–#181** UI builds on ADR-027 tokens from day one.

**#181** requires P1.7 executor integration (#167) merged and **#180** reasoning components ready. **#182** completes the exit gate loop (outcome views after approve/execute).

## ADR-026 constraints

- **In scope:** mock fixtures, rules-only classification/health/ranking/reasoning, unified approval shell, routing to listing + leakage panels only, outcome metrics mocked
- **Out of scope:** TikTok API, Postgres, ML, Ollama, Growth panel routing, standalone executors for Violations/Stockout/Budget/Scaling (P2-12…P2-15)
- **Traceability:** datum → workflow, indicator → workflow, recommendation → catalog — automate in tests

## Recommended implementation layers

| Layer | Issues | Focus |
|-------|--------|-------|
| 0 Foundation | #176, #177, #174 | Fixtures, classification, tokens |
| 1 Pure logic | #178, #179 | Health, ranking, pipeline hook (TDD) |
| 2 Pipeline UI | #180, #181, #182 | Shell, approval, routing, outcomes |
| 3 Polish | #174 (migration) | Screenshot re-baseline, high-traffic migration |

## P1.8-9 — Decision Copilot app structure (Phase 1.8.5)

**Parent PRD:** Local [`PRD-app-structure.md`](PRD-app-structure.md) · GitHub: [#190](https://github.com/thienphung00/Juli-AI/issues/190)

**White canvas:** Seller `--background` = `#FFFFFF` (not pink `#FEF5F6`); pink accent only ([#191](https://github.com/thienphung00/Juli-AI/issues/191)).

| Order | Issue | Title | Type | Blocked by | EXECUTION slice | Modules |
|-------|-------|-------|------|------------|-----------------|---------|
| 0 | [#190](https://github.com/thienphung00/Juli-AI/issues/190) | PRD: MVP 1.8.5 — Decision Copilot App Structure | AFK | — | (parent) | — |
| 1 | [#191](https://github.com/thienphung00/Juli-AI/issues/191) | White seller canvas + 3-tab nav + `/decisions` shell | AFK | — | P1.8-9 | `globals.css`, `nav-config.ts` |
| 2 | [#192](https://github.com/thienphung00/Juli-AI/issues/192) | Decision view-model | AFK | #179 | P1.8-9 | `lib/decisions/` |
| 3 | [#193](https://github.com/thienphung00/Juli-AI/issues/193) | Home read-only shell (hero + top-3 preview) | AFK | #178, #179, #191 | P1.8-9 | `HomeSummaryShell` |
| 4 | [#194](https://github.com/thienphung00/Juli-AI/issues/194) | Today's Report domain cards | AFK | #176, #193 | P1.8-9 | `home/todays-report/` |
| 5 | [#195](https://github.com/thienphung00/Juli-AI/issues/195) | Decisions Recommended + approval relocation | AFK | #180, #181, #191, #192 | P1.8-9 | `decisions/` |
| 6 | [#196](https://github.com/thienphung00/Juli-AI/issues/196) | Decision detail 5-step flow | AFK | #195 | P1.8-9 | `/decisions/[id]` |
| 7 | [#197](https://github.com/thienphung00/Juli-AI/issues/197) | In Progress sub-tab | AFK | #181, #195 | P1.8-9 | `decisions/` |
| 8 | [#198](https://github.com/thienphung00/Juli-AI/issues/198) | Workflow Templates sub-tab (mock) | AFK | #191 | P1.8-9 | `decisions/templates` |
| 9 | [#199](https://github.com/thienphung00/Juli-AI/issues/199) | Juli Chat decision context | AFK | #192 | P1.8-9 | `ai-chat/` |
| 10 | [#200](https://github.com/thienphung00/Juli-AI/issues/200) | Integration tests + MODULE.md + screenshots | AFK | #193, #195, #196 | P1.8-9 | tests, docs |

**Parallelization:** **#191** can start immediately (white canvas + nav). **#198** can run in parallel once **#191** lands. **#192** after **#179**. **#194** after **#193** (Home shell slot for Today's Report).

Coordinate with **#174**: white canvas in **#191** supersedes ADR-027 pink-tint seller background; **#174** migration must not reintroduce `#FEF5F6` on page surfaces.

## Next step

Orchestration spine: `focus` on **#176** (fixtures unblock classification, health, and traceability tests).

App structure: `focus` on **#191** (white canvas + 3-tab nav — unblocks Decisions shell work in parallel with orchestration Layer 1–2).
