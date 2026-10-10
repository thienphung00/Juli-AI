/**
 * Below the streams (ADR-109 Amendment 2 d.5, PtProduct / PtMobile):
 * "Khuyến mãi" and "Lịch sale và chiến dịch", both collapsed until "Xem thêm".
 * Pure over the report: `shop_flash`, `vouchers`, `shop_bands`, `sale_days`
 * (ADR-108) and the P12 additive `promo_products`, `daily_gmv`, `seller_skus`.
 * Sections a report cannot fill say so instead of inventing figures.
 */

import type { ShopDiagnosisReport } from "../shop-analysis/types";
import { dayMonth, kMoney, percent, saleDayName } from "./format";
import { num } from "../vn-format";

export interface PromoStat {
  readonly k: string;
  readonly v: string;
  readonly sub: string;
}

export interface PromoRow {
  readonly productId: string;
  readonly sku: string | null;
  readonly name: string;
  readonly kind: string;
  readonly depth: string;
  /** A depth under the shallow line (5 %) is red. */
  readonly shallow: boolean;
  readonly gmv: string;
}

export interface PromoView {
  readonly stats: readonly PromoStat[];
  readonly rows: readonly PromoRow[];
}

/** Backend `ShopDiagnosisConfig.flash_shallow_depth`. */
const SHALLOW_DEPTH = 0.05;

function millions(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${num(value / 1e6, 1)} tr`;
}

export function promoView(report: ShopDiagnosisReport): PromoView {
  const flash = report.shop_flash;
  const products = report.promo_products ?? [];
  const flashProducts = products.filter((p) => p.kind === "Flash sale").length;
  const allDays = (report.daily_gmv ? Object.keys(report.daily_gmv).length : 0) || 60;
  const flashDays = flash ? flash.flash_days_last + flash.flash_days_prior : 0;
  const live = report.vouchers?.live ?? [];
  const reached = live
    .map((v) => v.above_after)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const stats: PromoStat[] = [
    {
      k: "Flash sale",
      v: `${num(flashDays, 0)}/${num(allDays, 0)} ngày`,
      sub: report.promo_products ? `${num(flashProducts, 0)} sản phẩm tham gia` : "Số sản phẩm chưa có trong báo cáo",
    },
    {
      k: "Giảm thật trung bình",
      v: typeof flash?.true_depth === "number" ? `−${num(Math.round(flash.true_depth * 100), 0)} %` : "—",
      sub: "So với giá đang bán trước flash sale",
    },
    {
      k: "Voucher",
      v: reached.length > 0 ? `${percent(Math.max(...reached), 0)} đơn` : `${num(live.length, 0)} voucher`,
      sub: reached.length > 0 ? `${num(live.length, 0)} voucher đang chạy · đơn đạt ngưỡng` : "đang chạy trong 60 ngày",
    },
  ];
  const rows: PromoRow[] = products.map((p) => ({
    productId: p.product_id,
    sku: report.seller_skus?.[p.product_id] ?? null,
    name: report.titles?.[p.product_id] || p.product_id,
    kind: p.kind,
    depth:
      typeof p.depth === "number"
        ? `−${num(Math.round(p.depth * 100), 0)} %${p.depth < SHALLOW_DEPTH ? " (quá nông)" : ""}`
        : "—",
    shallow: typeof p.depth === "number" && p.depth < SHALLOW_DEPTH,
    gmv: `${millions(p.gmv_in)} · ${millions(p.gmv_out)} ₫`,
  }));
  return { stats, rows };
}

export interface CalendarBar {
  readonly day: string;
  /** % of the tallest bar. */
  readonly height: number;
  readonly kind: "normal" | "flash" | "platform";
  readonly gmv: number;
}

export interface CalendarTile {
  readonly title: string;
  readonly text: string;
}

export interface CalendarView {
  readonly bars: readonly CalendarBar[];
  readonly first: string;
  /** "07/09 · bắt đầu 30 ngày gần đây". */
  readonly middle: string;
  readonly last: string;
  /** "9.9, 10.10" — the legend's platform sale days. */
  readonly saleNames: string;
  readonly tiles: readonly CalendarTile[];
}

function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function addDays(iso: string, days: number): Date {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * 86_400_000);
}

/** The next double-day sales (d.d) after `end`, within ~2 months. */
function upcomingSaleDays(end: string): string[] {
  const out: string[] = [];
  for (let i = 1; i <= 62 && out.length < 2; i += 1) {
    const day = addDays(end, i);
    if (day.getUTCDate() === day.getUTCMonth() + 1) out.push(day.toISOString().slice(0, 10));
  }
  return out;
}

const ratioText = (value: number) => num(value, 1);

/** `null` when the report has no daily GMV (a report built before P12). */
export function calendarView(report: ShopDiagnosisReport, flashCoverage = 0.5): CalendarView | null {
  const daily = report.daily_gmv;
  if (!daily || Object.keys(daily).length === 0) return null;
  const days = Object.keys(daily).sort();
  const sale = new Set(report.sale_days ?? []);
  const coverage = report.shop_flash?.coverage ?? {};
  const max = Math.max(1, ...days.map((d) => daily[d] ?? 0));
  const bars: CalendarBar[] = days.map((day) => ({
    day,
    gmv: daily[day] ?? 0,
    height: Math.max(1, Math.round(((daily[day] ?? 0) / max) * 100)),
    kind: sale.has(day) ? "platform" : (coverage[day] ?? 0) >= flashCoverage ? "flash" : "normal",
  }));
  const normal = median(bars.filter((b) => b.kind === "normal").map((b) => b.gmv));
  const tiles: CalendarTile[] = [];
  const platform = bars.filter((b) => b.kind === "platform").sort((a, b) => b.gmv - a.gmv)[0];
  if (platform && normal) {
    tiles.push({
      title: saleDayName(platform.day),
      text: `GMV ${kMoney(platform.gmv)}, gấp ${ratioText(platform.gmv / normal)} lần ngày thường`,
    });
  }
  const flashBand = (report.shop_bands ?? [])
    .filter((b) => b.kind === "Flash sale" && daily[b.first] !== undefined)
    .sort((a, b) => (daily[b.first] ?? 0) - (daily[a.first] ?? 0))[0];
  if (flashBand && normal) {
    const lift = (daily[flashBand.first] ?? 0) / normal - 1;
    const products = typeof flashBand.product_count === "number" ? `${num(flashBand.product_count, 0)} sản phẩm, ` : "";
    tiles.push({
      title: `Flash sale ${dayMonth(flashBand.first)}`,
      text: `${products}GMV ${lift >= 0 ? "+" : "−"}${num(Math.round(Math.abs(lift) * 100), 0)} % trong ngày`,
    });
  }
  const upcoming = upcomingSaleDays(report.end);
  if (upcoming.length > 0) tiles.push({ title: "Sắp tới", text: upcoming.map(saleDayName).join(", ") });
  const shownSales = [...sale].filter((d) => daily[d] !== undefined).sort();
  return {
    bars,
    first: dayMonth(days[0]),
    middle: `${dayMonth(report.windows.last_first)} · bắt đầu 30 ngày gần đây`,
    last: dayMonth(days[days.length - 1]),
    saleNames: [...shownSales, ...upcoming.slice(0, 1)].map(saleDayName).join(", "),
    tiles,
  };
}
