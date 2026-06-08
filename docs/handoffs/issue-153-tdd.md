# Handoff: tdd → review — Issue #153

## Issue

- **#153** — Mock workflow fixtures — ProductDraft, Distributor, Opportunity catalogs

## Branch

- `feature/issue-153-listing-workflow-fixtures`

## Changes summary

- **New:** `web/src/lib/mock-data/listing-workflow/` (schemas, fixtures, validate, index, MODULE.md)
- **New:** `web/src/__tests__/test_listing_workflow_fixtures.test.ts`
- **Modified:** `docs/architecture/map.md` — deployed module row for listing-workflow

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_listing_workflow_fixtures.test.ts` — distributors | ≥5 records, ≥3 categories, stable UUID |
| `test_listing_workflow_fixtures.test.ts` — validate | Schema validation passes |
| `test_listing_workflow_fixtures.test.ts` — opportunities | ≥8 records, filter fields |
| `test_listing_workflow_fixtures.test.ts` — product drafts | Golden seeds, required fields |
| `test_listing_workflow_fixtures.test.ts` — source policy | P1.6-allowed sources only |

## Test results

- 5/5 new tests passing
- 191/191 full web suite passing

## Acceptance criteria status

- [x] Fixture module under `web/src/lib/mock-data/listing-workflow/` — implemented
- [x] `loadDistributors()` ≥5, ≥3 categories, stable UUIDs — tested
- [x] `loadOpportunities()` ≥8 with filter fields — tested
- [x] Sample `ProductDraft` seeds — 2 golden drafts
- [x] Unit test: counts and schema fields — covered
- [x] Unit test: P1.6 source policy — covered
- [x] MODULE.md + map.md row — added
- [x] No TikTok API / Postgres — static fixtures only

## Notes for reviewer

- Opportunity filter fields (`min_capital_vnd`, `max_capital_vnd`, `supports_dropship`) are P1.6 extensions on canonical `Opportunity` for Path B filtering
- `load*` functions return shallow copies to prevent accidental mutation
