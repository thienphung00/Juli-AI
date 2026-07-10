# Handoff: focus → tdd — Issue #119

## Issue

- **#119** — New Seller Copilot UI (mocked)
- **EXECUTION slice:** P1-2
- **Parent:** #113 · **Blocked by:** #114, #115, #117, #118 (all merged ✓)

## Acceptance criteria

- Checklist tasks render for new-seller persona (setup, list product, affiliate, first ad, etc.)
- Each task explains why it matters (Vietnamese copy from fixtures)
- First-sale milestone progress visible
- Approve/dismiss via shared executor; empty and completed states render without layout breaks
- Integration test: new-seller persona renders ≥3 tasks with Vietnamese titles
- Integration test: approve removes task from active queue
- No TikTok API calls

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1-2), `docs/architecture/system-design.md`, `docs/product/features/mvp_1.0/PRD.md` US 8–14 |
| Module | `web/MODULE.md` |
| Shell (read-only) | `web/src/components/seller-home/SellerHomeShell.tsx` |
| Shared tasks | `web/src/components/tasks/*`, `web/src/lib/task-executor/*` |
| Mock data | `web/src/lib/mock-data/seller-personas/fixtures/new-persona.ts` |
| Routing | `web/src/lib/seller-workflows.ts` (`workflowId: "new_seller"`) |

## Standards applied

- Reliability (integration tests, deterministic fixtures)
- Security (no buyer PII — fixtures use masked `buyer_***` IDs)
- Performance (bounded task lists from fixtures)
- Coding style: match existing `TaskCard` / `SellerHomeShell` patterns

## Plugin skills & MCP

- `/nextjs` — App Router, client components
- `/shadcn` — reuse existing card/badge patterns (no new component installs unless needed)
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** lib helpers → workflow panel → shell integration → tests

### New files

| File | Purpose |
|------|---------|
| `web/src/components/workflows/new-seller/NewSellerCopilotPanel.tsx` | Checklist header, first-sale milestone bar, delegates to `TaskQueue` |
| `web/src/components/workflows/new-seller/MilestoneProgress.tsx` | Visual progress toward first profitable sale (from persona profile + task completion) |
| `web/src/components/workflows/new-seller/index.ts` | Barrel export |
| `web/src/lib/workflows/new-seller/milestone.ts` | Pure helpers: compute milestone % from profile fields (orders, GMV) |
| `web/src/__tests__/test_new_seller_copilot.test.tsx` | Integration tests per acceptance criteria |

### Modified files

| File | Change |
|------|--------|
| `web/src/components/seller-home/SellerHomeShell.tsx` | When `workflow.workflowId === "new_seller"`, render `NewSellerCopilotPanel` instead of bare `TaskQueue` |
| `web/MODULE.md` | Document new public interfaces |

### Key patterns

- Reuse `TaskQueue` + `useTaskExecutor` — do not duplicate approve/dismiss logic
- Milestone copy in Vietnamese (e.g. "Tiến độ đơn hàng đầu tiên")
- Empty state: reuse or extend `task-queue-empty` messaging for completed checklist
- `copy_source: "mock"` already on tasks — display fixture `body` as justification

### Tests (TDD)

1. RED: new-seller persona shows ≥3 Vietnamese task titles
2. RED: milestone progress element visible with plausible label
3. RED: approve removes task from active queue
4. GREEN: minimal panel + shell branch
5. REFACTOR: extract milestone helper if needed

Run: `cd web && npm test -- --testPathPattern=test_new_seller_copilot`

## DO NOT touch

- `web/src/components/workflows/leakage/` — #120
- `web/src/lib/mock-data/seller-personas/fixtures/*` — unless test-only gap (prefer using existing `NEW_PERSONA`)
- Auth, mode-select, persona switcher — #118
- Backend / TikTok API
