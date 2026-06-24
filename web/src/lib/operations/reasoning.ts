import { formatNumber } from "@/lib/format";
import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

import type {
  HealthCheckResults,
  HealthIndicator,
  HealthIndicatorId,
} from "./health-check";
import { HEALTH_INDICATOR_TRACEABILITY_MAP, TARGET_ROAS } from "./health-check";
import type { WorkflowRecommendation } from "./recommendations";

export const REASONING_COPY_SOURCE = "rules" as const;

export type ReasoningCopySource = typeof REASONING_COPY_SOURCE;

export interface WorkflowReasoning {
  copy_source: ReasoningCopySource;
  why: string;
  expected_impact: string;
  next_steps: string[];
  /** Health indicators referenced in copy — for traceability tests. */
  source_indicator_ids: HealthIndicatorId[];
}

type ReasoningTemplate = (
  recommendation: WorkflowRecommendation,
  health: HealthCheckResults,
) => WorkflowReasoning;

function indicatorApplies(indicator: HealthIndicator): boolean {
  return indicator.severity !== "not_applicable";
}

function collectNumbersFromValue(value: unknown, bucket: number[]): void {
  if (typeof value === "number" && Number.isFinite(value)) {
    bucket.push(value);
    return;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      collectNumbersFromValue(item, bucket);
    }
    return;
  }

  if (value && typeof value === "object") {
    for (const nested of Object.values(value as Record<string, unknown>)) {
      collectNumbersFromValue(nested, bucket);
    }
  }
}

/** Numeric values from a health indicator — used by reasoning guard tests. */
export function collectIndicatorNumericValues(indicator: HealthIndicator): number[] {
  const values: number[] = [];
  collectNumbersFromValue(indicator, values);
  return values;
}

function formatImpactSentence(recommendation: WorkflowRecommendation): string {
  const { metric, value } = recommendation.expected_impact;
  return `Dự kiến cải thiện ${metric} khoảng ${formatNumber(value)} điểm.`;
}

const buildNplReasoning: ReasoningTemplate = (recommendation, health) => {
  const probation = health.indicators.probation_progress;
  const sps = health.indicators.sps_health;
  const source_indicator_ids: HealthIndicatorId[] = [];

  const whyParts: string[] = [];

  if (indicatorApplies(probation)) {
    source_indicator_ids.push("probation_progress");
    whyParts.push(
      `Tiến độ thử việc đạt ${formatNumber(probation.percent_toward_graduation)}% với ${formatNumber(probation.days_remaining)} ngày còn lại.`,
    );
  }

  if (indicatorApplies(sps)) {
    source_indicator_ids.push("sps_health");
    whyParts.push(
      `SPS hiện tại ${formatNumber(sps.sps_current)}/${formatNumber(sps.sps_threshold)} — còn thiếu ${formatNumber(sps.threshold_gap)} điểm.`,
    );
  }

  return {
    copy_source: REASONING_COPY_SOURCE,
    why: whyParts.join(" ") || recommendation.rationale,
    expected_impact: formatImpactSentence(recommendation),
    next_steps: [
      "Rà soát danh mục để xác định category còn thiếu sản phẩm.",
      "Chuẩn bị listing mới với mô tả và hình ảnh đạt chuẩn Seller Center.",
      "Theo dõi SPS sau khi đăng sản phẩm trong 7 ngày.",
    ],
    source_indicator_ids,
  };
};

const buildMinimizeViolationsReasoning: ReasoningTemplate = (recommendation, health) => {
  const ahr = health.indicators.ahr_health;
  const source_indicator_ids: HealthIndicatorId[] = [];

  const whyParts: string[] = [];

  if (indicatorApplies(ahr)) {
    source_indicator_ids.push("ahr_health");
    whyParts.push(
      `AHR hiện tại ${formatNumber(ahr.ahr_current)}/${formatNumber(ahr.ahr_threshold)} — cần cải thiện ${formatNumber(ahr.threshold_gap)} điểm.`,
    );
    if (ahr.summary) {
      whyParts.push(ahr.summary);
    }
  }

  return {
    copy_source: REASONING_COPY_SOURCE,
    why: whyParts.join(" ") || recommendation.rationale,
    expected_impact: formatImpactSentence(recommendation),
    next_steps: [
      "Mở Seller Center → Trung tâm vi phạm để xem chi tiết từng cảnh báo.",
      "Ưu tiên xử lý vi phạm mức cao trước khi đăng thêm sản phẩm.",
      "Theo dõi AHR sau 7 ngày để xác nhận cải thiện.",
    ],
    source_indicator_ids,
  };
};

const buildBudgetOptimizationReasoning: ReasoningTemplate = (recommendation, health) => {
  const roas = health.indicators.ad_roas_efficiency;
  const source_indicator_ids: HealthIndicatorId[] = [];

  const whyParts: string[] = [];

  if (indicatorApplies(roas)) {
    source_indicator_ids.push("ad_roas_efficiency");
    whyParts.push(
      `${formatNumber(roas.active_campaigns_below_target_pct)}% chiến dịch đang dưới ROAS mục tiêu ${formatNumber(TARGET_ROAS)}.`,
    );
    const belowTarget = roas.campaigns.filter(
      (campaign) => campaign.percent_below_target > 0,
    );
    if (belowTarget[0]) {
      whyParts.push(
        `Chiến dịch "${belowTarget[0].campaign_name}" đạt ROAS ${formatNumber(belowTarget[0].roas)}.`,
      );
    }
  }

  return {
    copy_source: REASONING_COPY_SOURCE,
    why: whyParts.join(" ") || recommendation.rationale,
    expected_impact: formatImpactSentence(recommendation),
    next_steps: [
      "Tạm dừng hoặc giảm ngân sách chiến dịch ROAS thấp.",
      "Chuyển ngân sách sang chiến dịch đạt ROAS ổn định.",
      "Đánh giá lại hiệu quả sau 7 ngày vận hành.",
    ],
    source_indicator_ids,
  };
};

