# Operations pipeline (P1.8-1…3)

Rules-based shop profile classification, health check indicators, and validated workflow catalog mapping for the operations-system pipeline.

## Public interface

- `classifyShopProfile(unifiedModel) → NEW_SHOP | MID_LARGE_SHOP` — pure classifier from `unified_operational_data_model`
- `computeHealthCheckResults(unifiedModel) → health_check_results` — pure health indicators keyed by indicator ID (P1.8-3)
- `HEALTH_INDICATOR_TRACEABILITY_MAP` / `getWorkflowsForHealthIndicator(id)` — indicator→workflow traceability (ADR-026 constraint #5)
- `WORKFLOW_CATALOG` / `getWorkflowsForProfile(profile)` — ADR-026 Appendix A profile→workflow map (six workflows only)
- `PROFILE_BOUNDARY_FIXTURES` — golden boundary inputs for QA

## Classification rules

- **NEW_SHOP:** active probation OR unmet graduation requirements (SPS/AHR below threshold), or graduated but under 90 days active without ≥2 tracked GMV metrics
- **MID_LARGE_SHOP:** met graduation requirements AND (shop age ≥ 90 days OR ≥2 GMV metrics tracked)

## Relationship to demo routing

Extends — does not replace — `seller-stage-router` / `resolveSellerWorkflow` (`new|leakage|growth` personas remain for P1 demos).

## Dependencies

- `@/lib/mock-data/operations/schemas` — `UnifiedOperationalDataModel`, `ShopProfileType`, `ValidatedWorkflowId`

## Health check indicators (P1.8-3)

| Indicator ID | Informs workflows | Output |
|--------------|-------------------|--------|
| `probation_progress` | NPL, Minimize Violations | % toward graduation, days remaining |
| `sps_health` | NPL, Minimize Violations | current SPS, threshold gap |
| `ahr_health` | NPL, Minimize Violations | current AHR, threshold gap |
| `ad_roas_efficiency` | Budget Optimization | ROAS by campaign, % below target |
| `inventory_health` | Stockout Prevention | days of inventory, lead-time coverage |
| `refund_spike_indicator` | Refund Spike Detection | refund rate 7d vs baseline, spike flag |
| `product_scaling_opportunity` | Product Scaling | top SKUs by growth potential |

## Out of scope (later slices)

- Ranking (`recommendations.ts`, P1.8-4)
- UI / `useOperationsPipeline` hook
