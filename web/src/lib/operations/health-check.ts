import type {
  HealthDataSource,
  UnifiedOperationalDataModel,
  ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";

/** Stable indicator IDs for P1.8 health check (system-design.md § Health Check indicators). */
export const HEALTH_INDICATOR_IDS = [
  "probation_progress",
  "sps_health",
  "ahr_health",
  "ad_roas_efficiency",
  "inventory_health",
  "refund_spike_indicator",
  "product_scaling_opportunity",
] as const;

export type HealthIndicatorId = (typeof HEALTH_INDICATOR_IDS)[number];

export type HealthIndicatorSeverity =
  | "critical"
  | "warning"
  | "healthy"
  | "not_applicable";

interface HealthIndicatorBase {
  indicator_id: HealthIndicatorId;
  informs_workflows: ValidatedWorkflowId[];
  severity: HealthIndicatorSeverity;
  summary: string;
}

export interface ProbationProgressIndicator extends HealthIndicatorBase {
  indicator_id: "probation_progress";
  percent_toward_graduation: number;
  days_remaining: number;
}

export interface SpsHealthIndicator extends HealthIndicatorBase {
  indicator_id: "sps_health";
  sps_current: number;
  sps_threshold: number;
  threshold_gap: number;
}

export interface AhrHealthIndicator extends HealthIndicatorBase {
  indicator_id: "ahr_health";
  ahr_current: number;
  ahr_threshold: number;
  threshold_gap: number;
}

export interface AdRoasCampaignSnapshot {
  campaign_id: string;
  campaign_name: string;
  roas: number;
  target_roas: number;
  percent_below_target: number;
}

export interface AdRoasEfficiencyIndicator extends HealthIndicatorBase {
  indicator_id: "ad_roas_efficiency";
  target_roas: number;
  campaigns: AdRoasCampaignSnapshot[];
  active_campaigns_below_target_pct: number;
}

export interface InventorySkuHealth {
  product_id: string;
  sku_id: string;
  days_of_inventory_remaining: number;
  reorder_lead_time_days: number;
  lead_time_coverage_ratio: number;
}

export interface InventoryHealthIndicator extends HealthIndicatorBase {
  indicator_id: "inventory_health";
  skus: InventorySkuHealth[];
  at_risk_sku_count: number;
}

export interface RefundSpikeIndicator extends HealthIndicatorBase {
  indicator_id: "refund_spike_indicator";
  refund_rate_7d: number;
  refund_rate_30d: number;
  baseline_refund_rate_30d: number;
  percent_change_vs_baseline: number;
  spike_detected: boolean;
}

export interface ProductScalingCandidate {
  product_id: string;
  sku_id: string;
  product_name: string;
  growth_potential_score: number;
  units_sold_7d: number;
  margin_pct: number;
}

export interface ProductScalingOpportunityIndicator extends HealthIndicatorBase {
  indicator_id: "product_scaling_opportunity";
  top_skus: ProductScalingCandidate[];
}

export type HealthIndicator =
  | ProbationProgressIndicator
  | SpsHealthIndicator
  | AhrHealthIndicator
  | AdRoasEfficiencyIndicator
  | InventoryHealthIndicator
  | RefundSpikeIndicator
  | ProductScalingOpportunityIndicator;

export type HealthCheckIndicators = {
  [K in HealthIndicatorId]: Extract<HealthIndicator, { indicator_id: K }>;
};

/**
 * Stable P1.8 output envelope for the operations pipeline health stage.
 * P2 swaps loaders; schema shape remains stable per ADR-013.
 */
export interface HealthCheckResults {
  shop_id: string;
  computed_at: string;
  health_data_source: HealthDataSource;
  indicators: HealthCheckIndicators;
}

/**
 * Indicator→workflow traceability map (ADR-013 constraint #5).
 * Every health indicator must inform ≥1 validated workflow decision.
 */
export const HEALTH_INDICATOR_TRACEABILITY_MAP: Readonly<
  Record<HealthIndicatorId, readonly ValidatedWorkflowId[]>
> = {
  probation_progress: ["npl", "minimize_violations"],
  sps_health: ["npl", "minimize_violations"],
  ahr_health: ["npl", "minimize_violations"],
  ad_roas_efficiency: ["budget_optimization"],
  inventory_health: ["stockout_prevention"],
  refund_spike_indicator: ["refund_spike_detection"],
  product_scaling_opportunity: ["product_scaling"],
};

/** Target ROAS for budget optimization efficiency scoring (mock P1.8). */
export const TARGET_ROAS = 5.0;

/** Refund spike threshold — matches ADR-013 Appendix C preconditions. */
export const REFUND_SPIKE_THRESHOLD_RATIO = 0.2;

const MS_PER_DAY = 86_400_000;

function notApplicableIndicator<T extends HealthIndicator>(
  indicator: T,
): T {
  return {
    ...indicator,
    severity: "not_applicable",
    summary: "Không áp dụng cho dữ liệu hiện tại",
  };
}

function scoreSeverityFromGap(
  current: number,
  threshold: number,
): HealthIndicatorSeverity {
  if (current >= threshold) {
    return "healthy";
  }

  const gapRatio = (threshold - current) / threshold;
  return gapRatio > 0.15 ? "critical" : "warning";
}

function computeProbationProgress(
  model: UnifiedOperationalDataModel,
): ProbationProgressIndicator {
  const base: ProbationProgressIndicator = {
    indicator_id: "probation_progress",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.probation_progress],
    severity: "not_applicable",
    summary: "",
    percent_toward_graduation: 0,
    days_remaining: 0,
  };

  if (model.probation === null) {
    return notApplicableIndicator(base);
  }

  const { probation_end_date, sps_current, sps_threshold, ahr_current, ahr_threshold } =
    model.probation;

  const collectedAt = new Date(model.collected_at).getTime();
  const endMs = new Date(probation_end_date).getTime();
  const daysRemaining = Math.max(0, Math.ceil((endMs - collectedAt) / MS_PER_DAY));

  const spsProgress = Math.min(100, (sps_current / sps_threshold) * 100);
  const ahrProgress = Math.min(100, (ahr_current / ahr_threshold) * 100);
  const percentTowardGraduation = Math.round(((spsProgress + ahrProgress) / 2) * 10) / 10;

  const severity: HealthIndicatorSeverity =
    percentTowardGraduation >= 100
      ? "healthy"
      : percentTowardGraduation >= 75
        ? "warning"
        : "critical";

  return {
    ...base,
    severity,
    summary: `${percentTowardGraduation}% tiến độ tốt nghiệp, còn ${daysRemaining} ngày`,
    percent_toward_graduation: percentTowardGraduation,
    days_remaining: daysRemaining,
  };
}

