# Handoff: focus → tdd — Issue #153

## Issue

- **#153** — Mock workflow fixtures — ProductDraft, Distributor, Opportunity catalogs
- **EXECUTION slice:** P1.6-1
- **Parent:** #152 · **Blocked by:** none

## Acceptance criteria

- Fixture module under `web/src/lib/mock-data/listing-workflow/` with typed schemas matching canonical entities
- `loadDistributors()` returns ≥5 records with stable UUIDs across ≥3 categories
- `loadOpportunities()` returns ≥8 records with deterministic filter fields (capital, category, dropship)
- Sample `ProductDraft` seed(s) for golden tests
- Unit test: loader counts and required schema fields
- Unit test: all `source` enums are `internal_curated` or `research` only (no `marketplace_api` in P1.6)
- MODULE.md or `map.md` row when module lands
- No TikTok API calls; no Postgres writes

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.6-1), `docs/architecture/system-design.md` §7, `docs/architecture/map.md`, `docs/architecture/data-sources.md` |
| Data models | `docs/api/data-models/canonical-entities.md` § Workflow entities |
| Decisions | `docs/adr/020-new-seller-listing-workflow-scope.md` |
| Prior art | `web/src/lib/mock-data/seller-personas/` (schemas, fixtures, validate, index) |
| Module | `web/MODULE.md` |

## Standards applied

- Reliability — fail-fast loaders, deterministic stable IDs
- Security — no PII, no forbidden `source` values per ADR-020 / data-sources policy
- Maintainability — mirror seller-personas module layout; small public loaders

## Plugin skills & MCP

- None required (client-side mock JSON only)
- shadcn / Supabase / TikTok API not in scope

## Implementation approach

**Dependency order:** schemas → fixture data → validate → public loaders → tests → MODULE.md + map.md

### New files

| File | Purpose |
|------|---------|
| `web/src/lib/mock-data/listing-workflow/schemas.ts` | ProductDraft, Distributor, Opportunity types |
| `web/src/lib/mock-data/listing-workflow/fixtures/distributors.ts` | ≥5 stable distributor records |
| `web/src/lib/mock-data/listing-workflow/fixtures/opportunities.ts` | ≥8 opportunity records + filter fields |
| `web/src/lib/mock-data/listing-workflow/fixtures/product-drafts.ts` | Golden ProductDraft seeds |
| `web/src/lib/mock-data/listing-workflow/validate.ts` | Schema validation helpers |
| `web/src/lib/mock-data/listing-workflow/index.ts` | `loadDistributors`, `loadOpportunities`, `loadProductDrafts` |
| `web/src/lib/mock-data/listing-workflow/MODULE.md` | Module contract |
| `web/src/__tests__/test_listing_workflow_fixtures.test.ts` | AC tests |

### Modified files

| File | Change |
|------|--------|
| `docs/architecture/map.md` | Move listing-workflow from planned → deployed row |

### Key patterns

- Follow `seller-personas` colocation: schemas + fixtures + validate + thin index loaders
- Stable UUIDs as fixed strings (e.g. `a1000001-0001-4000-8000-000000000001`) for golden tests
- P1.6 `source` guard: `assertP16AllowedSources()` used in tests; fixtures only use `internal_curated` | `research`
- Opportunity filter fields: `min_capital_vnd`, `max_capital_vnd`, `category`, `supports_dropship` on fixture records (P1.6 Path B filtering)

### Tests (TDD)

1. RED: `loadDistributors` count ≥5, ≥3 distinct categories, stable IDs
2. RED: `loadOpportunities` count ≥8, filter fields present
3. RED: `loadProductDrafts` returns valid golden seeds
4. RED: no forbidden `source` enums in P1.6 fixtures
5. GREEN: implement fixtures + loaders + validate

## DO NOT touch

- Listing workflow UI (#155), rules engine (#154), export (#156)
- Backend / Postgres / TikTok API
- Other copilot workflows (leakage, growth)
