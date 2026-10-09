import { addToCartRate, aov, ctor, ctr, isChannelMissing } from "../shop-analysis/derive";
import type { ChannelRow, Counts, FactorKey, ShopDiagnosisReport } from "../shop-analysis/types";
import { change, money, num, pct, signedMoney } from "../vn-format";
import type { RankedMetric, RankedStream, RowKind } from "./types";

/**
 * Phân tích (AC-8.6, ADR-109 decisions 2–5) — the pure mapping behind the
 * screen: sub-tabs and streams, URL slugs (the query Home's matrix links
 * write, `lib/shop-report/home-metrics.ts` `analyticsCellHref`), which cells
 * are clickable (d.4), the bottleneck and the conclusion-style title. No I/O.
 */

export type TabSlug = "san-pham" | "noi-dung";

export interface StreamSpec {
  readonly stream: RankedStream;
  readonly slug: string;
  readonly tab: TabSlug;
  readonly label: string;
  readonly sub: string;
  readonly rowKind: RowKind;
}

/** The four streams as the sales demo video names them (Home uses the same). */
export const STREAM_SPECS: readonly StreamSpec[] = [
  { stream: "product_card", slug: "the-san-pham", tab: "san-pham", label: "Thẻ sản phẩm", sub: "Khách tự tìm đến sản phẩm", rowKind: "product" },
  { stream: "shop_tab", slug: "tab-cua-hang", tab: "san-pham", label: "Tab cửa hàng", sub: "Trang cửa hàng của shop", rowKind: "product" },
  { stream: "seller_video", slug: "video", tab: "noi-dung", label: "Video của shop", sub: "Video shop tự đăng", rowKind: "video" },
  { stream: "seller_live", slug: "live", tab: "noi-dung", label: "LIVE của shop", sub: "Phiên LIVE của shop", rowKind: "live_session" },
];

export const TABS: ReadonlyArray<{ readonly slug: TabSlug; readonly label: string; readonly eyebrow: string }> = [
  { slug: "san-pham", label: "Sản phẩm", eyebrow: "Phân tích · Sản phẩm" },
  { slug: "noi-dung", label: "Nội dung", eyebrow: "Phân tích · Nội dung" },
];

export const METRIC_SLUGS: Record<RankedMetric, string> = {
  impressions: "hien-thi",
  ctr: "ctr",
  ctor: "ctor",
  add_to_cart_rate: "them-gio",
  orders_per_cart: "don-them-gio",
  aov: "aov",
};

/** How each metric is named in titles ("SKU kéo CTOR xuống"). */
export const METRIC_NAMES: Record<RankedMetric, string> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "CTR",
  ctor: "CTOR",
  add_to_cart_rate: "Thêm giỏ/bấm",
  orders_per_cart: "Đơn/thêm giỏ",
  aov: "AOV",
};

/** ADR-109 d.4: the clickable cells of each stream (the backend's `STREAM_METRICS`). */
export const CLICKABLE: Record<RankedStream, readonly RankedMetric[]> = {
  product_card: ["impressions", "ctr", "ctor", "add_to_cart_rate", "orders_per_cart", "aov"],
  shop_tab: ["impressions", "ctr", "ctor", "aov"],
  seller_video: ["impressions", "ctr"],
  seller_live: ["impressions", "ctr", "ctor"],
};

/** What a shown-but-not-clickable content cell says (d.4). */
export const DEPENDS_ON_PRODUCT = "phụ thuộc sản phẩm → xem tab Sản phẩm";

export function isClickable(stream: RankedStream, metric: RankedMetric): boolean {
  return CLICKABLE[stream].includes(metric);
}

export function specOf(stream: RankedStream): StreamSpec {
  return STREAM_SPECS.find((s) => s.stream === stream) as StreamSpec;
}

export function streamsOf(tab: TabSlug): readonly StreamSpec[] {
  return STREAM_SPECS.filter((s) => s.tab === tab);
}

