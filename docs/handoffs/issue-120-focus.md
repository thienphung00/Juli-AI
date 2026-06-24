# Handoff: focus → tdd — Issue #120

## Issue

- **#120** — Revenue Leakage Detection UI (mocked)
- **EXECUTION slice:** P1-3
- **Parent:** #113 · **Blocked by:** #114, #115, #117, #118 (all merged ✓)

## Acceptance criteria

- Leakage persona renders ranked anomaly tasks with severity and VND impact
- Drill-down shows supporting mock evidence (order IDs, return reasons, affiliate IDs — masked)
- Recommended fix visible per anomaly (task `body` + `cta_label`)
- Approve/dismiss via shared executor
- Empty state: "Không phát hiện rò rỉ tuần này" for persona with no signals
- Integration test: leakage persona renders anomalies with severity labels
- Integration test: drill-down opens evidence without PII fields
- No TikTok API calls

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1-3), `docs/system-design.md`, `docs/features/mvp_1.0/PRD.md` US 15–21 |
| Module | `web/MODULE.md` |
| Shell (read-only) | `web/src/components/seller-home/SellerHomeShell.tsx` |
| Shared tasks | `web/src/components/tasks/TaskCard.tsx` (severity + VND impact already rendered) |
| Mock data | `web/src/lib/mock-data/seller-personas/fixtures/leakage-persona.ts` |
| Schemas | `web/src/lib/mock-data/seller-personas/schemas.ts` (`evidence_refs`, returns, affiliate_events) |
| Routing | `web/src/lib/seller-workflows.ts` (`workflowId: "leakage"`) |

## Standards applied

- Reliability, security (**no buyer PII** — only masked IDs like `buyer_***1204`, `aff_***9912`)
- Maintainability — evidence resolver as pure function keyed by `evidence_refs`

## Plugin skills & MCP

- `/nextjs`, `/shadcn`
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

## Implementation approach

**Dependency order:** evidence resolver → leakage panel + drill-down → shell integration → tests

### New files

| File | Purpose |
|------|---------|
| `web/src/lib/workflows/leakage/resolve-evidence.ts` | Map `evidence_refs` → `{ orders, returns, affiliate_events }` slices from persona; assert no raw buyer PII |
| `web/src/components/workflows/leakage/LeakageCopilotPanel.tsx` | Anomaly list header, ranked tasks via `TaskQueue`, leakage-specific empty copy |
| `web/src/components/workflows/leakage/EvidenceDrawer.tsx` | Expandable drill-down per task showing masked evidence rows |
| `web/src/components/workflows/leakage/index.ts` | Barrel export |
| `web/src/__tests__/test_revenue_leakage_ui.test.tsx` | Integration tests per acceptance criteria |

### Modified files

| File | Change |
|------|--------|
| `web/src/components/seller-home/SellerHomeShell.tsx` | When `workflow.workflowId === "leakage"`, render `LeakageCopilotPanel` |
| `web/MODULE.md` | Document leakage workflow exports |

### Key patterns

- `TaskCard` already shows severity badge + `estimated_impact_vnd` — panel adds evidence drill-down on approve/CTA or "Xem bằng chứng" action
- Evidence drawer lists: order ID, return reason, affiliate ID (masked) — **never** full buyer phone/email/name
- Empty state copy: **"Không phát hiện rò rỉ tuần này"** when `activeTasks.length === 0` for leakage workflow
- Optional: add `EMPTY_LEAKAGE_PERSONA` fixture or filter tasks in test with a persona override — prefer test helper that loads leakage persona with `tasks: []` for empty-state test

### Tests (TDD)

1. RED: leakage persona shows severity labels on anomaly cards
2. RED: drill-down reveals evidence refs without PII field names (`phone`, `email`, unmasked buyer)
3. RED: empty state Vietnamese copy when no tasks
4. GREEN: panel + resolver + drawer
5. REFACTOR: consolidate evidence row rendering

Run: `cd web && npm test -- --testPathPattern=test_revenue_leakage_ui`

## DO NOT touch

- `web/src/components/workflows/new-seller/` — #119
- Persona switcher / stage router — #116/#118
- Backend / TikTok API
