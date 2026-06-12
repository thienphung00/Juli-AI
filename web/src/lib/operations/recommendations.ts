import type {
  ShopProfileType,
  ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";

import type { ShopProfileClassification } from "./classification";
import type { HealthCheckResults, HealthIndicatorSeverity } from "./health-check";
import { REFUND_SPIKE_THRESHOLD_RATIO } from "./health-check";
import { getWorkflowsForProfile } from "./workflow-catalog";

/**
 * Product-owned MID_LARGE_SHOP impact filter (VND). Null until recorded in EXECUTION.md.
 * Mock P1.8 ranks all eligible workflows when unset (ADR-026).
 */
export const MID_LARGE_IMPACT_THRESHOLD_VND: number | null = null;

export type ImpactConfidence = "high" | "medium" | "low";

export interface WorkflowExpectedImpact {
  metric: string;
  value: number;
  confidence: ImpactConfidence;
}

export interface WorkflowRecommendation {
  workflow_id: ValidatedWorkflowId;
  workflow_name: string;
  priority: number;
  rationale: string;
  expected_impact: WorkflowExpectedImpact;
  preconditions_met: boolean;
  user_action_required: boolean;
}

/**
 * Stable P1.8 output envelope for the operations pipeline ranking stage.
 * P2 swaps scoring; schema shape remains stable per ADR-026.
 */
export interface WorkflowRecommendations {
  shop_profile: ShopProfileType;
  recommended_workflows: WorkflowRecommendation[];
}

interface ScoredWorkflow {
  workflowId: ValidatedWorkflowId;
  score: number;
  rationale: string;
  expectedImpact: WorkflowExpectedImpact;
  preconditionsMet: boolean;
}

const WORKFLOW_DISPLAY_NAMES: Record<ValidatedWorkflowId, string> = {
  npl: "Thêm sản phẩm mới",
  minimize_violations: "Giảm thiểu vi phạm",
  budget_optimization: "Tối ưu ngân sách quảng cáo",
  product_scaling: "Mở rộng sản phẩm",
  refund_spike_detection: "Phát hiện đỉnh hoàn tiền",
  stockout_prevention: "Phòng tránh hết hàng",
};

function severityToConfidence(severity: HealthIndicatorSeverity): ImpactConfidence {
  if (severity === "critical") return "high";
  if (severity === "warning") return "medium";
  return "low";
}

function scoreNewShopWorkflow(
  workflowId: ValidatedWorkflowId,
  health: HealthCheckResults,
): ScoredWorkflow {
  const probation = health.indicators.probation_progress;
  const sps = health.indicators.sps_health;
  const ahr = health.indicators.ahr_health;

  if (workflowId === "npl") {
    const urgency =
      100 -
      probation.percent_toward_graduation +
      sps.threshold_gap * 10 +
      Math.max(0, 30 - probation.days_remaining);

    return {
      workflowId,
      score: urgency,
      rationale: probation.summary || sps.summary,
      expectedImpact: {
        metric: "SPS",
        value: Math.round(sps.threshold_gap * 10) / 10,
        confidence: severityToConfidence(sps.severity),
      },
      preconditionsMet: probation.severity !== "not_applicable" && sps.sps_current > 0,
    };
  }

  const violationWeight = ahr.severity === "critical" ? 40 : 20;
  const urgency = ahr.threshold_gap * 2 + violationWeight;

  return {
    workflowId,
    score: urgency,
    rationale: ahr.summary,
    expectedImpact: {
      metric: "AHR",
      value: ahr.threshold_gap,
      confidence: severityToConfidence(ahr.severity),
    },
    preconditionsMet: ahr.ahr_current > 0 && ahr.threshold_gap > 0,
  };
}

function scoreMidLargeWorkflow(
  workflowId: ValidatedWorkflowId,
  health: HealthCheckResults,
): ScoredWorkflow {
  switch (workflowId) {
    case "budget_optimization": {
      const indicator = health.indicators.ad_roas_efficiency;
      const score =
        indicator.active_campaigns_below_target_pct +
        (indicator.severity === "critical" ? 30 : indicator.severity === "warning" ? 15 : 0);

      return {
        workflowId,
        score,
        rationale: indicator.summary,
        expectedImpact: {
          metric: "ROAS",
          value: indicator.active_campaigns_below_target_pct,
          confidence: severityToConfidence(indicator.severity),
        },
        preconditionsMet:
          indicator.severity !== "not_applicable" && indicator.campaigns.length >= 2,
      };
    }
    case "product_scaling": {
      const indicator = health.indicators.product_scaling_opportunity;
      const topScore = indicator.top_skus[0]?.growth_potential_score ?? 0;

      return {
        workflowId,
        score: topScore,
        rationale: indicator.summary,
        expectedImpact: {
          metric: "doanh_thu_SKU",
          value: topScore,
          confidence: severityToConfidence(indicator.severity),
        },
        preconditionsMet:
          indicator.severity !== "not_applicable" && indicator.top_skus.length > 0,
      };
    }
    case "refund_spike_detection": {
      const indicator = health.indicators.refund_spike_indicator;
      const score = indicator.spike_detected
        ? 100 + indicator.percent_change_vs_baseline
        : indicator.percent_change_vs_baseline;

      return {
        workflowId,
        score,
        rationale: indicator.summary,
        expectedImpact: {
          metric: "tỷ_lệ_hoàn",
          value: Math.round(indicator.refund_rate_7d * 1000) / 10,
          confidence: severityToConfidence(indicator.severity),
        },
        preconditionsMet:
          indicator.spike_detected ||
          indicator.percent_change_vs_baseline / 100 > REFUND_SPIKE_THRESHOLD_RATIO,
      };
    }
    case "stockout_prevention": {
      const indicator = health.indicators.inventory_health;
      const score =
        indicator.at_risk_sku_count * 25 +
        (indicator.severity === "critical" ? 20 : indicator.severity === "warning" ? 10 : 0);

      return {
        workflowId,
        score,
        rationale: indicator.summary,
        expectedImpact: {
          metric: "SKU_rủi_ro",
          value: indicator.at_risk_sku_count,
          confidence: severityToConfidence(indicator.severity),
        },
        preconditionsMet:
          indicator.severity !== "not_applicable" && indicator.skus.length > 0,
      };
    }
    default:
      return {
        workflowId,
        score: 0,
        rationale: "",
        expectedImpact: { metric: "unknown", value: 0, confidence: "low" },
        preconditionsMet: false,
      };
  }
}

function passesImpactThreshold(expectedImpactValue: number): boolean {
  if (MID_LARGE_IMPACT_THRESHOLD_VND === null) {
    return true;
  }

  return expectedImpactValue >= MID_LARGE_IMPACT_THRESHOLD_VND;
}

function toRecommendation(item: ScoredWorkflow, priority: number): WorkflowRecommendation {
  return {
    workflow_id: item.workflowId,
    workflow_name: WORKFLOW_DISPLAY_NAMES[item.workflowId],
    priority,
    rationale: item.rationale,
    expected_impact: item.expectedImpact,
    preconditions_met: item.preconditionsMet,
    user_action_required: item.preconditionsMet,
  };
}

/**
 * Rules-based workflow ranking (P1.8-4).
 * Profile-gates to WORKFLOW_CATALOG; never surfaces IDs outside the validated catalog.
 */
export function rankWorkflowRecommendations(
  profile: ShopProfileClassification,
  health: HealthCheckResults,
): WorkflowRecommendations {
  const eligibleWorkflows = getWorkflowsForProfile(profile);

  const scored = eligibleWorkflows.map((workflowId) =>
    profile === "NEW_SHOP"
      ? scoreNewShopWorkflow(workflowId, health)
      : scoreMidLargeWorkflow(workflowId, health),
  );

  const filtered =
    profile === "MID_LARGE_SHOP"
      ? scored.filter((item) => passesImpactThreshold(item.expectedImpact.value))
      : scored;

  const ranked = [...filtered].sort((left, right) => right.score - left.score);

  return {
    shop_profile: profile,
    recommended_workflows: ranked.map((item, index) => toRecommendation(item, index + 1)),
  };
}
