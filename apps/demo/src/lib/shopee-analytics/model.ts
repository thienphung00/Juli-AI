import {
  chipFromChange,
  chipOf,
  chipPt,
  fmt,
  pc,
  pp,
  sv,
  vnd,
  type Chip,
  type Tone,
} from "./format";
import type { FiveNumbers, Kpi, N, Overview, WindowJson } from "./types";

/** Derivations the screens share: tones, ₫/ngày impacts, the five numbers, freshness. */

export const FIVE_LABELS = [
  "① % giảm giá",
  "② Doanh thu thêm / chi thêm",
  "③ Biên lợi nhuận cuối",
  "④ Số đơn",
  "⑤ AOV",
] as const;
export const CAP_LABEL = "Chi marketing / ngày vs trần";

/** Worse-by-8 % turns a cell red, better-by-8 % green (README decision 4). */
export const CELL_THRESHOLD = 0.08;

export function isBad(chip: Chip, threshold = CELL_THRESHOLD): boolean {
  return chip.up === false && Math.abs(chip.r) >= threshold;
}
export function isGood(chip: Chip, threshold = CELL_THRESHOLD): boolean {
  return chip.up === true && Math.abs(chip.r) >= threshold;
}

const isNum = (n: N | undefined): n is number => typeof n === "number" && Number.isFinite(n);

export interface Impacts {
  readonly views: number | null;
  readonly ctr: number | null;
  readonly ctor: number | null;
  readonly aov: number | null;
  readonly gmv: number | null;
}

/**
 * ₫ per day each link of the chain (views × CTR × CTOR × AOV) pulled GMV between the two windows:
 * the GMV change split by the logarithm of each factor's ratio (the artboards' `impacts`), so the
 * four add up to the GMV change.
 */
export function impactsOf(strip: Overview["kpi_strip"], days: number): Impacts {
  const none: Impacts = { views: null, ctr: null, ctor: null, aov: null, gmv: null };
  const g1 = strip.gmv.value;
  const g0 = strip.gmv.previous;
  if (!isNum(g1) || !isNum(g0) || days <= 0) return none;
  const dG = g1 - g0;
  const per = (x: Kpi): number | null => {
    if (!isNum(x.value) || !isNum(x.previous) || x.value <= 0 || x.previous <= 0) return null;
    if (g1 <= 0 || g0 <= 0) return null;
    if (g1 === g0) return 0;
    return (dG * Math.log(x.value / x.previous)) / Math.log(g1 / g0) / days;
  };
  return {
    views: per(strip.views),
    ctr: per(strip.ctr),
    ctor: per(strip.ctor),
    aov: per(strip.aov),
    gmv: dG / days,
  };
}

/** Index of the weakest link (most negative impact), for the "✦ Juli gợi ý" flag. */
export function weakestLink(impacts: Impacts): "views" | "ctr" | "ctor" | "aov" | null {
  let key: "views" | "ctr" | "ctor" | "aov" | null = null;
  let worst = 0;
  for (const k of ["views", "ctr", "ctor", "aov"] as const) {
    const v = impacts[k];
    if (v !== null && v < worst) {
      worst = v;
      key = k;
    }
  }
  return key;
}

export interface FiveCard {
  readonly key: "disc" | "eff" | "bien" | "orders" | "aov" | "cap";
  readonly label: string;
  readonly value: string;
  readonly chip: string;
  readonly tone: Tone;
  readonly sub1: string;
  readonly sub2: string;
  /** Ranking kpi the card opens. */
  readonly kpi: string;
  readonly src?: string;
}

/**
 * The executive's five numbers (+ spend vs cap), as the artboards print them. One function for
 * Tổng quan, Sản phẩm and the card, so a number reads the same everywhere (contract 5). When the
 * previous period has no order lines (`comparison.available` false) the "after" is shown and no
 * difference is invented.
 */
