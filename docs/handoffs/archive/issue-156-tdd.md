# Handoff: tdd → review — Issue #156

## Issue
- **#156** — CSV/JSON export — execute step from ProductDraft
- **Branch:** `feature/issue-156-listing-export`

## Implementation summary

| File | Change |
|------|--------|
| `web/src/lib/workflows/new-seller/listing/export.ts` | `exportProductDraft`, CSV/JSON serializers, `ExportBlockedError`, `downloadExportResult` |
| `web/src/lib/workflows/new-seller/listing/export-analytics.ts` | `trackExportCompleted` → `juli:analytics` |
| `web/src/lib/workflows/new-seller/listing/index.ts` | Re-export export surface |
| `web/src/lib/workflows/new-seller/listing/MODULE.md` | Updated public API docs |
| `ListingWorkflowPanel.tsx` | `ExportExecuteStep` — format picker, download, success copy (Vietnamese) |
| `web/src/__tests__/test_listing_export.test.ts` | 3 unit tests (JSON, CSV, blocked guard) |
| `web/src/__tests__/test_listing_workflow_ui.test.tsx` | Path A/B E2E through export + analytics |
| `docs/adr/023-listing-export-service.md` | ADR |
| `docs/architecture/map.md` | Export row updates |

## Acceptance criteria status

| Criterion | Status | Covered by |
|-----------|--------|------------|
| `exportProductDraft(draft, format)` returns valid CSV/JSON | ✓ | `test_listing_export.test.ts` |
| Export blocked when `compliance.status === blocked` | ✓ | unit test + UI disabled state |
| Execute step success message (Vietnamese manual upload) | ✓ | Path A E2E |
| Path A E2E through export | ✓ | `test_listing_workflow_ui.test.tsx` |
| Path B E2E through export | ✓ | `test_listing_workflow_ui.test.tsx` |
| JSON contains required fields | ✓ | unit test |
| Blocked draft throws error | ✓ | unit test |
| No TikTok API / Postgres | ✓ | UI-only; existing API mock assertions pass |
| `export_completed` analytics | ✓ | Path A E2E event assertion |

## Test results

```
38 suites, 213 tests — all passed
```

## Notes for review

- CSV uses dot-notation flat columns with pipe-delimited arrays — not TikTok bulk template
- Step id remains `export_placeholder` in state machine (minimal churn); UI testid is `listing-export-execute`
- `downloadExportResult` is DOM-only; tests mock `URL.createObjectURL` + anchor click

## DO NOT touch

- Rules engine logic (#154)
- Shop progress widget (#157)
