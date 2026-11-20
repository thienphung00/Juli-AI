// U1 (owner 2026-11-17): what a card or an option shows depends on its kind. One kind -> strategy map and
// one set of small rules, used by Tự tạo step 4, the result card and the card's versions table, so the
// three screens never disagree. Pure: no components.

import { vnd } from "../shopee-analytics/format";
import type { OptionResult } from "./option-result";

/** F5 (owner 2026-11-17, option b): a metric inside the normal swing keeps its P50 amount, followed by this tag; never "—". */
export const NOISE_TAG = "· trong dao động";

export type Strategy = "listing" | "offer" | "ads" | "affiliate";

const LISTING = new Set(["title", "keyword", "cover_image", "cover", "main_image", "price_display", "description_first_line", "description", "variation_restructure"]);

/** Listing kinds change a field and cost nothing; ads and affiliate have their own rows; the rest are offers. */
export function strategyOf(kind: string | null | undefined, family?: string | null, hasAds = false): Strategy {
  const k = kind ?? "";
  if (hasAds || k.startsWith("ads")) return "ads";
  if (k.startsWith("affiliate")) return "affiliate";
  if (LISTING.has(k)) return "listing";
  if (k === "" && family === "listing") return "listing";
  if (k === "" && family === "ads") return "ads";
  if (k === "" && family === "affiliate") return "affiliate";
  return "offer";
}

export const strategyOfResult = (r: Pick<OptionResult, "kind" | "ads">): Strategy => strategyOf(r.kind, null, Boolean(r.ads));

export type Metric = "gmv" | "profit" | "cost" | "orders" | "aov" | "margin" | "breakeven" | "ads_orders" | "cpa" | "roas" | "roi" | "views" | "ctr";

/** Master order of the step-4 columns. */
const ORDER: readonly Metric[] = ["views", "ctr", "gmv", "profit", "cost", "orders", "aov", "margin", "breakeven", "ads_orders", "cpa", "roas", "roi"];

const NO_COST = 0.5;

/** Does this result carry a real cost line? (a zero cost is not shown: "cost line only when it costs"). */
export const hasCost = (r: OptionResult | null | undefined): boolean => Boolean(r) && (Math.abs(r!.cost.total) >= NO_COST);

/** The columns Tự tạo step 4 shows for these results: those that apply to their kinds, nothing else. */
export function metricsFor(results: readonly (OptionResult | null)[]): Metric[] {
  const want = new Set<Metric>();
  for (const r of results) {
    if (!r) continue;
    const s = strategyOfResult(r);
    if (s === "listing") {
      for (const d of r.drivers_pct) if (d.pct !== null && (d.metric === "views" || d.metric === "ctr")) want.add(d.metric);
    } else if (s === "ads") {
      (["gmv", "cost", "ads_orders", "cpa", "roas"] as const).forEach((m) => want.add(m));
      if (r.roi?.value != null) want.add("roi");
    } else if (s === "affiliate") {
      want.add("gmv");
      if (hasCost(r)) want.add("cost");
    } else {
      (["gmv", "profit", "orders", "aov", "margin"] as const).forEach((m) => want.add(m));
      if (hasCost(r)) {
        want.add("cost");
        if (r.cost.break_even_orders != null) want.add("breakeven");
        if (r.roi?.value != null) want.add("roi");
      }
    }
  }
  return ORDER.filter((m) => want.has(m));
}

/** One line saying why a result has no figures (never one "Không tính được" per row). */
export function reasonLine(r: Pick<OptionResult, "estimable" | "reason_text" | "notes" | "delta"> | null | undefined): string {
  if (!r) return "Chưa tính được phương án này.";
  return r.reason_text || r.delta.orders.note || r.notes[0] || "Chưa ước tính được.";
}

type MoneyMetric = "gmv" | "orders" | "profit";

/** F5: is this metric listed in the result's `within_noise`? */
export const inNoise = (r: Pick<OptionResult, "estimable" | "within_noise"> | null | undefined, m: MoneyMetric): boolean => Boolean(r && r.estimable && r.within_noise?.includes(m));

/** A Δ the screen shows: the wire value, or (inside the noise band, where the wire value is null) the P50 rebuilt from the untouched before / likely columns. */
export function deltaOf(r: OptionResult, m: MoneyMetric): { readonly value: number | null; readonly noise: boolean } {
  const noise = inNoise(r, m);
  const wire = m === "profit" ? (r.delta.profit?.value ?? null) : r.delta[m].value;
  if (wire !== null || !noise) return { value: wire, noise };
  const b = r.detail.before;
  const l = r.detail.likely;
  if (!l) return { value: null, noise };
  const value = m === "gmv" ? l.gmv - b.gmv : m === "orders" ? l.orders - b.orders : l.profit !== null && b.profit !== null ? l.profit - b.profit : null;
  return { value, noise };
}

/** "Có lãi" only when Δ lợi nhuận > 0. */
export function profitVerdict(r: OptionResult): { readonly text: string; readonly tone: "up" | "down" | "flat" } {
  if (!r.estimable) return { text: "Chưa ước tính", tone: "flat" };
  const { value: v, noise } = deltaOf(r, "profit");
  if (noise) return { text: "Trong dao động", tone: "flat" };
  if (v === null || v === undefined) return { text: "—", tone: "flat" };
  if (v > 0) return { text: "Có lãi", tone: "up" };
  if (v < 0) return { text: `Lỗ phần thêm ${vnd(Math.round(-v))}`, tone: "down" };
  return { text: "Không đổi", tone: "flat" };
}
