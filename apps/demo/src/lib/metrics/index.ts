import { fmt } from "../shopee-analytics/format";
import { METRIC_DEFS, type MetricId } from "./registry.generated";


/**
 * P100 shared metric vocabulary for Tổng quan, Phân tích and Quyết định (Shopee seller, Ops, reviewer
 * sample shop; TikTok Shop later). Platform-agnostic: screens take these keys from their host's data.
 */
export type MetricKey = "views" | "ctr" | "ctor" | "aov" | "orders" | "gmv" | "margin";

export const METRIC_ORDER: readonly MetricKey[] = ["views", "ctr", "ctor", "aov", "orders", "gmv", "margin"];

export const METRIC_NAME: Readonly<Record<MetricKey, string>> = {
  views: "Lượt xem",
  ctr: "CTR",
  ctor: "CTOR",
  aov: "AOV",
  orders: "Đơn hàng",
  gmv: "GMV",
  margin: "Biên lợi nhuận",
};

/** Ratios read the same per period and per day; the others are summed and divide by days. */
export const IS_RATE: Readonly<Record<MetricKey, boolean>> = {
  views: false,
  ctr: true,
  ctor: true,
  aov: true,
  orders: false,
  gmv: false,
  margin: true,
};

/** Period presets (no "Tháng này": a calendar month is a Tùy chọn range). */
export type PeriodPreset = "7" | "30" | "90" | "custom" | "plan";
export const PERIOD_LABEL: Readonly<Record<PeriodPreset, string>> = { "7": "7 ngày", "30": "30 ngày", "90": "90 ngày", custom: "Tùy chọn", plan: "Cả kế hoạch" };

/** Tổng | Trung bình / ngày. */
export type ValueMode = "total" | "avg";

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/** A summed value shown in the chosen mode (`days` = days in the period). */
export function inMode(total: number | null | undefined, days: number, mode: ValueMode): number | null {
  if (!num(total)) return null;
  return mode === "avg" && days > 0 ? total / days : total;
}

export type ShiftTone = "up" | "down" | "flat";

/** Change vs the previous period of the same length, as "▲ 12 %" / "▼ 3,4 %". `good` = 1 when up is good. */
export function shift(pct: number | null | undefined, good: 1 | -1 = 1): { readonly text: string; readonly tone: ShiftTone } | null {
  if (!num(pct)) return null;
  if (Math.abs(pct) < 0.0005) return { text: "0 %", tone: "flat" };
  const up = pct > 0;
  const text = `${up ? "▲" : "▼"} ${fmt(Math.abs(pct) * 100, Math.abs(pct) < 0.1 ? 1 : 0)} %`;
  return { text, tone: (up ? 1 : -1) * good > 0 ? "up" : "down" };
}

/** ROI in points: 5.4 -> "5,4" (never a percent). */
export function roiText(roi: number | null | undefined): string {
  return num(roi) ? fmt(roundHalfAway(roi * 10) / 10, 1) : "—";
}

/** The registry's Vietnamese name of a metric id (the one place screens take a label from). */
export const metricLabel = (id: MetricId): string => METRIC_DEFS[id].label_vi;

/**
 * Half away from zero (2.5 -> 3, -2.5 -> -3), like the server's `round_count`; JS `Math.round(-1.5)` is -1.
 * The one rounding of every figure a screen shows and every Δ it derives from shown figures.
 */
export const roundHalfAway = (n: number): number => (n < 0 ? -Math.round(-n) : Math.round(n));
