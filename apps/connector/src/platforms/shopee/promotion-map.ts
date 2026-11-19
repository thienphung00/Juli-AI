// Phân tích bán hàng › Khuyến mãi (Connector 0.3.29, F4.7): the per-programme performance list of
// one finished day -> `promotion_daily` (one row per promotion type and day, plus Shopee's "Tất cả"
// total, the file import's field names: services/ingest/schemas.py ShopeePromotionDailyRow) and a
// `promotions` snapshot of the programmes that had orders (terms only).
//
// Captured 2026-11-19: GET /api/mydata/marketing/new-discount/performance-list/
//   ?start_time=<day start>&end_time=<start+86400>&period=day&promotion_type=1&order_type=<placed|confirmed>
// -> {code: 0, result: [{promotion_id, promotion_name, promotion_type, status, create_time,
//    start_time, end_time, units, orders, buyers, sales, sales_per_buyer}]}; result is null on a day
//    with no promotion orders (an empty day: posted as zeros, not an error). promotion_type 1 asks
//    for every type in one answer (2 shop programmes, 3 combo, 4 add-on deal: unconfirmed).
// The backend keys a daily row by (date, promo_type), so programmes of one type are summed; a type
// the backend does not know (SHOPEE_PROMO_TYPES) only counts in the total.

import { type Mapped, type Row } from "./map";
import { ENDPOINTS } from "./endpoints";

/** Shopee's numeric promotion_type -> the file import's promotion type. */
export const PROMO_TYPE_LABELS: Record<number, string> = {
  2: "Chương Trình Khuyến Mãi",
  3: "Combo Khuyến Mãi",
  4: "Mua Kèm Deal Sốc",
};
export const PROMO_TYPE_ALL = "Tất cả";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNeg(value: unknown): number | undefined {
  const n = typeof value === "number" ? value : typeof value === "string" && value.trim() !== "" ? Number(value) : NaN;
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

/** Seller Centre's wall clock (GMT+7), no zone suffix, from unix seconds / ms. */
function wallClock(value: unknown): string | undefined {
  const n = nonNeg(value);
  if (n === undefined || n <= 0) return undefined;
  const seconds = n > 1e12 ? Math.floor(n / 1000) : n;
  return new Date((seconds + 7 * 3600) * 1000).toISOString().slice(0, 19);
}

interface Totals {
  sales: number;
  orders: number;
  units: number;
  buyers: number;
}
const zero = (): Totals => ({ sales: 0, orders: 0, units: 0, buyers: 0 });

function rowOf(date: string, promoType: string, t: Totals): Row {
  const row: Row = { date, promo_type: promoType, sales: t.sales, orders: t.orders, units: t.units, buyers: t.buyers };
  if (t.buyers > 0) row.sales_per_buyer = Math.round((t.sales / t.buyers) * 100) / 100;
  return row;
}

/** One answer of the performance list (one day, one order type) -> its posts; [] when it is not data. */
export function mapPromotionDailyAnswer(body: unknown, date: string, params: URLSearchParams): Mapped[] {
  if (!isRecord(body)) return [];
  const code = "code" in body ? body.code : body.error;
  if (code !== undefined && code !== null && code !== 0 && code !== "0") return [];
  if (params.get("promotion_type") !== "1") return []; // a single-type answer is not the day's total
  const orderType = params.get("order_type") === "placed" ? "placed" : params.get("order_type") === "confirmed" ? "confirmed" : null;
  if (orderType === null) return [];
  const result = body.result;
  if (result !== null && result !== undefined && !Array.isArray(result)) return [];
  const programmes = (Array.isArray(result) ? result : []).filter(isRecord);
  const total = zero();
  const byType = new Map<string, Totals>();
  for (const programme of programmes) {
    const t: Totals = {
      sales: nonNeg(programme.sales) ?? 0,
      orders: nonNeg(programme.orders) ?? 0,
      units: nonNeg(programme.units) ?? 0,
      buyers: nonNeg(programme.buyers) ?? 0,
    };
    for (const key of Object.keys(total) as (keyof Totals)[]) total[key] += t[key];
    const label = PROMO_TYPE_LABELS[Number(programme.promotion_type)];
    if (label) {
      const own = byType.get(label) ?? zero();
      for (const key of Object.keys(own) as (keyof Totals)[]) own[key] += t[key];
      byType.set(label, own);
    }
  }
  const daily: Mapped = {
    dataset: "promotion_daily",
    endpoint: ENDPOINTS.promotion_daily,
    date,
    orderType,
    rows: [rowOf(date, PROMO_TYPE_ALL, total), ...[...byType.entries()].map(([label, t]) => rowOf(date, label, t))],
    drift: null,
  };
  const posts: Mapped[] = [daily];
  // the programme snapshot: once per day (the placed answer), known types only, terms without numbers
  if (orderType === "placed") {
    const seen = new Map<string, number>();
    const rows: Row[] = [];
    for (const programme of programmes) {
      const label = PROMO_TYPE_LABELS[Number(programme.promotion_type)];
      const name = typeof programme.promotion_name === "string" ? programme.promotion_name.trim().slice(0, 255) : "";
      const startsAt = wallClock(programme.start_time);
      if (!label || !name || !startsAt) continue;
      const base = `${label}|${name}|${startsAt}`;
      const ordinal = seen.get(base) ?? 0;
      seen.set(base, ordinal + 1);
      const row: Row = { program_name: name, promo_type: label, starts_at: startsAt, ordinal };
      const endsAt = wallClock(programme.end_time);
      if (endsAt) row.ends_at = endsAt;
      rows.push(row);
    }
    if (rows.length > 0) {
      posts.push({ dataset: "promotions", endpoint: ENDPOINTS.promotion_daily, date, periodStart: date, orderType: null, granularity: "period", rows, drift: null });
    }
  }
  return posts;
}
