# TDD — Issue #157

## Branch
`feature/issue-157-shop-progress`

## Changes
- **New:** `web/src/lib/workflows/new-seller/shop-progress/` (tracker, session, milestone, hook)
- **New:** `web/src/components/workflows/new-seller/ListingProgressWidget.tsx`
- **Modified:** `MilestoneProgress`, `NewSellerCopilotPanel`, `ListingWorkflowPanel`, `export-analytics`
- **Docs:** `map.md`, shop-progress `MODULE.md`

## Tests
- `test_shop_progress.test.ts` — 8 unit tests (milestone, persistence, buckets)
- `test_listing_workflow_ui.test.tsx` — 4 integration tests (#157 AC)
- All 227 frontend tests passing

## Acceptance criteria
- [x] Export increments listing count — `recordExportCompleted`
- [x] MilestoneProgress bar 30% → 40% after export
- [x] Widget four states through happy path
- [x] Integration tests for count + widget transitions
- [x] `readiness_score_bucket` on `export_completed` event
- [x] Mock only — no TikTok API
