# Module: operations (mock data)

## Responsibility

Phase 1.8 mock fixtures for the operations-system pipeline input envelope:
`unified_operational_data_model` per shop profile (`NEW_SHOP`, `MID_LARGE_SHOP`),
plus a datum→workflow traceability map enforcing ADR-013 constraint #4.

## Public Interface

- `loadOperationalModel(profile)` — unified envelope for `NEW_SHOP` or `MID_LARGE_SHOP`
- `loadOperationalModelForPersona(personaId)` — PersonaSwitcher binding (`new` → NEW_SHOP; `leakage`/`growth` → MID_LARGE_SHOP)
- `resolveOperationalProfileForPersona(personaId)` — demo persona → shop profile mapping
- `loadAllOperationalFixtures()` — both profile fixtures for batch validation
- `validateOperationsFixtures()` — schema validation for all fixture sets
- `validateUnifiedOperationalModel(model)` — single-envelope schema validation
- `DATUM_TRACEABILITY_MAP` / `exportTraceabilityArtifact()` — datum→workflow_id map
- `checkTraceability(model)` — assert every present datum maps to ≥1 validated workflow
- `assertNoDatumsOutsideSignalRequirements(model)` — no orphan fields outside the six-workflow signal set
- `VALIDATED_WORKFLOW_IDS` — ADR-013 Appendix A catalog (`npl`, `minimize_violations`, …)

## Dependencies

- `@/lib/mock-data/seller-personas/schemas` — `PersonaId` for demo persona binding

## Invariants

- Exactly two shop-profile fixtures: `NEW_SHOP`, `MID_LARGE_SHOP`
- Every collected datum maps to ≥1 validated `workflow_id` (traceability map + CI tests)
- No datum fields outside the six-workflow signal requirements
- Stable shop IDs aligned with seller-persona fixtures where applicable
- `health_data_source: "mock"` in P1.8; P2 swaps loaders without schema rewrites
- No TikTok API calls; no Postgres writes

## Owners

- domain: web
- code: `web/src/lib/mock-data/operations/`
- EXECUTION slice: P1.8-2 (issue #176)
