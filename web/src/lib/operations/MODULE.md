# Operations pipeline (P1.8-1…3)

Rules-based shop profile classification, health check indicators, and validated workflow catalog mapping for the operations-system pipeline.

## Public interface

- `classifyShopProfile(unifiedModel) → NEW_SHOP | MID_LARGE_SHOP` — pure classifier from `unified_operational_data_model`
- `computeHealthCheckResults(unifiedModel) → health_check_results` — pure health indicators keyed by indicator ID (P1.8-3)
- `rankWorkflowRecommendations(profile, health) → workflow_recommendations` — pure ranking by profile + health signals (P1.8-4)
- `buildWorkflowReasoning(recommendation, health) → WorkflowReasoning` — rules-only Why / Impact / Next Steps copy (P1.8-5)
- `loadWorkflowOutcomeMetrics(workflowId) → workflow_outcome_metrics` — mock outcome envelope + ADR-026 Appendix B success criteria (P1.8-7)
- `useOperationsPipeline({ personaId })` / `runOperationsPipeline(personaId)` — load → classify → health → rank (P1.8-4)
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

## Workflow recommendations (P1.8-4)

| Profile | Workflows ranked | Logic |
|---------|------------------|-------|
| NEW_SHOP | NPL, Minimize Violations | Probation timeline urgency + SPS/AHR gaps; never growth/loss workflows |
| MID_LARGE_SHOP | Budget, Scaling, Refund Spike, Stockout | Impact/urgency from health indicators; impact-threshold filter skipped until Product sets `MID_LARGE_IMPACT_THRESHOLD_VND` in EXECUTION.md |

## Reasoning copy layer (P1.8-5)

| Workflow | Why signals | Next steps |
|----------|-------------|------------|
| NPL | probation_progress, sps_health | Listing prep + SPS follow-up |
| Minimize Violations | ahr_health | Violation center triage |
| Budget Optimization | ad_roas_efficiency | Pause/reallocate underperforming campaigns |
| Product Scaling | product_scaling_opportunity | Scale top SKU ads + inventory |
| Refund Spike | refund_spike_indicator | Root-cause refund review |
| Stockout Prevention | inventory_health | Reorder at-risk SKUs |

UI: `web/src/components/workflows/operations/` — `HomeSummaryShell` (read-only Home, P1.8-9 #193), `DecisionPreviewCard`, `RecommendedDecisionsPreview`, `ClarityCard`, `ReasoningPanel`, `ShopHealthHero`, `ApprovalGate`, `OperationsApprovalShell` (Decisions Recommended tab, #195), `OperationsPipelineShell` (legacy test composite), `OutcomeTrackingView` (P1.8-5…7).

Today's Report (P1.8-9 #194): `buildAllDomainReportSummaries(unifiedModel)` in `todays-report.ts`; UI in `web/src/components/home/todays-report/` (`TodaysReportPanel` embedded in `HomeSummaryShell`).

## Journey link registry (P1.8-10)

RRAA cross-screen loop ([ADR-029](../../../docs/decisions/029-user-journey-rraa-loop.md)): maps each ADR-026 `workflow_id` to a Home Today's Report metric anchor, standardized Reason/Anticipation copy, and deep-link query params.

| Export | Purpose |
|--------|---------|
| `getJourneyLink(workflowId)` | Full registry row: `reportDomain`, `metricKey`, `rewardLabel`, `reasonTemplate`, `anticipationTemplate` |
| `resolveHomeHighlight(workflowId)` | Home metric anchor for Anticipation back-link / Recent Progress completed rows |
| `formatAnticipationImpact(workflowId)` | Standardized **TÁC ĐỘNG DỰ KIẾN** copy (VND, %, units — not abstract điểm where a Home chart exists) |
| `buildDecisionsHighlightLink(workflowId)` | `/decisions?highlight=<workflow_id>` |
| `buildHomeHighlightLink(anchor)` | `/?highlight=<report_domain>:<metric_key>` |
| `parseDecisionsHighlight(param)` | Validate Decisions `?highlight=` — returns `null` for invalid values |
| `parseHomeHighlight(param)` | Parse Home `?highlight=domain:metric` — returns `null` for invalid values |

Types: `JourneyLink`, `HomeMetricAnchor`, `RecentProgressState` (`pending` \| `completed`).

## Approval gate & routing (P1.8-6)

| Workflow | Route | Executor |
|----------|-------|----------|
| `npl` | listing | `ListingWorkflowPanel` via `list_products` task |
| `refund_spike_detection` | leakage | `LeakageWorkflowPanel` via mapped P1.7 task type |
| others | noop | Session-only approval + Phase 2 toast |

Session: `operations/approval-session.ts` (workflow dispositions) + `use-operations-approval.ts` (selective / approve-all / reject-with-reason via `TaskDismissModal`).

## Outcome tracking (P1.8-7)

| Cadence | Purpose |
|---------|---------|
| `realtime` | Execution status immediately after approval |
| `daily` | Preliminary 24h readings |
| `weekly` | Full assessment vs ADR-026 Appendix B threshold |
| `monthly` | Aggregate trend |

Success criteria copy is frozen in `WORKFLOW_OUTCOME_SUCCESS_CRITERIA` (ADR-026 Appendix B). UI: `OutcomeTrackingView` with cadence tabs; reachable from approved Clarity Cards without clearing executor session.
