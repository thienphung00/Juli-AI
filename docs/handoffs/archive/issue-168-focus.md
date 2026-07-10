## Handoff: focus → tdd

### Issue
- #168 — Leakage integration tests + UX instrumentation
- Acceptance criteria: happy path × 4 task types through executor; PII guard; dismiss reasons; UX events; CI green

### Context Loaded
- Architecture: `EXECUTION.md` P1.7-5, `docs/product/features/mvp_1.7/PRD.md`
- Module docs: `web/src/lib/workflows/leakage/MODULE.md`
- Prior art: `test_listing_workflow_ui.test.tsx`, `test_task_executor_issue_167.test.tsx`, `export-analytics.ts`

### Implementation Approach
- Add `leakage-analytics.ts` (mirror `export-analytics.ts`)
- Wire events in `LeakageWorkflowPanel` + `use-task-executor`
- PII guard UI on evidence step when bundle fails check
- New `test_leakage_integration_issue_168.test.tsx`

### DO NOT Touch
- TikTok API, Postgres, listing/growth workflow logic
