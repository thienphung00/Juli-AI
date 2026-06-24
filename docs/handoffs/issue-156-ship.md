# Ship — Issue #156

## Shipped

- **PR:** https://github.com/thienphung00/Juli-AI/pull/161 (squash merged)
- **Branch:** `feature/issue-156-listing-export` (deleted)
- **Issue:** #156 closed

## What landed

- `exportProductDraft(draft, format)` — client-side CSV/JSON serialization
- `ExportBlockedError` + `canExportProductDraft` guard
- `ExportExecuteStep` in `ListingWorkflowPanel` — format picker, download, Vietnamese Seller Center success copy
- `trackExportCompleted` → `juli:analytics` `export_completed` event
- 5 new tests (3 unit + 2 E2E); ADR-023; map.md updated

## CI

All gates passed (frontend, validate-artifacts, status-check, 213 tests).

## Next in queue

- **#157** — Mock shop-progress tracking (listing milestone + task card widget)
