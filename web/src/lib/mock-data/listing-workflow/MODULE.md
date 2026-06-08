# Module: listing-workflow (mock data)

## Responsibility

Phase 1.6 mock fixtures for New Seller listing workflow entities:
`ProductDraft`, `Distributor`, and `Opportunity`. Typed schemas aligned with
`docs/data-models/canonical-entities.md` § Workflow entities.

## Public Interface

- `loadDistributors()` — curated distributor catalog (≥5, stable UUIDs)
- `loadOpportunities()` — opportunity cards with P1.6 filter fields (capital, category, dropship)
- `loadProductDrafts()` — golden `ProductDraft` seeds for tests and rules engine
- `validateListingFixtures()` — schema validation for all fixture sets
- `P16_ALLOWED_SOURCES` — `internal_curated` | `research` only (ADR-020)

## Dependencies

- None (static JSON fixtures)

## Invariants

- All fixture `source` values are P1.6-allowed (`internal_curated` or `research`)
- Stable UUIDs for golden tests — do not randomize IDs
- No TikTok API calls; no Postgres writes
- Opportunity `suggested_supplier_ids` reference distributor fixture IDs

## Owners

- domain: web
- code: `web/src/lib/mock-data/listing-workflow/`
- EXECUTION slice: P1.6-1 (issue #153)
