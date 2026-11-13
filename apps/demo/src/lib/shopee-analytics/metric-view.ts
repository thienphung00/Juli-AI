import { IS_RATE, METRIC_ORDER, inMode, type MetricKey, type ValueMode } from "../metrics";
import { DASH, fmt, pc, vnd } from "./format";
import type { MetricViewRow } from "./types";

/** URL state of Phân tích: `metric`, `channel`, `product`, and `cach=tb` for Trung bình / ngày. */

export const CHANNEL_LABEL: Readonly<Record<string, string>> = {
  the_san_pham: "Thẻ sản phẩm",
  trang_shop: "Trang shop",
  video: "Video",
  live: "Live",
  ads_product: "DVHT Sản phẩm",
  ads_shop: "DVHT Shop+",
  lien_ket: "Tiếp thị liên kết",
};

/** Old `kpi=` values of Phân tích links → the metric they open. */
const METRIC_OF_KPI: Readonly<Record<string, MetricKey>> = {
  gmv: "gmv",
  views: "views",
  ctr: "ctr",
  ctor: "ctor",
  aov: "aov",
  orders: "orders",
  bien: "margin",
  margin: "margin",
  disc: "margin",
};

/** Old `src=` values → the luồng they open. */
const CHANNEL_OF_SRC: Readonly<Record<string, string>> = {
  the_san_pham: "the_san_pham",
  trang_shop: "trang_shop",
  video: "video",
  live: "live",
  lien_ket: "lien_ket",
  ads: "ads_product",
};

export interface MetricParams {
  readonly metric: MetricKey;
  readonly channel: string | null;
  readonly product: string | null;
  readonly mode: ValueMode;
}

export function readMetricParams(params: URLSearchParams): MetricParams {
  const raw = params.get("metric") ?? METRIC_OF_KPI[params.get("kpi") ?? ""] ?? "gmv";
  const metric = (METRIC_ORDER as readonly string[]).includes(raw) ? (raw as MetricKey) : "gmv";
  const ch = params.get("channel") ?? CHANNEL_OF_SRC[params.get("src") ?? ""] ?? null;
  const channel = ch && CHANNEL_LABEL[ch] ? ch : null;
  const product = params.get("product") ?? params.get("focus") ?? null;
  return { metric, channel, product, mode: params.get("cach") === "tb" ? "avg" : "total" };
}

/** A sum shown in "x,xx tr" from a million, else in đ. */
export function money(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return DASH;
  if (Math.abs(n) >= 1_000_000) return `${fmt(n / 1_000_000, 2)} tr`;
  return vnd(n);
}

/** "−1,20 tr" with an explicit sign. */
export function signedMoney(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return DASH;
  const r = Math.round(n);
  if (r === 0) return "0đ";
  const body = money(Math.abs(r));
  return `${r < 0 ? "−" : "+"}${body}`;
}

/** The text of one metric value; sums follow Tổng | Trung bình / ngày through `inMode`. */
export function valueText(metric: MetricKey, v: number | null | undefined, days: number, mode: ValueMode): string {
  if (typeof v !== "number") return DASH;
  switch (metric) {
    case "ctr":
    case "ctor":
    case "margin":
      return pc(v, metric === "margin" ? 1 : 2);
    case "aov":
      return vnd(v);
    case "gmv":
      return money(inMode(v, days, mode));
    default: {
      const x = inMode(v, days, mode);
      return fmt(x, mode === "avg" && (x ?? 0) < 100 ? 1 : 0);
    }
  }
}

/** Impact is a ₫ total in Tổng and a per-day figure in Trung bình / ngày. */
export function impactText(row: MetricViewRow, days: number, mode: ValueMode): string {
  return signedMoney(inMode(row.impact, days, mode));
}

export type SortKey = "impact" | "change";

/** Rows ordered by the GMV gap (biggest loss first) or by the change (steepest fall first); unknown last. */
export function sortRows<T extends MetricViewRow>(rows: readonly T[], by: SortKey): T[] {
  const key = (r: T): number | null => (by === "impact" ? r.impact : r.change);
  return [...rows].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1;
    if (y === null) return -1;
    return x - y;
  });
}

export { IS_RATE };
