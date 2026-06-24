# Handoff: tdd → review — Issue #154

## Issue

- **#154** — Rules-based listing generation — extraction, compliance, readiness score

## Branch

- `feature/issue-154-listing-rules-engine`

## Changes summary

- **New:** `web/src/lib/workflows/new-seller/listing/` (types, constants, extraction, compliance, readiness, generate, export-guard, hash, MODULE.md)
- **New:** `web/src/__tests__/test_listing_rules_engine.test.ts`
- **Modified:** `docs/architecture/map.md` — deployed module row for listing rules engine

## Tests written

| Test | Behavior verified |
|------|-------------------|
| `test_listing_rules_engine.test.ts` — blocked category | `compliance.status === blocked`, export denied |
| `test_listing_rules_engine.test.ts` — missing price | Blocking issue present, export denied |
| `test_listing_rules_engine.test.ts` — complete input | `ready_for_export`, score ≥ 70 |
| `test_listing_rules_engine.test.ts` — determinism | Same context → deep equality |
| `test_listing_rules_engine.test.ts` — url_stub | Category hint + product name extraction |
| `test_listing_rules_engine.test.ts` — opportunity_card | Pre-fill from opportunity + distributor |
| `test_listing_rules_engine.test.ts` — module contract | No fetch/LLM in entrypoint |

## Test results

- 7/7 new tests passing
- 200/200 full web suite passing
- `tsc --noEmit` clean
- `next lint` clean (pre-existing warning in CreatorsPage only)

## Acceptance criteria status

- [x] `generateProductDraft()` under `web/src/lib/workflows/new-seller/listing/` with documented context types
- [x] Manual form → complete `product_info` and `listing_content`
- [x] URL stub → deterministic extraction (no live fetch)
- [x] Opportunity card → pre-filled from opportunity + distributor
- [x] Compliance blocked/warning/approved rules
- [x] Readiness score 0–100 deterministic
- [x] All four required unit tests + source-type coverage
- [x] No cloud LLM; no API calls
- [x] MODULE.md + map.md row

## Notes for reviewer

- `draft_id` and timestamps derived from stable hash of normalized context JSON for determinism
- `READINESS_EXPORT_THRESHOLD = 70` exported and asserted in tests
- Reuses `ProductDraft` types from listing-workflow fixtures module (#153)