function computeSpsHealth(model: UnifiedOperationalDataModel): SpsHealthIndicator {
  const base: SpsHealthIndicator = {
    indicator_id: "sps_health",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.sps_health],
    severity: "not_applicable",
    summary: "",
    sps_current: 0,
    sps_threshold: 0,
    threshold_gap: 0,
  };

  if (model.probation === null) {
    return notApplicableIndicator(base);
  }

  const { sps_current, sps_threshold } = model.probation;
  const thresholdGap = Math.max(0, sps_threshold - sps_current);
  const severity = scoreSeverityFromGap(sps_current, sps_threshold);

  return {
    ...base,
    severity,
    summary: `SPS ${sps_current}/${sps_threshold} (thiếu ${thresholdGap.toFixed(1)} điểm)`,
    sps_current,
    sps_threshold,
    threshold_gap: thresholdGap,
  };
}

function computeAhrHealth(model: UnifiedOperationalDataModel): AhrHealthIndicator {
  const base: AhrHealthIndicator = {
    indicator_id: "ahr_health",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.ahr_health],
    severity: "not_applicable",
    summary: "",
    ahr_current: 0,
    ahr_threshold: 0,
    threshold_gap: 0,
  };

  if (model.probation === null) {
    return notApplicableIndicator(base);
  }

  const { ahr_current, ahr_threshold } = model.probation;
  const thresholdGap = Math.max(0, ahr_threshold - ahr_current);
  const severity = scoreSeverityFromGap(ahr_current, ahr_threshold);

  return {
    ...base,
    severity,
    summary: `AHR ${ahr_current}/${ahr_threshold} (thiếu ${thresholdGap} điểm)`,
    ahr_current,
    ahr_threshold,
    threshold_gap: thresholdGap,
  };
}

