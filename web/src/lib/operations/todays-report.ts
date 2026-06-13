import type {
  ShopProfileType,
  UnifiedOperationalDataModel,
} from "@/lib/mock-data/operations/schemas";
import { formatNumber, formatVND } from "@/lib/format";

export const REPORT_DOMAIN_IDS = [
  "revenue_growth",
  "product_listings",
  "inventory_refunds",
] as const;

export type ReportDomainId = (typeof REPORT_DOMAIN_IDS)[number];

export type TrendDirection = "up" | "down" | "neutral";

export type DomainStatusTone = "healthy" | "warning" | "critical" | "neutral" | "empty";

const TARGET_ROAS = 3;

export interface MetricDelta {
  label: string;
  metricKey: string;
  value: string;
  deltaLabel?: string;
  direction?: TrendDirection;
  realValue: number;
  estimatedValue: number;
  scaleMax: number;
  estimatedGainLabel?: string;
}

export interface DomainReportSummary {
  domainId: ReportDomainId;
  title: string;
  shortLabel: string;
  statusLabel: string;
  statusTone: DomainStatusTone;
  trend: TrendDirection;
  trendLabel: string;
  metrics: MetricDelta[];
  isEmpty: boolean;
}

const DOMAIN_TITLES: Record<ReportDomainId, { title: string; shortLabel: string }> = {
  revenue_growth: { title: "Tăng trưởng doanh thu", shortLabel: "Tăng trưởng" },
  product_listings: { title: "Danh sách sản phẩm", shortLabel: "Sản phẩm" },
  inventory_refunds: {
    title: "Tồn kho & Hoàn tiền",
    shortLabel: "Tồn kho & Hoàn tiền",
  },
};

const TREND_LABELS: Record<TrendDirection, string> = {
  up: "Tăng so với kỳ trước",
  down: "Giảm so với kỳ trước",
  neutral: "Ổn định so với kỳ trước",
};

function computeTrend(
  current: number,
  prior: number,
): { direction: TrendDirection; deltaPct: number } {
  if (current === 0 && prior === 0) {
    return { direction: "neutral", deltaPct: 0 };
  }
  if (prior === 0) {
    return { direction: "up", deltaPct: 100 };
  }

  const deltaPct = ((current - prior) / prior) * 100;
  if (Math.abs(deltaPct) < 2) {
    return { direction: "neutral", deltaPct };
  }

  return { direction: deltaPct > 0 ? "up" : "down", deltaPct };
}

function formatDeltaPct(deltaPct: number): string {
  const rounded = Math.round(deltaPct * 10) / 10;
  const sign = rounded > 0 ? "+" : "";
  return `${sign}${rounded}%`;
}

function formatRatePct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function scaleHeadroom(real: number, estimated: number): number {
  return Math.max(real, estimated, 1) * 1.05;
}

function computeBlendedRoas(model: UnifiedOperationalDataModel): number {
  const totalSpend = model.ad_campaigns.reduce((sum, campaign) => sum + campaign.spend_vnd, 0);
  const totalRevenue = model.ad_campaigns.reduce((sum, campaign) => sum + campaign.revenue_vnd, 0);
  return totalSpend > 0 ? totalRevenue / totalSpend : 0;
}

function computeLowStockRate(model: UnifiedOperationalDataModel): number {
  if (model.inventory.length === 0) {
    return 0;
  }

  const atRiskCount = model.inventory.filter((item) => {
    if (item.sales_velocity_units_per_day <= 0) {
      return false;
    }
    const daysRemaining = item.inventory_level / item.sales_velocity_units_per_day;
    return item.reorder_lead_time_days > 0 && daysRemaining < item.reorder_lead_time_days;
  }).length;

  return atRiskCount / model.inventory.length;
}

function buildSummary(
  domainId: ReportDomainId,
  input: Omit<DomainReportSummary, "domainId" | "title" | "shortLabel" | "trendLabel">,
): DomainReportSummary {
  const labels = DOMAIN_TITLES[domainId];
  return {
    domainId,
    title: labels.title,
    shortLabel: labels.shortLabel,
    trendLabel: TREND_LABELS[input.trend],
    ...input,
  };
}

