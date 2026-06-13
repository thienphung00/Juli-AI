import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

import type { WorkflowRecommendation } from "./recommendations";
import type { ReportDomainId } from "./todays-report";

const METRIC_PRIMARY_WORKFLOW: Partial<Record<`${ReportDomainId}:${string}`, ValidatedWorkflowId>> =
  {
    "revenue_growth:revenue_7d": "budget_optimization",
    "revenue_growth:units_sold_7d": "budget_optimization",
    "revenue_growth:roas": "budget_optimization",
    "product_listings:product_count": "product_scaling",
    "inventory_refunds:low_stock_rate": "stockout_prevention",
    "inventory_refunds:refund_rate_7d": "refund_spike_detection",
  };

const SPS_TAGGED_WORKFLOW_IDS: ValidatedWorkflowId[] = [
  "budget_optimization",
  "product_scaling",
  "npl",
];

const AHR_TAGGED_WORKFLOW_IDS: ValidatedWorkflowId[] = ["minimize_violations", "npl"];

function isActionable(recommendation: WorkflowRecommendation | undefined): boolean {
  return Boolean(recommendation?.preconditions_met);
}

/** Fixed Daily Report metric → Decisions workflow (Product tab falls back to NPL). */
export function resolveMetricWorkflowId(
  reportDomain: ReportDomainId,
  metricKey: string,
  recommendations: WorkflowRecommendation[] = [],
): ValidatedWorkflowId | null {
  const mapKey = `${reportDomain}:${metricKey}` as `${ReportDomainId}:${string}`;
  const primary = METRIC_PRIMARY_WORKFLOW[mapKey];
  if (!primary) {
    return null;
  }

  if (primary === "product_scaling") {
    const scaling = recommendations.find((item) => item.workflow_id === "product_scaling");
    if (isActionable(scaling)) {
      return "product_scaling";
    }
    return "npl";
  }

  return primary;
}

/** SPS estimated bar — fall through SPS-tagged ranked actions when top is unavailable. */
export function resolveSpsWorkflowId(
  recommendations: WorkflowRecommendation[],
): ValidatedWorkflowId {
  for (const workflowId of SPS_TAGGED_WORKFLOW_IDS) {
    const match = recommendations.find((item) => item.workflow_id === workflowId);
    if (isActionable(match)) {
      return workflowId;
    }
  }

  const ranked = recommendations.find((item) =>
    SPS_TAGGED_WORKFLOW_IDS.includes(item.workflow_id),
  );
  return ranked?.workflow_id ?? "budget_optimization";
}

/** AHR estimated bar — Minimize Violation first, then other AHR-tagged actions. */
export function resolveAhrWorkflowId(
  recommendations: WorkflowRecommendation[],
): ValidatedWorkflowId {
  for (const workflowId of AHR_TAGGED_WORKFLOW_IDS) {
    const match = recommendations.find((item) => item.workflow_id === workflowId);
    if (isActionable(match)) {
      return workflowId;
    }
  }

  const ahrImpact = recommendations.find((item) => item.expected_impact.metric === "AHR");
  return ahrImpact?.workflow_id ?? "minimize_violations";
}
