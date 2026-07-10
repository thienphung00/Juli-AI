# MVP 1.7 — Phase 1.7 Issue Queue

**Parent PRD:** Local [`PRD.md`](PRD.md) · GitHub parent issue: [#163](https://github.com/thienphung00/Juli-AI/issues/163)

Process issues top-to-bottom. **#165** and **#166** can run in parallel after **#164**.

> **GitHub sync:** Authoritative Phase 1.7 issue set is **#163–#168** below (created 2026-06-08).

| Order | Issue | Title | Type | Blocked by | EXECUTION slice | Modules |
|-------|-------|-------|------|------------|-----------------|---------|
| 0 | [#163](https://github.com/thienphung00/Juli-AI/issues/163) | PRD: MVP 1.7 — Phase 1.7 Revenue Leakage Executable Workflow | AFK | — | (parent) | — |
| 1 | [#164](https://github.com/thienphung00/Juli-AI/issues/164) | Leakage workflow fixtures + persona alignment | AFK | — | P1.7-1 | `mock-data/leakage-workflow`, `leakage-persona.ts` |
| 2 | [#165](https://github.com/thienphung00/Juli-AI/issues/165) | Leakage state machine + `useLeakageWorkflow` hook | AFK | #164 | P1.7-2 | `workflows/leakage/state-machine.ts`, `use-leakage-workflow.ts` |
| 3 | [#166](https://github.com/thienphung00/Juli-AI/issues/166) | `LeakageWorkflowPanel` modal UI — four task-type step renderers | AFK | #164 | P1.7-3 | `components/workflows/leakage/LeakageWorkflowPanel.tsx` |
| 4 | [#167](https://github.com/thienphung00/Juli-AI/issues/167) | Executor integration — approve opens workflow; global skip-with-reason | AFK | #165, #166 | P1.7-4 | `use-task-executor.ts`, `TaskCard`, dismiss modal |
| 5 | [#168](https://github.com/thienphung00/Juli-AI/issues/168) | Leakage integration tests + UX instrumentation | AFK | #167 | P1.7-5 | `web/src/__tests__/`, `ux-analytics` |

## Parallelization

After **#164** lands, **#165** (state machine) and **#166** (panel + step renderers) are disjoint and may run in parallel per `issue-workflow.mdc`. **#166** should integrate `useLeakageWorkflow` from **#165** before **#167** executor work begins.

**#167** requires all four task types demoable through execute step. **#168** completes the exit gate (happy path × 4, PII guard, step events, dismiss reasons).

## ADR-025 constraints

- **In scope:** mock fixtures, rules-only copy, modal workflow, global skip-with-reason, session-scoped state
- **Out of scope:** TikTok API, Postgres, ML inference, Ollama, `/leakage/*` routes, P2-9/P2-10

## Next step

`focus` on **#164** (fixtures unblock all downstream slices).
