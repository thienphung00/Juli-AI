# Handoff: focus → tdd — Issue #121

## Issue

- **#121** — Growth Copilot UI (mocked)
- **EXECUTION slice:** P1-4
- **Parent:** #113 · **Blocked by:** #114, #115, #117, #118 (all merged ✓)

## Acceptance criteria

- Growth persona renders ad performance summary from mock fixtures
- Scale and pause/cut recommendations cite metric justification (e.g., ROAS vs account average)
- Campaigns ranked by opportunity
- Approve/dismiss via shared executor
- Integration test: growth persona renders ≥2 ad tasks with metric citations
- Integration test: dismiss removes campaign task from active queue
- No TikTok API calls

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1-4), `docs/architecture/system-design.md`, `docs/product/features/mvp_1.0/PRD.md` US 22–27 |
| Module | `web/MODULE.md` |
| Shell (read-only) | `web/src/components/seller-home/SellerHomeShell.tsx` |
| Shared tasks | `web/src/components/tasks/*`, `web/src/lib/task-executor/*` |
| Mock data | `web/src/lib/mock-data/seller-personas/fixtures/growth-persona.ts` |
| Routing | `web/src/lib/seller-workflows.ts` (`workflowId: "growth"`) |

## Standards applied

- Reliability (integration tests, deterministic fixtures)
- Performance (bounded campaign/task lists from fixtures)
- Coding style: match `LeakageCopilotPanel` / `NewSellerCopilotPanel` patterns

## Plugin skills & MCP

- `/nextjs` — App Router, client components
- `/shadcn` — reuse existing card/badge patterns
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** lib helpers → summary component → growth panel → shell integration → tests

### New files

| File | Purpose |
|------|---------|
| `web/src/lib/workflows/growth/ad-summary.ts` | Pure helpers: aggregate spend, ROAS, CPC, conversions from `ad_campaigns` |
| `web/src/lib/workflows/growth/rank-tasks.ts` | Sort growth tasks by `estimated_impact_vnd` descending |
| `web/src/components/workflows/growth/AdPerformanceSummary.tsx` | Account-level ad metrics card |
| `web/src/components/workflows/growth/GrowthCopilotPanel.tsx` | Summary + ranked scale/cut tasks via shared executor |
| `web/src/components/workflows/growth/index.ts` | Barrel export |
| `web/src/__tests__/test_growth_copilot.test.tsx` | Integration tests per acceptance criteria |

### Modified files

| File | Change |
|------|--------|
| `web/src/components/seller-home/SellerHomeShell.tsx` | When `workflow.workflowId === "growth"`, render `GrowthCopilotPanel` |
| `web/MODULE.md` | Document growth workflow exports |

### Key patterns

- Reuse `useTaskExecutor` + `TaskCard` — do not duplicate approve/dismiss logic
- Task `body` from fixtures already cites ROAS/CPC — display as justification
- Rank tasks by `estimated_impact_vnd` before rendering
- Ad summary reads from `persona.ad_campaigns` + `profile.ad_spend_30d_vnd`

### Tests (TDD)

1. RED: growth persona shows ad performance summary (spend, ROAS, CPC, conversions)
2. RED: ≥2 ad tasks with metric citations (ROAS/CPC in body)
3. RED: tasks ranked by opportunity (highest impact first)
4. RED: dismiss removes task from active queue
5. GREEN: panel + helpers + shell branch
6. REFACTOR: consolidate metric formatting if needed

Run: `cd web && npm test -- --testPathPattern=test_growth_copilot`

## DO NOT touch

- `web/src/components/workflows/new-seller/` — #119
- `web/src/components/workflows/leakage/` — #120
- Auth, mode-select, persona switcher — #118
- Backend / TikTok API
