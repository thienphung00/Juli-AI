import type {
  ShopProfileType,
  UnifiedOperationalDataModel,
} from "@/lib/mock-data/operations/schemas";
import { formatNumber, formatVND } from "@/lib/format";

export const REPORT_DOMAIN_IDS = [
  "revenue_growth",
  "revenue_protection",
  "product_listings",
  "advertising",
  "refunds",
] as const;

export type ReportDomainId = (typeof REPORT_DOMAIN_IDS)[number];

export type TrendDirection = "up" | "down" | "neutral";

export type DomainStatusTone = "healthy" | "warning" | "critical" | "neutral" | "empty";

export const SPARKLINE_POINT_COUNT = 7;

export interface MetricDelta {
  label: string;
  metricKey: string;
  value: string;
  deltaLabel?: string;
  direction?: TrendDirection;
  series: number[];
}

function hashSeed(seed: string): number {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return hash;
}

function seededUnitNoise(seed: string, index: number): number {
  const value = hashSeed(`${seed}:${index}`);
  return (value % 1000) / 1000;
}

/** Deterministic 7-point series for sparklines — derived from the same model inputs as metric values. */
export function deriveSparklineSeries(
  current: number,
  prior: number,
  seed: string,
  pointCount = SPARKLINE_POINT_COUNT,
): number[] {
  if (pointCount < 2) {
    return [current];
  }

  const amplitude = Math.abs(current - prior);
  const points = Array.from({ length: pointCount }, (_, index) => {
    const progress = index / (pointCount - 1);
    const base = prior + (current - prior) * progress;
    const wobble = (seededUnitNoise(seed, index) - 0.5) * amplitude * 0.08;
    return Math.max(0, base + wobble);
  });

  points[pointCount - 1] = current;
  return points;
}

function buildMetricSeries(
  model: UnifiedOperationalDataModel,
  domainId: ReportDomainId,
  metricKey: string,
  current: number,
  prior: number,
): number[] {
  const shopId = model.shop_metadata.shop_id;
  return deriveSparklineSeries(current, prior, `${shopId}:${domainId}:${metricKey}`);
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
  revenue_protection: { title: "Bảo vệ doanh thu", shortLabel: "Bảo vệ" },
  product_listings: { title: "Danh sách sản phẩm", shortLabel: "Sản phẩm" },
  advertising: { title: "Quảng cáo", shortLabel: "Quảng cáo" },
  refunds: { title: "Hoàn tiền", shortLabel: "Hoàn tiền" },
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

  const revenueTrend = computeTrend(revenue7d, revenuePrior);
  const unitsTrend = computeTrend(units7d, unitsPrior);

  const statusTone: DomainStatusTone =
    revenueTrend.direction === "down" ? "warning" : revenueTrend.direction === "up" ? "healthy" : "neutral";

  return buildSummary("revenue_growth", {
    statusLabel:
      statusTone === "healthy"
        ? "Đang tăng trưởng"
        : statusTone === "warning"
          ? "Cần theo dõi"
          : "Ổn định",
    statusTone,
    trend: revenueTrend.direction,
    metrics: [
      {
        label: "Doanh thu 7 ngày",
        metricKey: "revenue_7d",
        value: formatVND(revenue7d),
        deltaLabel: formatDeltaPct(revenueTrend.deltaPct),
        direction: revenueTrend.direction,
        series: buildMetricSeries(
          model,
          "revenue_growth",
          "revenue_7d",
          revenue7d,
          revenuePrior,
        ),
      },
      {
        label: "Đơn vị bán 7 ngày",
        metricKey: "units_sold_7d",
        value: formatNumber(units7d),
        deltaLabel: formatDeltaPct(unitsTrend.deltaPct),
        direction: unitsTrend.direction,
        series: buildMetricSeries(
          model,
          "revenue_growth",
          "units_sold_7d",
          units7d,
          unitsPrior,
        ),
      },
    ],
    isEmpty: model.products.length === 0,
  });
}

