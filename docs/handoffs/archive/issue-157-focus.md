# Focus — Issue #157

## Issue
- **#157** — Mock shop-progress tracking — listing milestone + task card widget
- **Parent:** #152 · **Slice:** P1.6-5 · **Blocked by:** #156 (shipped)

## Acceptance criteria
- Successful export increments mock active listing count on seller persona profile
- `MilestoneProgress` progress bar updates after execute (3 → 4)
- Task card widget renders correct state enum: NoDistributor → DistributorKnown → DraftGenerated → Published-stub
- Integration tests for export increment + widget transitions
- Metrics: export rate + readiness score bucket via UX instrumentation
- No TikTok API; Published-stub is mock only

## Context loaded
- `docs/product/features/mvp_1.6/PRD.md` (P1.6-5 stories)
- `web/src/lib/workflows/new-seller/listing/` (#155–#156)
- `web/src/components/workflows/new-seller/` (copilot home)
- `docs/architecture/map.md`

## Implementation approach
- New `shop-progress` module: sessionStorage, persona-scoped
- `ListingProgressWidget` on copilot home
- Extend `MilestoneProgress` with Standard-status listing bar
- Wire `ListingWorkflowPanel` sync + `recordExportCompleted` on export
- Extend `trackExportCompleted` with `readiness_score_bucket`

## DO NOT touch
- Revenue Leakage / Growth copilot workflows
- TikTok API, Postgres, backend routes
- Rules engine / export serialization logic (#154–#156)
