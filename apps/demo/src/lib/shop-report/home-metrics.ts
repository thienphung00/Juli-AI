import { aov, ctor, ctr, isChannelMissing } from "../shop-analysis/derive";
import type {
  ChannelKey,
  ChannelRow,
  Counts,
  ShopAnalysisEnvelope,
  ShopDiagnosisReport,
} from "../shop-analysis/types";
import { change, type ChangeTone } from "../vn-format";

/**
 * Home (Trang chủ, ADR-109 decision 3): the GMV / Đơn / AOV cards and the
 * 5-stream matrix, read from the ADR-108 report the shop's Phân tích also
 * renders. Pure — no formatting beyond the change chip, no I/O — so Home,
 * the sample and the tests share one mapping.
 *
 * Every count in the report is a DAILY AVERAGE over its 30-day window
 * (`types.ts`); the 30-day totals on the cards are daily average × the
 * window's length in days. Rates are recomputed from counts (`derive.ts`).
 */

export type MetricKey = "impressions" | "ctr" | "ctor" | "aov";
export type StreamGroup = "product" | "content" | "affiliate";

export interface HomeMetricCell {
  readonly metric: MetricKey;
  readonly prior: number | null;
  readonly last: number | null;
  readonly changeText: string;
  readonly tone: ChangeTone;
  /** CTOR/AOV of Tab Cửa hàng: TikTok gives no SKU orders, they are CTOR × clicks. */
  readonly estimated: boolean;
  /** Where the cell opens in Phân tích; `null` for Liên kết (monitor only). */
  readonly href: string | null;
}

export interface HomeStreamRow {
  readonly channel: ChannelKey;
  readonly label: string;
  readonly sub: string;
  readonly group: StreamGroup;
  /** No numbers for this stream in the report — rendered "Chưa có dữ liệu". */
  readonly missing: boolean;
  readonly monitorOnly: boolean;
  readonly cells: readonly HomeMetricCell[];
}

export interface HomeTotalCard {
  readonly key: "gmv" | "orders" | "aov";
  readonly label: string;
  readonly prior: number | null;
  readonly last: number | null;
  readonly kind: "money" | "count";
  readonly changeText: string;
  readonly tone: ChangeTone;
}

export interface HomeOverviewModel {
  readonly shopName: string;
  readonly windowDays: number;
  readonly lastWindowEnd: string;
  readonly cards: readonly HomeTotalCard[];
  readonly groups: ReadonlyArray<{
    readonly group: StreamGroup;
    readonly label: string;
    readonly rows: readonly HomeStreamRow[];
  }>;
}

export const METRIC_COLUMNS: ReadonlyArray<{ readonly metric: MetricKey; readonly label: string }> = [
  { metric: "impressions", label: "Lượt hiển thị sản phẩm/ngày" },
  { metric: "ctr", label: "CTR" },
  { metric: "ctor", label: "CTOR" },
  { metric: "aov", label: "AOV" },
];

export const GROUP_LABELS: Record<StreamGroup, string> = {
  product: "Tăng trưởng từ sản phẩm",
  content: "Tăng trưởng từ nội dung",
  affiliate: "Tiếp thị liên kết · chỉ theo dõi, Juli không tác động",
};

/** The five streams as the sales demo video names them, in Home's row order. */
const STREAMS: ReadonlyArray<{
  channel: ChannelKey;
  label: string;
  sub: string;
  group: StreamGroup;
  /** Phân tích sub-tab + stream slug (ADR-109 d.2); `null` = not in Phân tích. */
  tab: "san-pham" | "noi-dung" | null;
  stream: string | null;
}> = [
  { channel: "product_card", label: "Thẻ sản phẩm", sub: "Khách tự tìm đến sản phẩm", group: "product", tab: "san-pham", stream: "the-san-pham" },
  { channel: "shop_tab", label: "Tab cửa hàng", sub: "Trang cửa hàng của shop", group: "product", tab: "san-pham", stream: "tab-cua-hang" },
  { channel: "seller_video", label: "Video của shop", sub: "Video shop tự đăng", group: "content", tab: "noi-dung", stream: "video" },
  { channel: "seller_live", label: "LIVE của shop", sub: "Phiên LIVE của shop", group: "content", tab: "noi-dung", stream: "live" },
  { channel: "affiliate", label: "Liên kết", sub: "Video và LIVE của nhà sáng tạo", group: "affiliate", tab: null, stream: null },
];