function computeAdRoasEfficiency(
  model: UnifiedOperationalDataModel,
): AdRoasEfficiencyIndicator {
  const base: AdRoasEfficiencyIndicator = {
    indicator_id: "ad_roas_efficiency",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.ad_roas_efficiency],
    severity: "not_applicable",
    summary: "",
    target_roas: TARGET_ROAS,
    campaigns: [],
    active_campaigns_below_target_pct: 0,
  };

  const activeCampaigns = model.ad_campaigns.filter((campaign) => campaign.status === "active");
  if (activeCampaigns.length === 0) {
    return notApplicableIndicator(base);
  }

  const campaigns: AdRoasCampaignSnapshot[] = activeCampaigns.map((campaign) => {
    const percentBelowTarget =
      campaign.roas >= TARGET_ROAS
        ? 0
        : Math.round(((TARGET_ROAS - campaign.roas) / TARGET_ROAS) * 1000) / 10;

    return {
      campaign_id: campaign.campaign_id,
      campaign_name: campaign.campaign_name,
      roas: campaign.roas,
      target_roas: TARGET_ROAS,
      percent_below_target: percentBelowTarget,
    };
  });

  const belowTargetCount = campaigns.filter((campaign) => campaign.percent_below_target > 0).length;
  const activeCampaignsBelowTargetPct =
    Math.round((belowTargetCount / campaigns.length) * 1000) / 10;

  let severity: HealthIndicatorSeverity = "healthy";
  if (activeCampaignsBelowTargetPct >= 50) {
    severity = "critical";
  } else if (belowTargetCount > 0) {
    severity = "warning";
  }

  return {
    ...base,
    severity,
    summary: `${belowTargetCount}/${campaigns.length} chiến dịch active dưới ROAS mục tiêu ${TARGET_ROAS}`,
    campaigns,
    active_campaigns_below_target_pct: activeCampaignsBelowTargetPct,
  };
}

function computeInventoryHealth(
  model: UnifiedOperationalDataModel,
): InventoryHealthIndicator {
  const base: InventoryHealthIndicator = {
    indicator_id: "inventory_health",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.inventory_health],
    severity: "not_applicable",
    summary: "",
    skus: [],
    at_risk_sku_count: 0,
  };

  if (model.inventory.length === 0) {
    return notApplicableIndicator(base);
  }

  const skus: InventorySkuHealth[] = model.inventory.map((item) => {
    const daysRemaining =
      item.sales_velocity_units_per_day > 0
        ? Math.round((item.inventory_level / item.sales_velocity_units_per_day) * 10) / 10
        : Infinity;
    const leadTimeCoverage =
      item.reorder_lead_time_days > 0 && Number.isFinite(daysRemaining)
        ? Math.round((daysRemaining / item.reorder_lead_time_days) * 1000) / 1000
        : 0;

    return {
      product_id: item.product_id,
      sku_id: item.sku_id,
      days_of_inventory_remaining: daysRemaining,
      reorder_lead_time_days: item.reorder_lead_time_days,
      lead_time_coverage_ratio: leadTimeCoverage,
    };
  });

  const atRiskSkuCount = skus.filter(
    (sku) =>
      Number.isFinite(sku.days_of_inventory_remaining) &&
      sku.lead_time_coverage_ratio < 1,
  ).length;

  let severity: HealthIndicatorSeverity = "healthy";
  if (atRiskSkuCount >= 2) {
    severity = "critical";
  } else if (atRiskSkuCount === 1) {
    severity = "warning";
  }

  return {
    ...base,
    severity,
    summary: `${atRiskSkuCount} SKU có tồn kho dưới thời gian giao hàng`,
    skus,
    at_risk_sku_count: atRiskSkuCount,
  };
}

