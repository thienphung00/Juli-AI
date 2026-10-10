import { aov, ctor, ctr, isChannelMissing } from "../shop-analysis/derive";
import type { ChannelRow, Counts, FactorChange, ShopDiagnosisReport } from "../shop-analysis/types";
import { num } from "../vn-format";
import { deltaChip, kMoney, perDay, roundedPercent, type DeltaChip } from "./format";
import type { RankedMetric, RankedStream, RowKind } from "./types";

/**
 * Phân tích (ADR-109 Amendment 2, `docs/product/design/phan-tich/`) — the pure
 * mapping from the ADR-108 report to the screen: sub-tabs and streams, the
 * four metric cells and their ₫/day impact (the report's log-share
 * `factors[].contribution`, decision 5's figure), the weakest metric, the
 * conclusion h1, and the URL state. No I/O.
 */

export type TabSlug = "san-pham" | "noi-dung";

/** The four cell metrics (Amendment 2 d.2: Bấm/ngày and Đơn/ngày are dropped). */
export type CellMetric = "impressions" | "ctr" | "ctor" | "aov";
export const CELL_METRICS: readonly CellMetric[] = ["impressions", "ctr", "ctor", "aov"];

export interface StreamSpec {
  readonly stream: RankedStream;
  readonly slug: string;
  readonly tab: TabSlug;
  /** The stream card's name (PtProduct / PtContent). */
  readonly label: string;
  /** The h1's short name ("Video: CTR giảm 9 %"). */
  readonly short: string;
  readonly rowKind: RowKind;
  /** Clickable cells (ADR-109 d.4); the others are grey "Phụ thuộc sản phẩm". */
  readonly clickable: readonly CellMetric[];
}

export const STREAM_SPECS: readonly StreamSpec[] = [
  { stream: "product_card", slug: "the-san-pham", tab: "san-pham", label: "Thẻ sản phẩm", short: "Thẻ sản phẩm", rowKind: "product", clickable: CELL_METRICS },
  { stream: "shop_tab", slug: "tab-cua-hang", tab: "san-pham", label: "Tab cửa hàng", short: "Tab cửa hàng", rowKind: "product", clickable: CELL_METRICS },
  { stream: "seller_video", slug: "video", tab: "noi-dung", label: "Video của người bán", short: "Video", rowKind: "video", clickable: ["impressions", "ctr"] },
  { stream: "seller_live", slug: "live", tab: "noi-dung", label: "LIVE của người bán", short: "LIVE", rowKind: "live_session", clickable: ["impressions", "ctr", "ctor"] },
];

export const TABS: ReadonlyArray<{ readonly slug: TabSlug; readonly label: string }> = [
  { slug: "san-pham", label: "Sản phẩm" },
  { slug: "noi-dung", label: "Nội dung" },
];

export const METRIC_SLUGS: Record<RankedMetric, string> = {
  impressions: "hien-thi",
  ctr: "ctr",
  ctor: "ctor",
  add_to_cart_rate: "them-gio",
  orders_per_cart: "don-them-gio",
  aov: "aov",
};

/** Cell labels (PtProduct `label`). */
export const CELL_LABELS: Record<CellMetric, string> = {
  impressions: "Hiển thị/ngày",
  ctr: "CTR",
  ctor: "CTOR",
  aov: "AOV",
};

/** The table / caption name of a metric (PtProduct `col`). */
export const METRIC_COLS: Record<CellMetric, string> = {
  impressions: "Hiển thị",
  ctr: "CTR",
  ctor: "CTOR",
  aov: "AOV",
};

export const DEPENDS_ON_PRODUCT = "Phụ thuộc sản phẩm";

export function specOf(stream: RankedStream): StreamSpec {
  return STREAM_SPECS.find((s) => s.stream === stream) as StreamSpec;
}

export function streamsOf(tab: TabSlug): readonly StreamSpec[] {
  return STREAM_SPECS.filter((s) => s.tab === tab);
}

export function isClickable(stream: RankedStream, metric: CellMetric): boolean {
  return specOf(stream).clickable.includes(metric);
}

export const METRIC_READ: Record<CellMetric, (c: Counts) => number | null> = {
  impressions: (c) => c.impressions,
  ctr,
  ctor,
  aov,
};

export function channelRow(report: ShopDiagnosisReport, stream: RankedStream): ChannelRow | undefined {
  const row = report.channels.find((r) => r.channel === stream);
  return isChannelMissing(row) ? undefined : row;
}

