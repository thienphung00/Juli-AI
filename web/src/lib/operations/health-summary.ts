import type { ShopProfileType } from "@/lib/mock-data/operations/schemas";

import type { HealthCheckResults, HealthIndicatorSeverity } from "./health-check";

export interface ShopHealthSummary {
  score: number;
  criticalCount: number;
  warningCount: number;
  healthyCount: number;
  applicableCount: number;
}

const PROFILE_INDICATORS: Record<ShopProfileType, readonly string[]> = {
  NEW_SHOP: ["probation_progress", "sps_health", "ahr_health"],
  MID_LARGE_SHOP: [
    "ad_roas_efficiency",
    "inventory_health",
    "refund_spike_indicator",
    "product_scaling_opportunity",
  ],
};

function isApplicableSeverity(severity: HealthIndicatorSeverity): boolean {
  return severity !== "not_applicable";
}

/**
 * Derives a simple shop health score from applicable indicator severities (P1.8-6 hero).
 */
export function computeShopHealthSummary(
  profile: ShopProfileType,
  health: HealthCheckResults,
): ShopHealthSummary {
  const indicatorIds = PROFILE_INDICATORS[profile];
  let criticalCount = 0;
  let warningCount = 0;
  let healthyCount = 0;
  let applicableCount = 0;

  for (const indicatorId of indicatorIds) {
    const indicator = health.indicators[indicatorId as keyof typeof health.indicators];
    if (!isApplicableSeverity(indicator.severity)) {
      continue;
    }

    applicableCount += 1;
    if (indicator.severity === "critical") {
      criticalCount += 1;
    } else if (indicator.severity === "warning") {
      warningCount += 1;
    } else {
      healthyCount += 1;
    }
  }

  const score =
    applicableCount === 0
      ? 100
      : Math.round((healthyCount / applicableCount) * 100);

  return {
    score,
    criticalCount,
    warningCount,
    healthyCount,
    applicableCount,
  };
}
