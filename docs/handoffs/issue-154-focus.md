# Handoff: focus → tdd — Issue #154

## Issue

- **#154** — Rules-based listing generation — extraction, compliance, readiness score
- **EXECUTION slice:** P1.6-3
- **Parent:** #152 · **Blocked by:** #153 (shipped)

## Acceptance criteria

- `generateProductDraft()` module under `web/src/lib/workflows/new-seller/listing/` with documented input context type
- Manual form input → complete `product_info` and `listing_content` fields via rules (no LLM)
- URL stub input → deterministic field extraction (hostname/category hints; no live fetch)
- Opportunity card context → draft pre-filled from selected opportunity + distributor
- Compliance: `blocked` when required fields missing or category on blocklist; `warning` for soft issues; `approved` otherwise
- Readiness score: integer 0–100, deterministic from field completeness and compliance state
- Unit test: blocked category → `compliance.status === blocked` and export would be denied
- Unit test: missing price → blocking issue present
- Unit test: complete valid input → `ready_for_export` status and score ≥ threshold documented in test
- Unit test: same input twice → identical draft hash or deep equality
- No cloud LLM; no API calls

## Context loaded

| Area | Files |
|------|-------|
| Architecture | `EXECUTION.md` (P1.6-3), `docs/system-design.md` §7, `docs/architecture/map.md` (planned row) |
| Data models | `docs/data-models/canonical-entities.md` § Workflow entities |
| Decisions | `docs/decisions/020-new-seller-listing-workflow-scope.md` |
| Prior art | `web/src/lib/mock-data/listing-workflow/schemas.ts`, `web/src/lib/workflows/new-seller/milestone.ts` |
| Upstream | `docs/handoffs/issue-153-ship.md` — ProductDraft schema contract |

## Standards applied

- Reliability — deterministic pure functions; fail-fast on invalid context shape
- Security — no external fetch; no PII in generated content
- Maintainability — small public surface (`generateProductDraft`, `canExportProductDraft`); deep modules split by concern

## Plugin skills & MCP

- None required (client-side rules only)

## Implementation approach

**Dependency order:** types → constants → extraction → compliance → readiness → generate → export guard → tests → MODULE.md + map.md

### New files

| File | Purpose |
|------|---------|
| `web/src/lib/workflows/new-seller/listing/types.ts` | `ListingGenerationContext` union (manual_form, url_stub, opportunity_card) |
| `web/src/lib/workflows/new-seller/listing/constants.ts` | Blocked categories, readiness export threshold |
| `web/src/lib/workflows/new-seller/listing/extraction.ts` | Rules-only field extraction per source type |
| `web/src/lib/workflows/new-seller/listing/compliance.ts` | Compliance status, warnings, blocking issues |
| `web/src/lib/workflows/new-seller/listing/readiness.ts` | Deterministic 0–100 score + suggestions |
| `web/src/lib/workflows/new-seller/listing/generate.ts` | `generateProductDraft(context)` orchestrator |
| `web/src/lib/workflows/new-seller/listing/export-guard.ts` | `canExportProductDraft(draft)` |
| `web/src/lib/workflows/new-seller/listing/index.ts` | Public exports |
| `web/src/lib/workflows/new-seller/listing/MODULE.md` | Module contract |
| `web/src/__tests__/test_listing_rules_engine.test.ts` | AC unit tests |

### Modified files

| File | Change |
|------|--------|
| `docs/architecture/map.md` | Move `web/src/lib/workflows/new-seller/listing/` from planned → deployed |

### Key patterns

- Reuse `ProductDraft` types from `@/lib/mock-data/listing-workflow/schemas` — single schema contract
- Deterministic `draft_id` + timestamps derived from stable hash of normalized context (same input → identical draft)
- URL stub: parse hostname/path segments only — map known host keywords to category hints (no `fetch`)
- Opportunity card: accept embedded `Opportunity` + `Distributor` in context (UI passes selected card data)
- Export gate: `canExportProductDraft` returns false when `compliance.status === "blocked"`
- `READINESS_EXPORT_THRESHOLD = 70` documented in test constant

### Tests (TDD)

1. RED: blocked category → `compliance.status === "blocked"`, `canExportProductDraft` false
2. RED: missing/zero price → blocking issue "Giá bán chưa được nhập"
3. RED: complete manual form → `ready_for_export`, score ≥ 70
4. RED: same context twice → deep equality on full `ProductDraft`
5. GREEN: implement rules modules + orchestrator

## DO NOT touch

- Listing workflow UI (#155), export service (#156), shop progress (#157)
- Backend / Postgres / TikTok API
- Mock fixture data (#153) except type imports
