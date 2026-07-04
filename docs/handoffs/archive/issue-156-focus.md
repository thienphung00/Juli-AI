# Handoff: focus → tdd — Issue #156

## Issue
- **#156** — CSV/JSON export — execute step from ProductDraft
- **EXECUTION slice:** P1.6-4
- **Parent:** #152 · **Blocked by:** #153, #154, #155 (all shipped)

## Acceptance criteria
- `exportProductDraft(draft, format)` returns valid CSV and JSON matching `ProductDraft` schema fields
- Export button disabled or shows error when `compliance.status === blocked`
- Execute step shows success message with manual Seller Center upload instructions (Vietnamese)
- Integration test: Path A E2E — approve `list_products` → complete Path A → download/export succeeds
- Integration test: Path B E2E — complete Path B → export succeeds
- Unit test: exported JSON parses and contains required `draft_id`, `product_info`, `listing_content`, `compliance`, `readiness`
- Unit test: blocked draft → export throws or returns error (no file produced)
- No TikTok API calls; no Postgres writes
- UX instrumentation hook for `export_completed` event (extend existing analytics pattern)

## Context loaded
| Area | Files |
|------|-------|
| Schema | `web/src/lib/mock-data/listing-workflow/schemas.ts` |
| Rules engine | `web/src/lib/workflows/new-seller/listing/generate.ts`, `export-guard.ts` |
| UI shell | `web/src/components/workflows/new-seller/listing/ListingWorkflowPanel.tsx` |
| State machine | `web/src/lib/workflows/new-seller/listing/state-machine.ts` (`export_placeholder` step) |
| Prior tests | `web/src/__tests__/test_listing_workflow_ui.test.tsx`, `test_listing_rules_engine.test.ts` |
| Analytics | `web/src/lib/ux-analytics/track.ts`, `web/src/lib/analytics.ts` |
| Fixtures | `web/src/lib/mock-data/listing-workflow/fixtures/product-drafts.ts` |

## Standards applied
- [x] Reliability — export guard before serialization; fail-fast on blocked drafts
- [x] Security — client-side only; no external API; no PII in logs
- [ ] Observability — add `export_completed` UX event (issue AC)
- [ ] Performance — single-draft serialization; no unbounded work

## Plugin skills & MCP
- None required (UI-only mock module; no Supabase/TikTok API)

## Implementation approach
**Dependency order:** export module → unit tests → wire UI execute step → E2E tests → analytics hook

### New files
| File | Purpose |
|------|---------|
| `web/src/lib/workflows/new-seller/listing/export.ts` | `exportProductDraft`, CSV/JSON serializers, `ExportBlockedError` |
| `web/src/lib/workflows/new-seller/listing/export-analytics.ts` | `trackExportCompleted` via `juli:analytics` pattern |
| `web/src/__tests__/test_listing_export.test.ts` | Unit tests for export module |
| `docs/decisions/023-listing-export-service.md` | ADR for client-side export contract |

### Modified files
| File | Change |
|------|--------|
| `ListingWorkflowPanel.tsx` | Replace `ExportPlaceholderStep` with execute step (format picker, export button, success copy) |
| `state-machine.ts` | Rename step `export_placeholder` → `export_execute` (optional; keep placeholder id if tests depend) |
| `index.ts` | Re-export `exportProductDraft` |
| `test_listing_workflow_ui.test.tsx` | Path A/B E2E through export |
| `docs/architecture/map.md` | Deployed row for export module |

### Key patterns
- Reuse `canExportProductDraft` from #154 — single guard for UI disable + export throw
- `exportProductDraft` returns `{ content, mimeType, filename }` for browser download (Blob + anchor)
- JSON export: full `ProductDraft` object serialized
- CSV export: dot-notation flat columns for schema fields; arrays pipe-delimited
- Analytics: new listing workflow event type alongside task UX events (fail-silent)

### Tests (TDD)
1. RED: JSON export contains required top-level fields from golden fixture
2. RED: blocked draft throws `ExportBlockedError`
3. RED: CSV export is parseable with expected headers
4. RED: Path A E2E reaches export success message
5. GREEN: Path B E2E export succeeds

## DO NOT touch
- TikTok API integrations, Postgres, backend routes
- Rules engine logic (#154) except importing `canExportProductDraft`
- Shop progress widget (#157)
