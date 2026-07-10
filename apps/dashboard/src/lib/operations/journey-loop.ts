import {
  VALIDATED_WORKFLOW_IDS,
  type ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";

import { resolveMetricWorkflowId } from "./metric-action-mapping";
import { REPORT_DOMAIN_IDS, type ReportDomainId } from "./todays-report";

export type RecentProgressState = "pending" | "completed";

export interface HomeMetricAnchor {
  reportDomain: ReportDomainId | "shop_health";
  metricKey: string;
}

export interface JourneyLink {
  workflowId: ValidatedWorkflowId;
  reportDomain: ReportDomainId | "shop_health";
  metricKey: string;
  rewardLabel: string;
  reasonTemplate: string;
  anticipationTemplate: string;
}

interface JourneyLinkDefinition {
  reportDomain: ReportDomainId | "shop_health";
  metricKey: string;
  rewardLabel: string;
  reasonTemplate: string;
  anticipationTemplate: string;
}

const JOURNEY_LINK_REGISTRY: Record<ValidatedWorkflowId, JourneyLinkDefinition> = {
  product_scaling: {
    reportDomain: "product_listings",
    metricKey: "product_count",
    rewardLabel: "Sản phẩm · Sản phẩm đang bán",
    reasonTemplate:
      "Doanh thu 7 ngày tăng **10,7%** nhưng **2 SKU** chiếm **>60%** doanh thu — mở rộng biên lợi nhuận trước khi tăng trưởng chậm lại.",
    anticipationTemplate:
      "**+₫12,4M** doanh thu/tuần dự kiến khi scale top SKU (ROAS hiện tại **4,2x**).",
  },
  budget_optimization: {
    reportDomain: "revenue_growth",
    metricKey: "roas",
    rewardLabel: "Tăng trưởng · ROAS trung bình",
    reasonTemplate:
      "ROAS trung bình **2,1x** — **3/5** chiến dịch dưới ngưỡng mục tiêu **3x**, làm lãng phí **₫2,8M/tuần**.",
    anticipationTemplate:
      "Cải thiện ROAS lên **+0,8x** → tiết kiệm **~₫2,8M/tuần** chi tiêu quảng cáo.",
  },
  refund_spike_detection: {
    reportDomain: "inventory_refunds",
    metricKey: "refund_rate_7d",
    rewardLabel: "Tồn kho & Hoàn tiền · Tỷ lệ hoàn 7 ngày",
    reasonTemplate:
      "Tỷ lệ hoàn 7 ngày **8,2%** — cao hơn **42%** so với baseline **30 ngày**; **12** yêu cầu chờ duyệt.",
    anticipationTemplate:
      "Giảm tỷ lệ hoàn **~1,5 điểm %** → ngăn rò rỉ **~₫4,1M/tuần**.",
  },
  stockout_prevention: {
    reportDomain: "inventory_refunds",
    metricKey: "low_stock_rate",
    rewardLabel: "Tồn kho & Hoàn tiền · Tỷ lệ tồn kho dưới ngưỡng",
    reasonTemplate:
      "**2 SKU** chỉ còn **≤7 ngày** tồn kho tại tốc độ bán hiện tại — nguy cơ hết hàng làm gián đoạn doanh thu.",
    anticipationTemplate:
      "Duy trì **0** lần hết hàng không kế hoạch trong **30 ngày** → bảo toàn doanh thu cho SKU đang scale.",
  },
  npl: {
    reportDomain: "product_listings",
    metricKey: "product_count",
    rewardLabel: "Sản phẩm · Sản phẩm đang bán",
    reasonTemplate:
      "Shop đang thử việc với **4** sản phẩm — cần thêm listing đạt Standard để đủ điều kiện tốt nghiệp.",
    anticipationTemplate: "**+3 listing** đạt Standard → SPS **+4,2 điểm**.",
  },
  minimize_violations: {
    reportDomain: "shop_health",
    metricKey: "ahr",
    rewardLabel: "Sức khỏe cửa hàng · AHR",
    reasonTemplate:
      "**2** vi phạm mức cao đang mở — AHR dưới ngưỡng an toàn, cần xử lý trước khi ảnh hưởng hiển thị shop.",
    anticipationTemplate: "AHR **+6 điểm** dự kiến khi xử lý **2** vi phạm mức cao.",
  },
};

const VALIDATED_WORKFLOW_ID_SET = new Set<string>(VALIDATED_WORKFLOW_IDS);
const REPORT_DOMAIN_SET = new Set<string>([...REPORT_DOMAIN_IDS, "shop_health"]);

const METRIC_JOURNEY_OVERRIDES: Partial<
  Record<ReportDomainId, Partial<Record<string, ValidatedWorkflowId>>>
> = {
  revenue_growth: {
    revenue_7d: "budget_optimization",
    units_sold_7d: "budget_optimization",
  },
  inventory_refunds: {
    pending_return_count: "refund_spike_detection",
  },
};

const METRIC_JOURNEY_REASON_OVERRIDES: Partial<
  Record<ReportDomainId, Partial<Record<string, string>>>
> = {
  inventory_refunds: {
    pending_return_count:
      "Chưa có yêu cầu hoàn tiền chờ duyệt — theo dõi tỷ lệ hoàn 7 ngày để phát hiện rò rỉ sớm.",
  },
};

export function resolveJourneyLinkForMetric(
  reportDomain: ReportDomainId,
  metricKey: string,
): JourneyLink | null {
  const workflowId = resolveMetricWorkflowId(reportDomain, metricKey);
  if (workflowId) {
    const link = getJourneyLink(workflowId);
    if (!link) {
      return null;
    }

    const reasonOverride =
      METRIC_JOURNEY_REASON_OVERRIDES[reportDomain]?.[metricKey];
    if (!reasonOverride) {
      return link;
    }

    return {
      ...link,
      reportDomain,
      metricKey,
      reasonTemplate: reasonOverride,
    };
  }

  for (const id of VALIDATED_WORKFLOW_IDS) {
    const link = getJourneyLink(id);
    if (link?.reportDomain === reportDomain && link.metricKey === metricKey) {
      return link;
    }
  }

  const overrideWorkflowId = METRIC_JOURNEY_OVERRIDES[reportDomain]?.[metricKey];
  if (overrideWorkflowId) {
    return getJourneyLink(overrideWorkflowId);
  }

  return null;
}

export function getJourneyLink(workflowId: ValidatedWorkflowId): JourneyLink | null {
  const definition = JOURNEY_LINK_REGISTRY[workflowId];
  if (!definition) {
    return null;
  }

  return {
    workflowId,
    ...definition,
  };
}

export function resolveHomeHighlight(
  workflowId: ValidatedWorkflowId,
): HomeMetricAnchor | null {
  const link = getJourneyLink(workflowId);
  if (!link) {
    return null;
  }

  return {
    reportDomain: link.reportDomain,
    metricKey: link.metricKey,
  };
}

export function formatAnticipationImpact(workflowId: ValidatedWorkflowId): string {
  return getJourneyLink(workflowId)?.anticipationTemplate ?? "";
}

export function buildDecisionsHighlightLink(workflowId: ValidatedWorkflowId): string | null {
  if (!VALIDATED_WORKFLOW_ID_SET.has(workflowId)) {
    return null;
  }

  return `/decisions?highlight=${workflowId}`;
}

export function buildHomeHighlightLink(anchor: HomeMetricAnchor): string {
  return `/?highlight=${anchor.reportDomain}:${anchor.metricKey}`;
}

export function parseDecisionsHighlight(
  value: string | null | undefined,
): ValidatedWorkflowId | null {
  if (!value || !VALIDATED_WORKFLOW_ID_SET.has(value)) {
    return null;
  }

  return value as ValidatedWorkflowId;
}

export function parseHomeHighlight(value: string | null | undefined): HomeMetricAnchor | null {
  if (!value) {
    return null;
  }

  const separatorIndex = value.indexOf(":");
  if (separatorIndex <= 0 || separatorIndex === value.length - 1) {
    return null;
  }

  const reportDomain = value.slice(0, separatorIndex);
  const metricKey = value.slice(separatorIndex + 1);

  if (!REPORT_DOMAIN_SET.has(reportDomain) || metricKey.length === 0) {
    return null;
  }

  return {
    reportDomain: reportDomain as HomeMetricAnchor["reportDomain"],
    metricKey,
  };
}