function buildRevenueProtectionSummary(model: UnifiedOperationalDataModel): DomainReportSummary {
  const violationCount =
    model.probation?.violations.reduce((sum, violation) => sum + violation.count, 0) ?? 0;
  const highSeverityCount =
    model.probation?.violations.filter((violation) => violation.severity === "high").length ?? 0;
  const pendingRefundVnd = model.returns.pending_return_authorizations.reduce(
    (sum, item) => sum + item.refund_vnd,
    0,
  );
  const refundRateTrend = computeTrend(
    model.returns.refund_rate_7d,
    model.returns.baseline_refund_rate_30d,
  );

  const isSpike = model.returns.refund_rate_7d > model.returns.baseline_refund_rate_30d * 1.5;
  const statusTone: DomainStatusTone =
    highSeverityCount > 0 || isSpike
      ? "critical"
      : violationCount > 0 || refundRateTrend.direction === "up"
        ? "warning"
        : "healthy";

  return buildSummary("revenue_protection", {
    statusLabel:
      statusTone === "critical"
        ? "Cần chú ý"
        : statusTone === "warning"
          ? "Cần theo dõi"
          : "Được bảo vệ tốt",
    statusTone,
    trend: refundRateTrend.direction === "up" && isSpike ? "down" : "neutral",
    metrics: [
      {
        label: "Vi phạm đang theo dõi",
        metricKey: "violation_count",
        value: formatNumber(violationCount),
        series: buildMetricSeries(
          model,
          "revenue_protection",
          "violation_count",
          violationCount,
          Math.max(violationCount - 1, 0),
        ),
      },
      {
        label: "Hoàn tiền chờ xử lý",
        metricKey: "pending_refund_vnd",
        value: formatVND(pendingRefundVnd),
        deltaLabel: formatRatePct(model.returns.refund_rate_7d),
        direction: isSpike ? "down" : "neutral",
        series: buildMetricSeries(
          model,
          "revenue_protection",
          "pending_refund_vnd",
          pendingRefundVnd,
          pendingRefundVnd * 0.9,
        ),
      },
    ],
    isEmpty: violationCount === 0 && pendingRefundVnd === 0 && model.returns.refund_count_7d === 0,
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
  const avgSellThrough =
    model.products.reduce((sum, product) => sum + product.sell_through_rate, 0) / productCount;
  const sellThroughTrend = computeTrend(avgSellThrough, avgSellThrough * 0.92);
  const unitsTrend = computeTrend(units7d, unitsPrior);

  const statusTone: DomainStatusTone =
    avgSellThrough < 0.25 ? "warning" : avgSellThrough >= 0.5 ? "healthy" : "neutral";

  return buildSummary("product_listings", {
    statusLabel:
      statusTone === "healthy"
        ? "Danh sách khỏe"
        : statusTone === "warning"
          ? "Cần tối ưu listing"
          : "Đang phát triển",
    statusTone,
    trend: unitsTrend.direction,
    metrics: [
      {
        label: "Sản phẩm đang bán",
        metricKey: "product_count",
        value: formatNumber(productCount),
        series: buildMetricSeries(
          model,
          "product_listings",
          "product_count",
          productCount,
          Math.max(productCount - 1, 0),
        ),
      },
      {
        label: "Tỷ lệ bán hết TB",
        metricKey: "sell_through_rate",
        value: formatRatePct(avgSellThrough),
        deltaLabel: formatDeltaPct(sellThroughTrend.deltaPct),
        direction: sellThroughTrend.direction,
        series: buildMetricSeries(
          model,
          "product_listings",
          "sell_through_rate",
          avgSellThrough,
          avgSellThrough * 0.92,
        ),
      },
    ],
    isEmpty: false,
  });
}

function buildAdvertisingSummary(model: UnifiedOperationalDataModel): DomainReportSummary {
  if (model.ad_campaigns.length === 0) {
    return buildSummary("advertising", {
      statusLabel: "Chưa có dữ liệu",
      statusTone: "empty",
      trend: "neutral",
      metrics: [],
      isEmpty: true,
    });
  }

  const activeCampaigns = model.ad_campaigns.filter((campaign) => campaign.status === "active");
  const totalSpend = model.ad_campaigns.reduce((sum, campaign) => sum + campaign.spend_vnd, 0);
  const totalRevenue = model.ad_campaigns.reduce((sum, campaign) => sum + campaign.revenue_vnd, 0);
  const blendedRoas = totalSpend > 0 ? totalRevenue / totalSpend : 0;
  const priorRoas =
    model.ad_campaigns.reduce((sum, campaign) => sum + campaign.roas, 0) /
    model.ad_campaigns.length;
  const roasTrend = computeTrend(blendedRoas, priorRoas * 0.95);

  const statusTone: DomainStatusTone =
    blendedRoas < 2 ? "warning" : blendedRoas >= 4 ? "healthy" : "neutral";

  return buildSummary("advertising", {
    statusLabel:
      statusTone === "healthy"
        ? "Hiệu quả tốt"
        : statusTone === "warning"
          ? "Cần tối ưu ngân sách"
          : "Đang chạy ổn định",
    statusTone,
    trend: roasTrend.direction,
    metrics: [
      {
        label: "Chi tiêu quảng cáo",
        metricKey: "ad_spend",
        value: formatVND(totalSpend),
        series: buildMetricSeries(model, "advertising", "ad_spend", totalSpend, totalSpend * 0.88),
      },
      {
        label: "ROAS trung bình",
        metricKey: "roas",
        value: `${blendedRoas.toFixed(2)}x`,
        deltaLabel: formatDeltaPct(roasTrend.deltaPct),
        direction: roasTrend.direction,
        series: buildMetricSeries(model, "advertising", "roas", blendedRoas, priorRoas * 0.95),
      },
      {
        label: "Chiến dịch đang chạy",
        metricKey: "active_campaign_count",
        value: formatNumber(activeCampaigns.length),
        series: buildMetricSeries(
          model,
          "advertising",
          "active_campaign_count",
          activeCampaigns.length,
          Math.max(activeCampaigns.length - 1, 0),
        ),
      },
    ],
    isEmpty: false,
  });
}

function buildRefundsSummary(model: UnifiedOperationalDataModel): DomainReportSummary {
  const refundTrend = computeTrend(
    model.returns.refund_rate_7d,
    model.returns.baseline_refund_rate_30d,
  );
  const pendingCount = model.returns.pending_return_authorizations.length;
  const isElevated = model.returns.refund_rate_7d > model.returns.baseline_refund_rate_30d;

  const statusTone: DomainStatusTone = isElevated
    ? "warning"
    : model.returns.refund_count_7d === 0
      ? "healthy"
      : "neutral";

  return buildSummary("refunds", {
    statusLabel:
      statusTone === "warning"
        ? "Tỷ lệ hoàn cao"
        : statusTone === "healthy"
          ? "Trong ngưỡng an toàn"
          : "Bình thường",
    statusTone,
    trend: refundTrend.direction,
    metrics: [
      {
        label: "Tỷ lệ hoàn 7 ngày",
        metricKey: "refund_rate_7d",
        value: formatRatePct(model.returns.refund_rate_7d),
        deltaLabel: formatDeltaPct(refundTrend.deltaPct),
        direction: refundTrend.direction,
        series: buildMetricSeries(
          model,
          "refunds",
          "refund_rate_7d",
          model.returns.refund_rate_7d,
          model.returns.baseline_refund_rate_30d,
        ),
      },
      {
        label: "Đơn hoàn 7 ngày",
        metricKey: "refund_count_7d",
        value: formatNumber(model.returns.refund_count_7d),
        series: buildMetricSeries(
          model,
          "refunds",
          "refund_count_7d",
          model.returns.refund_count_7d,
          Math.max(model.returns.refund_count_7d - 2, 0),
        ),
      },
      {
        label: "Yêu cầu chờ duyệt",
        metricKey: "pending_return_count",
        value: formatNumber(pendingCount),
        series: buildMetricSeries(
          model,
          "refunds",
          "pending_return_count",
          pendingCount,
          Math.max(pendingCount - 1, 0),
        ),
      },
    ],
    isEmpty:
      model.returns.refund_count_7d === 0 &&
      pendingCount === 0 &&
      model.returns.refund_rate_7d === 0,
  });
}

const DOMAIN_BUILDERS: Record<
  ReportDomainId,
  (model: UnifiedOperationalDataModel) => DomainReportSummary
> = {
  revenue_growth: buildRevenueGrowthSummary,
  revenue_protection: buildRevenueProtectionSummary,
  product_listings: buildProductListingsSummary,
  advertising: buildAdvertisingSummary,
  refunds: buildRefundsSummary,
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