function factorOf(row: ChannelRow | undefined, metric: CellMetric): FactorChange | undefined {
  return row?.comparison.factors?.find((f) => f.factor === metric);
}

// -- cells ---------------------------------------------------------------------------

export interface CellView {
  readonly metric: CellMetric | "gmv";
  readonly label: string;
  readonly value: string;
  /** "trước 6,06 %" — shown on hover / tap (Amendment 2 d.2). */
  readonly before: string;
  readonly delta: DeltaChip;
  /** "−250k ₫/ngày", "Phụ thuộc sản phẩm", "Tổng của 4 ô". */
  readonly impact: string;
  readonly impactTone: "up" | "down" | "muted";
  readonly clickable: boolean;
  /** Greyed, dashed (content streams' CTOR / AOV, and their GMV cell). */
  readonly grey: boolean;
  /** Carries "✦ Juli gợi ý". */
  readonly weak: boolean;
}

export interface StreamView {
  readonly spec: StreamSpec;
  /** `false` when the report has no data for the stream. */
  readonly present: boolean;
  /** "3,6 tr ₫/ngày". */
  readonly gmvText: string;
  /** "3,6 tr ₫" (mobile header). */
  readonly gmvShort: string;
  readonly delta: DeltaChip;
  /** The clickable metric whose change cost the most GMV, `null` when none did. */
  readonly weakMetric: CellMetric | null;
  readonly weakContribution: number | null;
  /** "Yếu nhất: CTOR −250k ₫/ngày". */
  readonly weakText: string | null;
  readonly cells: readonly CellView[];
}

function formatCellValue(metric: CellMetric, value: number | null): string {
  if (value === null) return "—";
  if (metric === "impressions") return num(value, 0);
  if (metric === "aov") return kMoney(value);
  return `${(value * 100).toFixed(2).replace(".", ",")} %`;
}

export function streamView(report: ShopDiagnosisReport, stream: RankedStream): StreamView {
  const spec = specOf(stream);
  const row = channelRow(report, stream);
  const prior = row?.comparison.prior;
  const last = row?.comparison.last;

  let weakMetric: CellMetric | null = null;
  let weakContribution: number | null = null;
  for (const metric of spec.clickable) {
    const contribution = factorOf(row, metric)?.contribution;
    if (typeof contribution !== "number" || contribution >= 0) continue;
    if (weakContribution === null || contribution < weakContribution) {
      weakMetric = metric;
      weakContribution = contribution;
    }
  }

  const cells: CellView[] = CELL_METRICS.map((metric) => {
    const clickable = spec.clickable.includes(metric);
    const contribution = factorOf(row, metric)?.contribution ?? null;
    const p = prior ? METRIC_READ[metric](prior) : null;
    const q = last ? METRIC_READ[metric](last) : null;
    return {
      metric,
      label: CELL_LABELS[metric],
      value: formatCellValue(metric, q),
      before: `trước ${formatCellValue(metric, p)}`,
      delta: deltaChip(p, q),
      impact: clickable ? perDay(contribution) : DEPENDS_ON_PRODUCT,
      impactTone: !clickable || contribution === null ? "muted" : contribution >= 0 ? "up" : "down",
      clickable: clickable && Boolean(row),
      grey: !clickable,
      weak: metric === weakMetric,
    };
  });
  const gmvDelta = deltaChip(prior?.gmv, last?.gmv);
  cells.push({
    metric: "gmv",
    label: "GMV/ngày",
    value: kMoney(last?.gmv ?? null),
    before: `trước ${kMoney(prior?.gmv ?? null)}`,
    delta: gmvDelta,
    impact: spec.tab === "san-pham" ? "Tổng của 4 ô" : "Tổng các ô",
    impactTone: "muted",
    clickable: false,
    grey: spec.tab === "noi-dung",
    weak: false,
  });

  return {
    spec,
    present: Boolean(row),
    gmvText: last ? `${kMoney(last.gmv)}/ngày` : "—",
    gmvShort: last ? kMoney(last.gmv) : "—",
    delta: gmvDelta,
    weakMetric,
    weakContribution,
    weakText: weakMetric ? `Yếu nhất: ${METRIC_COLS[weakMetric]} ${perDay(weakContribution)}` : null,
    cells,
  };
}

/**
 * The stream that opens by default on a sub-tab: the one whose weakest metric
 * costs the most GMV (Amendment 2 d.1, "the stream that loses the most GMV");
 * with no losing metric, the first stream with data.
 */
