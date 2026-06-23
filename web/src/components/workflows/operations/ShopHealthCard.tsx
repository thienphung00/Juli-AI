"use client";

import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";
import { AHR_METRIC, SPS_METRIC } from "@/lib/metrics/shop-health-metrics";

import { HealthMetricBar } from "./HealthMetricBar";

export function ShopHealthCard({ model }: { model: UnifiedOperationalDataModel }) {
  const probation = model.probation;

  return (
    <section className="card space-y-4 p-4" data-testid="shop-health-card">
      <div>
        <p className="text-muted text-xs font-medium uppercase tracking-wide">Sức khỏe cửa hàng</p>
        <p className="text-muted mt-1 text-sm">SPS và AHR là chỉ số quan trọng nhất trên Trang chủ.</p>
      </div>

      {probation ? (
        <>
          <HealthMetricBar
            label={SPS_METRIC.label}
            description={SPS_METRIC.description}
            current={probation.sps_current}
            target={probation.sps_threshold}
            testId="shop-health-sps"
          />
          <HealthMetricBar
            label={AHR_METRIC.label}
            description={AHR_METRIC.description}
            current={probation.ahr_current}
            target={probation.ahr_threshold}
            testId="shop-health-ahr"
          />
        </>
      ) : (
        <p className="text-muted text-sm" data-testid="shop-health-unavailable">
          Chỉ số SPS/AHR chỉ áp dụng cho shop đang trong giai đoạn thử nghiệm.
        </p>
      )}
    </section>
  );
}