function buildRevenueGrowthSummary(model: UnifiedOperationalDataModel): DomainReportSummary {
  const revenue7d = model.products.reduce((sum, product) => sum + product.revenue_vnd_7d, 0);
  const revenuePrior = model.products.reduce(
    (sum, product) => sum + product.revenue_vnd_30d / 4,
    0,
  );
  const units7d = model.products.reduce((sum, product) => sum + product.units_sold_7d, 0);
  const unitsPrior = model.products.reduce(
    (sum, product) => sum + product.units_sold_30d / 4,
    0,
  );
  const blendedRoas = computeBlendedRoas(model);
  const revenueTrend = computeTrend(revenue7d, revenuePrior);
  const unitsTrend = computeTrend(units7d, unitsPrior);
  const roasTrend = computeTrend(blendedRoas, TARGET_ROAS * 0.7);

  const revenueEstimated = Math.round(revenue7d * 1.107);
  const unitsEstimated = Math.round(units7d * 1.107);
  const roasEstimated = Math.min(TARGET_ROAS, Math.round((blendedRoas + 0.8) * 100) / 100);

  const statusTone: DomainStatusTone =
    revenueTrend.direction === "down"
      ? "warning"
      : revenueTrend.direction === "up"
        ? "healthy"
        : "neutral";

  const hasCampaigns = model.ad_campaigns.length > 0;
  const metrics: MetricDelta[] = [
    {
      label: "Doanh thu 7 ngày",
      metricKey: "revenue_7d",
      value: formatVND(revenue7d),
      deltaLabel: formatDeltaPct(revenueTrend.deltaPct),
      direction: revenueTrend.direction,
      realValue: revenue7d,
      estimatedValue: revenueEstimated,
      scaleMax: scaleHeadroom(revenue7d, revenueEstimated),
      estimatedGainLabel: `+${formatVND(revenueEstimated - revenue7d)} if approved`,
    },
    {
      label: "Đơn vị bán 7 ngày",
      metricKey: "units_sold_7d",
      value: formatNumber(units7d),
      deltaLabel: formatDeltaPct(unitsTrend.deltaPct),
      direction: unitsTrend.direction,
      realValue: units7d,
      estimatedValue: unitsEstimated,
      scaleMax: scaleHeadroom(units7d, unitsEstimated),
      estimatedGainLabel: `+${formatNumber(unitsEstimated - units7d)} đơn if approved`,
    },
  ];

  if (hasCampaigns) {
    metrics.push({
      label: "ROAS trung bình",
      metricKey: "roas",
      value: `${blendedRoas.toFixed(2)}x`,
      deltaLabel: formatDeltaPct(roasTrend.deltaPct),
      direction: roasTrend.direction,
      realValue: blendedRoas,
      estimatedValue: roasEstimated,
      scaleMax: scaleHeadroom(blendedRoas, roasEstimated),
      estimatedGainLabel: `+${(roasEstimated - blendedRoas).toFixed(1)}x ROAS if approved`,
    });
  }

  return buildSummary("revenue_growth", {
    statusLabel:
      statusTone === "healthy"
        ? "Đang tăng trưởng"
        : statusTone === "warning"
          ? "Cần theo dõi"
          : "Ổn định",
    statusTone,
    trend: revenueTrend.direction,
    metrics,
    isEmpty: model.products.length === 0,
  });
}

function buildProductListingsSummary(model: UnifiedOperationalDataModel): DomainReportSummary {
  const productCount = model.products.length;
  if (productCount === 0) {
    return buildSummary("product_listings", {
      statusLabel: "Chưa có dữ liệu",
      statusTone: "empty",
      trend: "neutral",
      metrics: [],
      isEmpty: true,
    });
  }

  const units7d = model.products.reduce((sum, product) => sum + product.units_sold_7d, 0);
  const unitsPrior = model.products.reduce(
    (sum, product) => sum + product.units_sold_30d / 4,
    0,
  );
  const unitsTrend = computeTrend(units7d, unitsPrior);
  const productEstimated = productCount + 1;

  return buildSummary("product_listings", {
    statusLabel: "Đang phát triển",
    statusTone: "neutral",
    trend: unitsTrend.direction,
    metrics: [
      {
        label: "Sản phẩm đang bán",
        metricKey: "product_count",
        value: formatNumber(productCount),
        realValue: productCount,
        estimatedValue: productEstimated,
        scaleMax: scaleHeadroom(productCount, productEstimated),
        estimatedGainLabel: `+${productEstimated - productCount} SKU if approved`,
      },
    ],
    isEmpty: false,
  });
}