export const ordersPerCart = (c: Counts) =>
  c.sku_orders === null || c.add_to_cart === null || !c.add_to_cart ? null : c.sku_orders / c.add_to_cart;

export const METRIC_READ: Record<RankedMetric, (c: Counts) => number | null> = {
  impressions: (c) => c.impressions,
  ctr,
  ctor,
  add_to_cart_rate: addToCartRate,
  orders_per_cart: ordersPerCart,
  aov,
};

/** A metric's value as the screen prints it (impressions are per day). */
export function formatMetric(metric: RankedMetric, value: number | null | undefined): string {
  if (metric === "impressions") return num(value ?? null, 0);
  if (metric === "aov") return money(value ?? null);
  return pct(value ?? null);
}

export function channelRow(report: ShopDiagnosisReport, stream: RankedStream): ChannelRow | undefined {
  const row = report.channels.find((r) => r.channel === stream);
  return isChannelMissing(row) ? undefined : row;
}

export interface Cell {
  readonly stream: RankedStream;
  readonly metric: RankedMetric;
}

export interface Bottleneck extends Cell {
  /** ₫/day this factor carried (negative). */
  readonly contribution: number;
  readonly prior: number | null;
  readonly last: number | null;
}

/**
 * The bottleneck of a sub-tab: across its two streams, the clickable factor
 * with the largest negative GMV contribution whose confidence is "Rõ"
 * (ADR-108's log-share split in the report). `null` when no factor qualifies —
 * then nothing is outlined and no "Juli gợi ý" is shown.
 */
export function findBottleneck(report: ShopDiagnosisReport, tab: TabSlug): Bottleneck | null {
  let best: Bottleneck | null = null;
  for (const spec of streamsOf(tab)) {
    const row = channelRow(report, spec.stream);
    if (!row) continue;
    for (const factor of row.comparison.factors ?? []) {
      const metric = factor.factor as FactorKey & RankedMetric;
      if (factor.confidence !== "Rõ" || factor.contribution === null || factor.contribution >= 0) continue;
      if (!isClickable(spec.stream, metric)) continue;
      if (best === null || factor.contribution < best.contribution) {
        best = {
          stream: spec.stream,
          metric,
          contribution: factor.contribution,
          prior: METRIC_READ[metric](row.comparison.prior),
          last: METRIC_READ[metric](row.comparison.last),
        };
      }
    }
  }
  return best;
}

export interface QueryState {
  readonly tab?: string | null;
  readonly stream?: string | null;
  readonly metric?: string | null;
}

export interface Selection {
  readonly tab: TabSlug;
  /** `null` when the sub-tab has no stream with data. */
  readonly cell: Cell | null;
}

function metricFromSlug(slug: string | null | undefined): RankedMetric | null {
  const hit = (Object.keys(METRIC_SLUGS) as RankedMetric[]).find((m) => METRIC_SLUGS[m] === slug);
  return hit ?? null;
}

/**
 * The URL → what is shown. A valid `stream` wins over `tab` (Home links carry
 * both, and they agree); an invalid or non-clickable cell, or a stream without
 * data, falls back to the sub-tab's bottleneck, then to the first clickable
 * cell of its first stream with data.
 */
export function resolveSelection(report: ShopDiagnosisReport, query: QueryState): Selection {
  const spec = STREAM_SPECS.find((s) => s.slug === query.stream);
  const tab: TabSlug = spec ? spec.tab : query.tab === "noi-dung" ? "noi-dung" : "san-pham";
  const metric = metricFromSlug(query.metric);
  if (spec && metric && isClickable(spec.stream, metric) && channelRow(report, spec.stream)) {
    return { tab, cell: { stream: spec.stream, metric } };
  }
  const bottleneck = findBottleneck(report, tab);
  if (bottleneck) return { tab, cell: { stream: bottleneck.stream, metric: bottleneck.metric } };
  const first = streamsOf(tab).find((s) => channelRow(report, s.stream));
  return { tab, cell: first ? { stream: first.stream, metric: CLICKABLE[first.stream][0] } : null };
}