const buildProductScalingReasoning: ReasoningTemplate = (recommendation, health) => {
  const scaling = health.indicators.product_scaling_opportunity;
  const source_indicator_ids: HealthIndicatorId[] = [];

  const whyParts: string[] = [];

  if (indicatorApplies(scaling)) {
    source_indicator_ids.push("product_scaling_opportunity");
    const topSku = scaling.top_skus[0];
    if (topSku) {
      whyParts.push(
        `SKU "${topSku.product_name}" có tiềm năng tăng trưởng ${formatNumber(topSku.growth_potential_score)} điểm với ${formatNumber(topSku.units_sold_7d)} đơn trong tuần qua.`,
      );
    } else if (scaling.summary) {
      whyParts.push(scaling.summary);
    }
  }

  return {
    copy_source: REASONING_COPY_SOURCE,
    why: whyParts.join(" ") || recommendation.rationale,
    expected_impact: formatImpactSentence(recommendation),
    next_steps: [
      "Tăng ngân sách quảng cáo cho SKU tiềm năng cao nhất.",
      "Đảm bảo tồn kho đủ cho giai đoạn mở rộng 14 ngày.",
      "Theo dõi doanh thu SKU sau khi tăng scale.",
    ],
    source_indicator_ids,
  };
};

const buildRefundSpikeReasoning: ReasoningTemplate = (recommendation, health) => {
  const refund = health.indicators.refund_spike_indicator;
  const source_indicator_ids: HealthIndicatorId[] = [];

  const whyParts: string[] = [];

  if (indicatorApplies(refund)) {
    source_indicator_ids.push("refund_spike_indicator");
    const ratePct = Math.round(refund.refund_rate_7d * 1000) / 10;
    whyParts.push(
      `Tỷ lệ hoàn gần đây ${formatNumber(ratePct)}% — ${formatNumber(refund.percent_change_vs_baseline)}% so với mức cơ sở.`,
    );
    if (refund.spike_detected) {
      whyParts.push("Hệ thống phát hiện đỉnh hoàn tiền bất thường.");
    }
  }

  return {
    copy_source: REASONING_COPY_SOURCE,
    why: whyParts.join(" ") || recommendation.rationale,
    expected_impact: formatImpactSentence(recommendation),
    next_steps: [
      "Rà soát đơn hoàn gần đây để tìm nguyên nhân lặp lại.",
      "Kiểm tra mô tả sản phẩm và chính sách đổi trả.",
      "Theo dõi tỷ lệ hoàn trong 7 ngày sau khi xử lý.",
    ],
    source_indicator_ids,
  };
};

const buildStockoutPreventionReasoning: ReasoningTemplate = (recommendation, health) => {
  const inventory = health.indicators.inventory_health;
  const source_indicator_ids: HealthIndicatorId[] = [];

  const whyParts: string[] = [];

  if (indicatorApplies(inventory)) {
    source_indicator_ids.push("inventory_health");
    whyParts.push(
      `${formatNumber(inventory.at_risk_sku_count)} SKU đang có nguy cơ hết hàng.`,
    );
    const riskiest = inventory.skus
      .filter((sku) => sku.lead_time_coverage_ratio < 1)
      .sort((left, right) => left.lead_time_coverage_ratio - right.lead_time_coverage_ratio)[0];
    if (riskiest) {
      whyParts.push(
        `SKU ${riskiest.sku_id} còn ${formatNumber(riskiest.days_of_inventory_remaining)} ngày tồn kho với lead time ${formatNumber(riskiest.reorder_lead_time_days)} ngày.`,
      );
    } else if (inventory.summary) {
      whyParts.push(inventory.summary);
    }
  }

  return {
    copy_source: REASONING_COPY_SOURCE,
    why: whyParts.join(" ") || recommendation.rationale,
    expected_impact: formatImpactSentence(recommendation),
    next_steps: [
      "Ưu tiên đặt hàng bổ sung cho SKU có coverage thấp nhất.",
      "Điều chỉnh quảng cáo nếu tồn kho không đủ cho nhu cầu.",
      "Theo dõi mức tồn kho hàng tuần trong 30 ngày.",
    ],
    source_indicator_ids,
  };
};

export const WORKFLOW_REASONING_TEMPLATES: Record<ValidatedWorkflowId, ReasoningTemplate> = {
  npl: buildNplReasoning,
  minimize_violations: buildMinimizeViolationsReasoning,
  budget_optimization: buildBudgetOptimizationReasoning,
  product_scaling: buildProductScalingReasoning,
  refund_spike_detection: buildRefundSpikeReasoning,
  stockout_prevention: buildStockoutPreventionReasoning,
};

/**
 * Deterministic rules-only reasoning copy keyed by workflow_id + health signals (P1.8-5).
 */
export function buildWorkflowReasoning(
  recommendation: WorkflowRecommendation,
  health: HealthCheckResults,
): WorkflowReasoning {
  const template = WORKFLOW_REASONING_TEMPLATES[recommendation.workflow_id];
  const reasoning = template(recommendation, health);

  const allowedIndicators = new Set(
    Object.entries(HEALTH_INDICATOR_TRACEABILITY_MAP)
      .filter(([, workflows]) => workflows.includes(recommendation.workflow_id))
      .map(([id]) => id as HealthIndicatorId),
  );

  return {
    ...reasoning,
    source_indicator_ids: reasoning.source_indicator_ids.filter((id) =>
      allowedIndicators.has(id),
    ),
  };
}