function buildInventoryRefundsSummary(model: UnifiedOperationalDataModel): DomainReportSummary {
  const lowStockRate = computeLowStockRate(model);
  const refundRate = model.returns.refund_rate_7d;
  const pendingCount = model.returns.pending_return_authorizations.length;
  const refundTrend = computeTrend(refundRate, model.returns.baseline_refund_rate_30d);
  const isElevated = refundRate > model.returns.baseline_refund_rate_30d;

  const lowStockEstimated = Math.max(0, lowStockRate - 0.5 / Math.max(model.inventory.length, 1));
  const refundEstimated = Math.max(0, refundRate - 0.015);

  const statusTone: DomainStatusTone =
    lowStockRate > 0.3 || isElevated
      ? "warning"
      : lowStockRate === 0 && refundRate === 0
        ? "healthy"
        : "neutral";

  return buildSummary("inventory_refunds", {
    statusLabel:
      statusTone === "warning"
        ? "Cần theo dõi"
        : statusTone === "healthy"
          ? "Trong ngưỡng an toàn"
          : "Bình thường",
    statusTone,
    trend: refundTrend.direction,
    metrics: [
      {
        label: "Tỷ lệ tồn kho dưới ngưỡng giao hàng",
        metricKey: "low_stock_rate",
        value: formatRatePct(lowStockRate),
        realValue: lowStockRate,
        estimatedValue: lowStockEstimated,
        scaleMax: 1,
        estimatedGainLabel: "Giảm SKU at-risk if approved",
      },
      {
        label: "Tỷ lệ hoàn 7 ngày",
        metricKey: "refund_rate_7d",
        value: formatRatePct(refundRate),
        deltaLabel: formatDeltaPct(refundTrend.deltaPct),
        direction: refundTrend.direction,
        realValue: refundRate,
        estimatedValue: refundEstimated,
        scaleMax: Math.max(refundRate, refundEstimated, 0.1),
        estimatedGainLabel: `−${formatRatePct(refundRate - refundEstimated)} if approved`,
      },
      {
        label: "Hoàn tiền chờ xử lý",
        metricKey: "pending_return_count",
        value: formatNumber(pendingCount),
        realValue: pendingCount,
        estimatedValue: Math.max(0, pendingCount - 2),
        scaleMax: scaleHeadroom(pendingCount, Math.max(0, pendingCount - 2)),
        estimatedGainLabel: "Giảm yêu cầu chờ duyệt if approved",
      },
    ],
    isEmpty: model.inventory.length === 0 && refundRate === 0 && pendingCount === 0,
  });
}

const DOMAIN_BUILDERS: Record<
  ReportDomainId,
  (model: UnifiedOperationalDataModel) => DomainReportSummary
> = {
  revenue_growth: buildRevenueGrowthSummary,
  product_listings: buildProductListingsSummary,
  inventory_refunds: buildInventoryRefundsSummary,
};

/** Default landing domain per PRD-app-structure (NEW_SHOP → listings, else growth). */
export function resolveDefaultReportDomain(profile: ShopProfileType): ReportDomainId {
  return profile === "NEW_SHOP" ? "product_listings" : "revenue_growth";
}

export function buildDomainReportSummary(
  domainId: ReportDomainId,
  model: UnifiedOperationalDataModel,
): DomainReportSummary {
  return DOMAIN_BUILDERS[domainId](model);
}

export function buildAllDomainReportSummaries(
  model: UnifiedOperationalDataModel,
): DomainReportSummary[] {
  return REPORT_DOMAIN_IDS.map((domainId) => buildDomainReportSummary(domainId, model));
}

/** @deprecated Sparklines removed in #217 reopen — kept for test migration only. */
export const SPARKLINE_POINT_COUNT = 7;

/** @deprecated */
export function deriveSparklineSeries(
  current: number,
  prior: number,
  _seed: string,
  pointCount = SPARKLINE_POINT_COUNT,
): number[] {
  if (pointCount < 2) {
    return [current];
  }
  return Array.from({ length: pointCount }, (_, index) => {
    const progress = index / (pointCount - 1);
    return prior + (current - prior) * progress;
  });
}
