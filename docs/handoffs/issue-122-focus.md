# Handoff: focus → tdd — Issue #122

## Issue

- **#122** — UX instrumentation
- **Parent:** #113 (MVP 1.0 PRD)
- **Slice:** P1-7

### Acceptance criteria

- Events emitted: `task_clicked`, `task_approved`, `task_dismissed`
- Payload includes `workflow`, `task_type`, `persona_id`, `session_id`; no PII
- Instrumentation wired into shared task card and all three workflow pages
- Analytics failures do not break approve/dismiss or navigation
- Unit tests assert events fire on click, approve, dismiss
- Engagement threshold definition documented

## Context loaded

- `EXECUTION.md` (P1-7)
- `docs/features/mvp_1.0/PRD.md` (user stories 43–47, observability)
- `web/MODULE.md`
- `web/src/lib/analytics.ts` (existing `juli:analytics` sink)
- `web/src/components/tasks/TaskCard.tsx`, `TaskQueue.tsx`
- `web/src/lib/task-executor/use-task-executor.ts`
- Workflow panels: new-seller, leakage, growth

## Standards applied

- Reliability — fail-silent analytics
- Observability — structured events, no PII
- Security — no buyer/shop names in payloads

## Implementation approach

1. Add `web/src/lib/ux-analytics/` — session id + `emitTaskUxEvent` wrapper
2. Extend `TaskCard` with `personaId` + `task_clicked` on card engagement
3. Extend `useTaskExecutor` with `personaId` + approve/dismiss events
4. Pass `personaId` through `TaskQueue` and workflow panels
5. Tests in `test_ux_instrumentation.test.tsx`
6. Document engagement threshold in PRD

## DO NOT touch

- Backend / `src/` Python modules
- Legacy recommendation analytics (`trackRecommendationAction`)
- Creator-matching route retirement (#123)