export function analysisHref(tab: TabSlug, cell?: Cell | null): string {
  const params = new URLSearchParams({ tab });
  if (cell) {
    params.set("stream", specOf(cell.stream).slug);
    params.set("metric", METRIC_SLUGS[cell.metric]);
  }
  return `/analytics?${params.toString()}`;
}

function unsignedChange(prior: number | null, last: number | null): string {
  return change(prior, last).text.replace(/^[+−]/, "");
}

/** The conclusion-style h1: "Thẻ sản phẩm: CTOR giảm 15,2 %". */
export function pageTitle(report: ShopDiagnosisReport, tab: TabSlug): string {
  const bottleneck = findBottleneck(report, tab);
  const tabLabel = TABS.find((t) => t.slug === tab)?.label ?? "";
  if (!bottleneck) return `${tabLabel}: không có chỉ số nào kéo GMV xuống rõ rệt`;
  const label = specOf(bottleneck.stream).label;
  const delta = change(bottleneck.prior, bottleneck.last);
  const verb = delta.tone === "up" ? "tăng" : delta.tone === "down" ? "giảm" : "đi ngang";
  const amount = delta.tone === "flat" ? "" : ` ${unsignedChange(bottleneck.prior, bottleneck.last)}`;
  return `${label}: ${METRIC_NAMES[bottleneck.metric]} ${verb}${amount}`;
}

/**
 * The "✦ Juli gợi ý" line — "Tối ưu <metric>: <one line>" — read only from
 * the report's numbers (which step of CTOR fell, the before → after values,
 * the GMV/day the factor carried). No target: the backend gives none.
 */
export function suggestionLine(report: ShopDiagnosisReport, bottleneck: Bottleneck): string {
  const { metric, stream } = bottleneck;
  const row = channelRow(report, stream);
  const gmv = `kéo GMV/ngày ${signedMoney(bottleneck.contribution)}`;
  const move = (m: RankedMetric, prior: number | null, last: number | null) =>
    `${METRIC_NAMES[m]} ${formatMetric(m, prior)} → ${formatMetric(m, last)}`;
  let reason: string;
  if (metric === "impressions") {
    reason = `sản phẩm được hiển thị ít hơn: ${move(metric, bottleneck.prior, bottleneck.last)}/ngày`;
  } else if (metric === "ctr") {
    reason = `khách thấy sản phẩm nhưng ít bấm hơn: ${move(metric, bottleneck.prior, bottleneck.last)}`;
  } else if (metric === "aov") {
    reason = `giá trị mỗi đơn SKU giảm: ${move(metric, bottleneck.prior, bottleneck.last)}`;
  } else {
    reason = move(metric, bottleneck.prior, bottleneck.last);
    if (row && metric === "ctor") {
      const p = row.comparison.prior;
      const q = row.comparison.last;
      const cart = change(addToCartRate(p), addToCartRate(q));
      const after = change(ordersPerCart(p), ordersPerCart(q));
      const cartRatio = (addToCartRate(q) ?? 0) / (addToCartRate(p) || 1);
      const afterRatio = (ordersPerCart(q) ?? 0) / (ordersPerCart(p) || 1);
      if (after.tone === "down" && afterRatio <= cartRatio) {
        reason = `khách thêm giỏ rồi bỏ: ${move("orders_per_cart", ordersPerCart(p), ordersPerCart(q))}`;
      } else if (cart.tone === "down") {
        reason = `khách bấm vào nhưng ít thêm giỏ: ${move("add_to_cart_rate", addToCartRate(p), addToCartRate(q))}`;
      }
    }
  }
  return `Tối ưu ${METRIC_NAMES[metric]}: ${reason} · ${gmv}`;
}