const METRIC_SLUGS: Record<MetricKey, string> = {
  impressions: "hien-thi",
  ctr: "ctr",
  ctor: "ctor",
  aov: "aov",
};

const READ: Record<MetricKey, (c: Counts) => number | null> = {
  impressions: (c) => c.impressions,
  ctr,
  ctor,
  aov,
};

/**
 * The Phân tích deep link for one matrix cell. The sub-tabs themselves are
 * P8-E's; this only fixes the query shape they read.
 */
export function analyticsCellHref(tab: string, stream: string, metric: MetricKey): string {
  const params = new URLSearchParams({ tab, stream, metric: METRIC_SLUGS[metric] });
  return `/analytics?${params.toString()}`;
}

/** Days in an inclusive ISO date range; 30 when the dates do not parse. */
export function windowLengthDays(first: string, last: string): number {
  const a = Date.parse(`${first}T00:00:00Z`);
  const b = Date.parse(`${last}T00:00:00Z`);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return 30;
  return Math.round((b - a) / 86_400_000) + 1;
}

function streamRow(report: ShopDiagnosisReport, spec: (typeof STREAMS)[number]): HomeStreamRow {
  const row: ChannelRow | undefined = report.channels.find((r) => r.channel === spec.channel);
  const missing = isChannelMissing(row);
  const monitorOnly = spec.group === "affiliate";
  const cells = METRIC_COLUMNS.map(({ metric }): HomeMetricCell => {
    const prior = row && !missing ? READ[metric](row.comparison.prior) : null;
    const last = row && !missing ? READ[metric](row.comparison.last) : null;
    const delta = change(prior, last);
    const estimated =
      (metric === "ctor" || metric === "aov") && Boolean(row?.comparison.last.orders_estimated);
    return {
      metric,
      prior,
      last,
      changeText: delta.text,
      tone: delta.tone,
      estimated,
      href:
        spec.tab && spec.stream && !missing ? analyticsCellHref(spec.tab, spec.stream, metric) : null,
    };
  });
  return {
    channel: spec.channel,
    label: spec.label,
    sub: spec.sub,
    group: spec.group,
    missing,
    monitorOnly,
    cells,
  };
}

export function buildHomeOverview(envelope: ShopAnalysisEnvelope): HomeOverviewModel {
  const { report } = envelope;
  const days = windowLengthDays(report.windows.last_first, report.windows.last_last);
  const priorDays = windowLengthDays(report.windows.prior_first, report.windows.prior_last);
  const { total } = report;

  const gmvPrior = total.prior.gmv * priorDays;
  const gmvLast = total.last.gmv * days;
  // Whole orders when the report has them; otherwise SKU orders × days.
  const ordersPrior =
    total.orders_prior ?? (total.prior.sku_orders === null ? null : total.prior.sku_orders * priorDays);
  const ordersLast =
    total.orders_last ?? (total.last.sku_orders === null ? null : total.last.sku_orders * days);
  const aovPrior = aov(total.prior);
  const aovLast = aov(total.last);

  const card = (
    key: HomeTotalCard["key"],
    label: string,
    kind: HomeTotalCard["kind"],
    prior: number | null,
    last: number | null,
  ): HomeTotalCard => {
    const delta = change(prior, last);
    return { key, label, kind, prior, last, changeText: delta.text, tone: delta.tone };
  };

  const rows = STREAMS.map((spec) => streamRow(report, spec));
  const groups = (["product", "content", "affiliate"] as const).map((group) => ({
    group,
    label: GROUP_LABELS[group],
    rows: rows.filter((r) => r.group === group),
  }));

  return {
    shopName: report.shop_name,
    windowDays: days,
    lastWindowEnd: report.windows.last_last,
    cards: [
      card("gmv", `GMV ${days} ngày`, "money", gmvPrior, gmvLast),
      card("orders", `Đơn ${days} ngày`, "count", ordersPrior, ordersLast),
      card("aov", "AOV", "money", aovPrior, aovLast),
    ],
    groups,
  };
}