function computeRefundSpike(
  model: UnifiedOperationalDataModel,
): RefundSpikeIndicator {
  const { refund_rate_7d, refund_rate_30d, baseline_refund_rate_30d } = model.returns;

  const percentChangeVsBaseline =
    baseline_refund_rate_30d > 0
      ? Math.round(
          ((refund_rate_7d - baseline_refund_rate_30d) / baseline_refund_rate_30d) * 1000,
        ) / 10
      : 0;

  const spikeDetected = percentChangeVsBaseline / 100 > REFUND_SPIKE_THRESHOLD_RATIO;

  let severity: HealthIndicatorSeverity = "healthy";
  if (spikeDetected) {
    severity = "critical";
  } else if (refund_rate_7d > refund_rate_30d) {
    severity = "warning";
  }

  return {
    indicator_id: "refund_spike_indicator",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.refund_spike_indicator],
    severity,
    summary: spikeDetected
      ? `Tỷ lệ hoàn ${(refund_rate_7d * 100).toFixed(1)}% — tăng ${percentChangeVsBaseline}% so với baseline`
      : `Tỷ lệ hoàn 7 ngày ${(refund_rate_7d * 100).toFixed(1)}% ổn định`,
    refund_rate_7d,
    refund_rate_30d,
    baseline_refund_rate_30d,
    percent_change_vs_baseline: percentChangeVsBaseline,
    spike_detected: spikeDetected,
  };
}

function computeProductScalingOpportunity(
  model: UnifiedOperationalDataModel,
): ProductScalingOpportunityIndicator {
  const base: ProductScalingOpportunityIndicator = {
    indicator_id: "product_scaling_opportunity",
    informs_workflows: [...HEALTH_INDICATOR_TRACEABILITY_MAP.product_scaling_opportunity],
    severity: "not_applicable",
    summary: "",
    top_skus: [],
  };

  if (model.products.length === 0) {
    return notApplicableIndicator(base);
  }

  const topSkus: ProductScalingCandidate[] = model.products
    .map((product) => {
      const dailyVelocity7d = product.units_sold_7d / 7;
      const dailyVelocity30d = product.units_sold_30d / 30;
      const momentum =
        dailyVelocity30d > 0 ? dailyVelocity7d / dailyVelocity30d : dailyVelocity7d;
      const growthPotentialScore =
        Math.round(momentum * product.margin_pct * product.sell_through_rate * 100) / 100;

      return {
        product_id: product.product_id,
        sku_id: product.sku_id,
        product_name: product.product_name,
        growth_potential_score: growthPotentialScore,
        units_sold_7d: product.units_sold_7d,
        margin_pct: product.margin_pct,
      };
    })
    .sort((a, b) => b.growth_potential_score - a.growth_potential_score)
    .slice(0, 3);

  const topScore = topSkus[0]?.growth_potential_score ?? 0;
  let severity: HealthIndicatorSeverity = "healthy";
  if (topScore >= 30) {
    severity = "warning";
  } else if (topScore < 5) {
    severity = "healthy";
  }

  return {
    ...base,
    severity,
    summary:
      topSkus.length > 0
        ? `${topSkus.length} SKU hàng đầu theo tiềm năng mở rộng`
        : "Chưa có SKU phù hợp để mở rộng",
    top_skus: topSkus,
  };
}

/**
 * Rules-based health check (P1.8-3).
 * Computes all mock indicators from unified operational data per system-design.md.
 */
export function computeHealthCheckResults(
  unifiedModel: UnifiedOperationalDataModel,
): HealthCheckResults {
  return {
    shop_id: unifiedModel.shop_metadata.shop_id,
    computed_at: unifiedModel.collected_at,
    health_data_source: unifiedModel.health_data_source,
    indicators: {
      probation_progress: computeProbationProgress(unifiedModel),
      sps_health: computeSpsHealth(unifiedModel),
      ahr_health: computeAhrHealth(unifiedModel),
      ad_roas_efficiency: computeAdRoasEfficiency(unifiedModel),
      inventory_health: computeInventoryHealth(unifiedModel),
      refund_spike_indicator: computeRefundSpike(unifiedModel),
      product_scaling_opportunity: computeProductScalingOpportunity(unifiedModel),
    },
  };
}

export function getWorkflowsForHealthIndicator(
  indicatorId: HealthIndicatorId,
): readonly ValidatedWorkflowId[] {
  return HEALTH_INDICATOR_TRACEABILITY_MAP[indicatorId];
}
