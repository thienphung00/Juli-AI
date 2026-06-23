import type { HealthCheckResults } from "@/lib/operations/health-check";
import { formatNumber } from "@/lib/format";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

export interface DecisionAnalyticsMetric {
  key: string;
  label: string;
  value: string;
  trend?: string;
}

export function buildDecisionAnalytics(
  recommendation: WorkflowRecommendation,
  health: HealthCheckResults,
): DecisionAnalyticsMetric[] {
  const workflowId = recommendation.workflow_id;

  switch (workflowId) {
    case "npl": {
      const probation = health.indicators.probation_progress;
      const sps = health.indicators.sps_health;
      return [
        {
          key: "probation",
          label: "Tiến độ thử việc",
          value: `${formatNumber(probation.percent_toward_graduation)}%`,
          trend: `${formatNumber(probation.days_remaining)} ngày còn lại`,
        },
        {
          key: "sps",
          label: "SPS hiện tại",
          value: `${formatNumber(sps.sps_current)}/${formatNumber(sps.sps_threshold)}`,
          trend: `Thiếu ${formatNumber(sps.threshold_gap)} điểm`,
        },
      ];
    }
    case "refund_spike_detection": {
      const refund = health.indicators.refund_spike_indicator;
      return [
        {
          key: "refund_rate",
          label: "Tỷ lệ hoàn tiền 7 ngày",
          value: `${formatNumber(refund.refund_rate_7d * 100)}%`,
          trend: refund.spike_detected ? "Đang tăng" : "Ổn định",
        },
        {
          key: "baseline_delta",
          label: "So với baseline",
          value: `${formatNumber(refund.percent_change_vs_baseline)}%`,
        },
      ];
    }
    case "budget_optimization": {
      const ads = health.indicators.ad_roas_efficiency;
      const topCampaign = ads.campaigns[0];
      return [
        {
          key: "roas",
          label: "ROAS chiến dịch hàng đầu",
          value: topCampaign ? formatNumber(topCampaign.roas) : "—",
          trend: `Mục tiêu ${formatNumber(ads.target_roas)}`,
        },
        {
          key: "below_target",
          label: "Chiến dịch dưới mục tiêu",
          value: `${formatNumber(ads.active_campaigns_below_target_pct)}%`,
        },
      ];
    }
    default:
      return [
        {
          key: "impact",
          label: recommendation.expected_impact.metric,
          value: formatNumber(recommendation.expected_impact.value),
          trend: `Độ tin cậy ${recommendation.expected_impact.confidence}`,
        },
        {
          key: "priority",
          label: "Ưu tiên",
          value: `#${recommendation.priority}`,
        },
      ];
  }
}

export const DECISION_PREVIEW_RISKS: Record<string, string[]> = {
  npl: ["Listing chưa đạt chuẩn có thể bị từ chối", "Cần theo dõi SPS sau khi đăng"],
  minimize_violations: ["Vi phạm mới có thể phát sinh trước khi Phase 2 bật thực thi"],
  budget_optimization: ["ROAS có thể dao động trong 3–5 ngày đầu"],
  product_scaling: ["Tồn kho chưa đủ có thể hạn chế mở rộng SKU"],
  refund_spike_detection: ["Hoàn tiền cao có thể ảnh hưởng AHR nếu không xử lý"],
  stockout_prevention: ["Lead time nhà cung cấp có thể làm trễ bổ sung hàng"],
};

export function getDecisionPreviewRisks(workflowId: string): string[] {
  return DECISION_PREVIEW_RISKS[workflowId] ?? ["Rủi ro thấp trong phiên demo P1.8"];
}

export const DECISIONS_RECOMMENDED_SCROLL_KEY = "decisions-recommended-scroll";

export function saveDecisionsRecommendedScroll(): void {
  if (typeof window === "undefined") {
    return;
  }
  sessionStorage.setItem(DECISIONS_RECOMMENDED_SCROLL_KEY, String(window.scrollY));
}

export function restoreDecisionsRecommendedScroll(): void {
  if (typeof window === "undefined") {
    return;
  }
  const raw = sessionStorage.getItem(DECISIONS_RECOMMENDED_SCROLL_KEY);
  if (raw === null) {
    return;
  }
  const y = Number.parseInt(raw, 10);
  if (Number.isFinite(y)) {
    window.scrollTo({ top: y, behavior: "instant" as ScrollBehavior });
  }
  sessionStorage.removeItem(DECISIONS_RECOMMENDED_SCROLL_KEY);
}
