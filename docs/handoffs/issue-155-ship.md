# Ship — Issue #155

## Shipped

- **PR:** https://github.com/thienphung00/Juli-AI/pull/160 (squash merged)
- **Branch:** `feature/issue-155-listing-workflow-ui` (deleted)
- **Issue:** #155 closed

## What landed

- Dual-path listing workflow modal from approved `list_products` task
- State machine: Path A (form → distributor → draft review) and Path B (constraints → opportunities → distributor → draft review)
- `useTaskExecutor` extension — only `list_products` launches workflow
- 8 integration tests + ADR-022 + map.md deployed row

## CI

All gates passed (frontend, validate-artifacts, status-check, 207+ tests).

## Next in queue

- **#156** — CSV/JSON export (blocked by #153, #154, #155 — now unblocked)
- **#157** — Mock shop-progress tracking
