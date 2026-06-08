# ADR 024: Shop Progress Tracker — Session-Scoped Listing Milestone

## Status
Accepted

## Context

- [ADR-020](020-new-seller-listing-workflow-scope.md) requires shop-progress bar updates
  after execute and a task-card widget tracking listing journey toward 10-listing
  Standard status.
- Issues #155 (workflow UI) and #156 (export) shipped the E2E chain through export;
  #157 completes the Phase 1.6 exit gate with mock progress tracking.
- New-seller persona fixture baseline is 3 active SKU (`catalog:sku_count=3`).

## Decision

- We will: add `web/src/lib/workflows/new-seller/shop-progress/` with persona-scoped
  `sessionStorage` persistence for `activeListingCount` and widget state enum
  (`no_distributor` → `distributor_known` → `draft_generated` → `published_stub`).
- We will: increment listing count and set `published_stub` atomically in
  `recordExportCompleted` on successful export (no TikTok API).
- We will: render `ListingProgressWidget` on copilot home and extend
  `MilestoneProgress` with a Standard-status listing bar (10-listing target).
- We will: sync widget state from listing workflow steps via
  `syncShopProgressFromWorkflow`, with a guard preventing downgrade from
  `published_stub`.
- We will: extend `export_completed` analytics with `readiness_score` and
  `readiness_score_bucket` (low / medium / high).
- We will not: call TikTok Products API, write to Postgres, or perform real publish.

## Rationale

Session-scoped storage matches ADR-020 P1.6 persistence constraints and keeps demos
refresh-safe within a browser session. Separating tracker logic from UI components
allows unit tests on public functions while integration tests prove E2E behavior.
`published_stub` naming makes mock-only publish explicit for reviewers and sellers.

## Consequences

- **Positive:** Completes Phase 1.6 exit gate — progress bar and widget update after execute.
- **Negative:** Listing count resets when sessionStorage is cleared (acceptable for P1.6 demos).
- **Follow-ups:** Persist shop progress in Postgres persona profile (P2); Products API publish (P2-8).
