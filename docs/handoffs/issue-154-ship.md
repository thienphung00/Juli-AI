# Handoff: ship complete — Issue #154

## Shipped

- Issue #154 — merged via PR #159
- Branch: `feature/issue-154-listing-rules-engine` — squash commit `e65c878`

## What shipped

- `web/src/lib/workflows/new-seller/listing/` — `generateProductDraft`, `canExportProductDraft`
- Deterministic extraction for manual form, URL stub, opportunity card
- Compliance (blocked categories, missing price) and readiness score (threshold 70)
- 7 jest tests; ADR-021; map.md deployed row

## Rollback

```bash
git revert e65c878
```

No migrations or runtime config.

## Follow-up work

- **#155** — E2E listing workflow UI (integrate rules engine at draft review)
- **#156** — CSV/JSON export (blocked when `compliance.status === blocked`)
