"use client";

import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";
import { AHR_METRIC, SPS_METRIC } from "@/lib/metrics/shop-health-metrics";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import {
  HealthMetricBar,
  deriveShopHealthEstimates,
} from "./HealthMetricBar";

export function ShopHealthCard({
  model,
  recommendations = [],
  highlightedMetricKey = null,
  shopHealthMetricKey = null,
}: {
  model: UnifiedOperationalDataModel;
  recommendations?: WorkflowRecommendation[];
  highlightedMetricKey?: string | null;
  shopHealthMetricKey?: string | null;
}) {
  const probation = model.probation;

  return (
    <section className="card space-y-4 p-4" data-testid="shop-health-card">
      {probation ? (
        (() => {
          const { spsEstimated, ahrEstimated } = deriveShopHealthEstimates(
            probation.sps_current,
            probation.ahr_current,
            recommendations,
          );

          return (
            <>
              <HealthMetricBar
                label={SPS_METRIC.label}
                current={probation.sps_current}
                estimated={spsEstimated}
                scaleMax={5}
                testId="shop-health-sps"
                metricKind="sps"
                recommendations={recommendations}
                highlighted={
                  shopHealthMetricKey === "sps" && highlightedMetricKey === "sps"
                }
              />
              <HealthMetricBar
                label={AHR_METRIC.label}
                current={probation.ahr_current}
                estimated={ahrEstimated}
                scaleMax={1000}
                testId="shop-health-ahr"
                metricKind="ahr"
                recommendations={recommendations}
                highlighted={
                  shopHealthMetricKey === "ahr" && highlightedMetricKey === "ahr"
                }
              />
            </>
          );
        })()
      ) : (
        <p className="text-muted text-sm" data-testid="shop-health-unavailable">
          Chỉ số SPS/AHR chỉ áp dụng cho shop đang trong giai đoạn thử nghiệm.
        </p>
      )}
    </section>
  );
}
