# Operations classification (P1.8-1)

Rules-based shop profile classification and validated workflow catalog mapping for the operations-system pipeline.

## Public interface

- `classifyShopProfile(unifiedModel) → NEW_SHOP | MID_LARGE_SHOP` — pure classifier from `unified_operational_data_model`
- `WORKFLOW_CATALOG` / `getWorkflowsForProfile(profile)` — ADR-026 Appendix A profile→workflow map (six workflows only)
- `PROFILE_BOUNDARY_FIXTURES` — golden boundary inputs for QA

## Classification rules

- **NEW_SHOP:** active probation OR unmet graduation requirements (SPS/AHR below threshold), or graduated but under 90 days active without ≥2 tracked GMV metrics
- **MID_LARGE_SHOP:** met graduation requirements AND (shop age ≥ 90 days OR ≥2 GMV metrics tracked)

## Relationship to demo routing

Extends — does not replace — `seller-stage-router` / `resolveSellerWorkflow` (`new|leakage|growth` personas remain for P1 demos).

## Dependencies

- `@/lib/mock-data/operations/schemas` — `UnifiedOperationalDataModel`, `ShopProfileType`, `ValidatedWorkflowId`

## Out of scope (later slices)

- Health check (`health-check.ts`, P1.8-3)
- Ranking (`recommendations.ts`, P1.8-4)
- UI / `useOperationsPipeline` hook