export function defaultStream(views: readonly StreamView[]): RankedStream | null {
  let best: StreamView | null = null;
  for (const view of views) {
    if (view.weakContribution === null) continue;
    if (!best || view.weakContribution < (best.weakContribution ?? 0)) best = view;
  }
  return (best ?? views.find((v) => v.present) ?? null)?.spec.stream ?? null;
}

/** A stream's selected cell by default: its weakest metric, else its first clickable one. */
export function defaultMetric(view: StreamView): CellMetric {
  return view.weakMetric ?? view.spec.clickable[0];
}

/** "Thẻ sản phẩm: CTOR giảm 15 %" — the default stream's weakest metric. */
export function pageTitle(report: ShopDiagnosisReport, tab: TabSlug): string {
  const views = streamsOf(tab).map((s) => streamView(report, s.stream));
  const stream = defaultStream(views);
  const view = views.find((v) => v.spec.stream === stream);
  const tabLabel = TABS.find((t) => t.slug === tab)?.label ?? "";
  if (!view || !view.weakMetric) return `${tabLabel}: không có chỉ số nào kéo GMV xuống`;
  const row = channelRow(report, view.spec.stream);
  const read = METRIC_READ[view.weakMetric];
  const prior = row ? read(row.comparison.prior) : null;
  const last = row ? read(row.comparison.last) : null;
  const amount = roundedPercent(prior, last);
  const verb = prior !== null && last !== null && last > prior ? "tăng" : "giảm";
  return `${view.spec.short}: ${METRIC_COLS[view.weakMetric]} ${verb}${amount ? ` ${amount} %` : ""}`;
}

// -- URL state ---------------------------------------------------------------------------

export type Direction = "down" | "up";

export interface QueryState {
  readonly tab?: string | null;
  readonly stream?: string | null;
  readonly metric?: string | null;
  /** `len` = Kéo lên. */
  readonly huong?: string | null;
  /** The expanded row's id (product / video / LIVE session). */
  readonly row?: string | null;
}

export interface Selection {
  readonly tab: TabSlug;
  /** The open stream; `null` when every stream is collapsed. */
  readonly stream: RankedStream | null;
  readonly metric: CellMetric | null;
  readonly direction: Direction;
  readonly row: string | null;
}

/** Old links (Home's matrix, P8) may still carry the two CTOR steps: they open CTOR. */
function metricFromSlug(slug: string | null | undefined): CellMetric | null {
  if (slug === METRIC_SLUGS.add_to_cart_rate || slug === METRIC_SLUGS.orders_per_cart) return "ctor";
  return CELL_METRICS.find((m) => METRIC_SLUGS[m] === slug) ?? null;
}

/**
 * The URL → what is shown. A valid `stream` wins over `tab`; `stream=dong`
 * means every stream collapsed. Without a stream the sub-tab's default
 * stream opens; without a valid clickable metric that stream's weakest.
 */
export function resolveSelection(report: ShopDiagnosisReport, query: QueryState): Selection {
  const spec = STREAM_SPECS.find((s) => s.slug === query.stream);
  const tab: TabSlug = spec ? spec.tab : query.tab === "noi-dung" ? "noi-dung" : "san-pham";
  const direction: Direction = query.huong === "len" ? "up" : "down";
  const row = query.row || null;
  if (query.stream === "dong") return { tab, stream: null, metric: null, direction, row: null };
  const views = streamsOf(tab).map((s) => streamView(report, s.stream));
  const stream = spec && channelRow(report, spec.stream) ? spec.stream : defaultStream(views);
  if (!stream) return { tab, stream: null, metric: null, direction, row: null };
  const view = views.find((v) => v.spec.stream === stream) as StreamView;
  const wanted = metricFromSlug(query.metric);
  const metric = wanted && isClickable(stream, wanted) ? wanted : defaultMetric(view);
  return { tab, stream, metric, direction, row };
}

export function analysisHref(selection: Partial<Selection> & { readonly tab: TabSlug }): string {
  const params = new URLSearchParams({ tab: selection.tab });
  if (selection.stream === null) params.set("stream", "dong");
  else if (selection.stream) params.set("stream", specOf(selection.stream).slug);
  if (selection.stream && selection.metric) params.set("metric", METRIC_SLUGS[selection.metric]);
  if (selection.direction === "up") params.set("huong", "len");
  if (selection.row) params.set("row", selection.row);
  return `/analytics?${params.toString()}`;
}