export function fiveCards(f: FiveNumbers, target: N | undefined): FiveCard[] {
  const compare = f.comparison.available;
  const d = f.discount;
  const discChip = compare ? chipPt(d.pct_before, d.pct_after) : { text: "—", up: null, r: 0 };
  const listValue = isNum(d.vnd_after) && isNum(d.pct_after) && d.pct_after > 0 ? (d.vnd_after / d.pct_after) * 100 : null;
  const e = f.extra_revenue_per_extra_spend;
  const giamChi = e.status === "giam_chi";
  const effValue = giamChi ? "giảm chi" : isNum(e.per_vnd) ? `${fmt(e.per_vnd, 2)}đ / 1đ chi` : "—";
  const m = f.margin;
  const marginChip = compare ? chipPt(m.pct_before, m.pct_after) : { text: "—", up: null, r: 0 };
  const belowTarget = isNum(m.pct_after) && isNum(target) && m.pct_after < target;
  const full = !m.is_partial;
  const o = f.orders;
  const orderChip = compare ? chipFromChange(o.change_pct) : { text: "—", up: null, r: 0 };
  const a = f.aov;
  const aovChip = compare ? chipFromChange(a.change_pct) : { text: "—", up: null, r: 0 };
  const toneOf = (c: Chip): Tone => (c.up === false ? "down" : c.up ? "up" : "flat");
  const cards: FiveCard[] = [
    {
      key: "disc",
      label: FIVE_LABELS[0],
      value: pp(d.pct_after, 1),
      chip: discChip.text,
      // Discount going UP is the bad direction.
      tone: discChip.r > 0.05 ? "down" : discChip.r < -0.05 ? "up" : "flat",
      sub1: `= ${vnd(d.vnd_after)} tiền giảm`,
      sub2: listValue === null ? "trên giá niêm yết" : `trên ${vnd(listValue)} giá niêm yết`,
      kpi: "disc",
    },
    {
      key: "eff",
      label: FIVE_LABELS[1],
      value: effValue,
      chip: !compare ? "—" : giamChi ? `Giảm chi ${vnd(isNum(e.extra_spend) ? -e.extra_spend : null)}` : isNum(e.per_vnd) ? `${fmt(e.per_vnd * 100, 0)}%` : "—",
      tone: !compare ? "flat" : giamChi ? "up" : e.below_one ? "down" : "up",
      sub1: compare ? `ΔGMV ${sv(e.extra_revenue)} ÷ Δchi ${sv(e.extra_spend)}` : "Chưa có kỳ trước để so",
      sub2: !compare ? "" : giamChi ? "Chi giảm hoặc không đổi" : e.below_one ? "Chi thêm nhiều hơn thu thêm" : "Thu thêm nhiều hơn chi thêm",
      kpi: "gmv",
    },
    {
      key: "bien",
      label: FIVE_LABELS[2],
      value: pp(m.pct_after, 1),
      chip: marginChip.text,
      tone: belowTarget ? "down" : toneOf(marginChip),
      sub1: full ? `= ${vnd(m.profit_after)} lợi nhuận` : `trên ${pp(m.cost_coverage_pct, 1)} doanh thu có giá vốn`,
      sub2: isNum(target) ? `Mục tiêu ${pp(target, 0)}: ${belowTarget ? "chưa đạt" : "đạt"}` : "Chưa đặt mục tiêu biên",
      kpi: "bien",
    },
    {
      key: "orders",
      label: FIVE_LABELS[3],
      value: isNum(o.after) ? `${fmt(o.after)} đơn` : "—",
      chip: orderChip.text,
      tone: toneOf(orderChip),
      sub1: "đơn đã xác nhận",
      sub2: compare && isNum(o.before) && isNum(o.after) ? `${o.after - o.before >= 0 ? "+" : "−"}${fmt(Math.abs(o.after - o.before))} đơn so với kỳ trước` : "",
      kpi: "orders",
    },
    {
      key: "aov",
      label: FIVE_LABELS[4],
      value: vnd(a.after),
      chip: aovChip.text,
      tone: toneOf(aovChip),
      sub1: "= GMV ÷ số đơn",
      sub2: compare && isNum(a.before) && isNum(a.after) ? `${sv(a.after - a.before)} so với kỳ trước` : "",
      kpi: "aov",
    },
  ];
  const cap = f.spend_cap;
  if (cap && isNum(cap.spend_per_day)) {
    const used = isNum(cap.used_pct) ? cap.used_pct : null;
    const high = cap.over_cap || (used !== null && used > 90);
    cards.push({
      key: "cap",
      label: CAP_LABEL,
      value: `${vnd(cap.spend_per_day)}/ngày`,
      chip: used === null ? "—" : `${fmt(used, 0)}% trần`,
      tone: high ? "down" : "flat",
      sub1: isNum(cap.cap) ? `Trần ${vnd(cap.cap)}/ngày (Cài đặt › Mục tiêu)` : "Chưa đặt trần",
      sub2:
        !isNum(cap.remaining) || !isNum(cap.cap)
          ? ""
          : cap.remaining >= 0
            ? `Còn ${vnd(cap.remaining)}${used === null ? "" : ` (${fmt(100 - used, 0)}%)`}`
            : `Vượt trần ${vnd(-cap.remaining)}`,
      kpi: "gmv",
      src: "ads",
    });
  }
  return cards;
}

export interface SourceFreshness {
  readonly key: string;
  readonly label: string;
  readonly covered: number;
  readonly days: number;
  readonly ok: boolean;
}

/**
 * Per source, how many of the window's days the stored data covers. The API names no source age,
 * only the days each source covers; a source under the window length is the stale-data state.
 */
export function freshnessOf(data: Overview["data"], window: WindowJson): SourceFreshness[] {
  const days = window.days;
  const rows: [string, string, number][] = [
    ["order_lines", "Đơn hàng", data.order_lines.days_with_orders],
    ["shop_totals", "Doanh số shop", data.shop_totals.days_covered],
    ["traffic", "Lưu lượng theo nguồn", data.traffic.days_covered],
    ["ads_daily", "Dịch vụ hiển thị", data.ads_daily.days_covered],
  ];
  return rows.map(([key, label, covered]) => ({ key, label, covered, days, ok: covered >= days }));
}

export function isStale(data: Overview["data"], window: WindowJson): boolean {
  return freshnessOf(data, window).some((s) => !s.ok && s.key !== "order_lines")
    || !data.order_lines.covers_window;
}

export function marginDropText(strip: Overview["kpi_strip"]): string | null {
  const now = strip.margin_pct.value;
  const before = strip.margin_pct.previous;
  if (!isNum(now) || !isNum(before) || Math.abs(now - before) < 0.05) return null;
  return `${now < before ? "biên giảm" : "biên tăng"} ${fmt(Math.abs(now - before), 1)} điểm`;
}

export { chipOf, pc };
