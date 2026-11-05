import { DASH, fmt } from "../shopee-analytics/format";
import type { Card, MoneyAt, N } from "./types";

/**
 * Units the seller reads (no "per month" on a card): per DAY for flows, per ORDER for unit economics,
 * and the total over the change's own days ("trong 3 ngày"). New cards carry `per_day` / `period` /
 * `per_order`; a card stored before them is converted from its `money_per_month` (which already
 * covers `days` days, capped at 30).
 */

const num = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const MINUS = "−";

/** Signed money with the precision a small flow needs: to 100đ under 100.000đ, else to nghìn. */
export function sm(n: N | undefined): string {
  if (!num(n)) return DASH;
  const step = Math.abs(n) < 100_000 ? 100 : 1000;
  const r = Math.round(n / step) * step;
  return `${r >= 0 ? "+" : MINUS}${fmt(Math.abs(r))}đ`;
}

/** Unsigned money, same precision rule. */
export function um(n: N | undefined): string {
  if (!num(n)) return DASH;
  const step = Math.abs(n) < 100_000 ? 100 : 1000;
  return `${fmt(Math.round(n / step) * step)}đ`;
}

export function srange(lo: N | undefined, hi: N | undefined): string {
  if (!num(lo) || !num(hi)) return DASH;
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  return sm(a) === sm(b) ? sm(a) : `${sm(a)} – ${sm(b)}`;
}

export interface Flow {
  readonly dchi: N;
  readonly certain: N;
  readonly p10: N;
  readonly p50: N;
  readonly p90: N;
  readonly gmv50: N;
}

export interface Units {
  readonly days: number;
  readonly perDay: Flow;
  readonly period: Flow;
  readonly perOrder: { readonly basis: "order" | "voucher_use"; readonly orders: number; readonly cost: N; readonly certain: N; readonly p10: N; readonly p50: N; readonly p90: N } | null;
}

const scale = (n: N | undefined, k: number): N => (num(n) ? n * k : null);

export function unitsOf(card: Pick<Card, "predicted">): Units {
  const m = card.predicted.money_per_month;
  const days = Math.max(1, m.period?.days ?? m.days ?? 1);
  const period: Flow = m.period
    ? { dchi: m.period.certain.dchi, certain: m.period.certain.dprofit, p10: m.period.total.p10.dprofit, p50: m.period.total.p50.dprofit, p90: m.period.total.p90.dprofit, gmv50: m.period.total.p50.dgmv }
    : { dchi: m.certain.dchi, certain: m.certain.dprofit, p10: m.total.p10.dprofit, p50: m.total.p50.dprofit, p90: m.total.p90.dprofit, gmv50: m.total.p50.dgmv };
  const perDay: Flow = m.per_day
    ? { dchi: m.per_day.certain.dchi, certain: m.per_day.certain.dprofit, p10: m.per_day.total.p10.dprofit, p50: m.per_day.total.p50.dprofit, p90: m.per_day.total.p90.dprofit, gmv50: m.per_day.total.p50.dgmv }
    : { dchi: scale(period.dchi, 1 / days), certain: scale(period.certain, 1 / days), p10: scale(period.p10, 1 / days), p50: scale(period.p50, 1 / days), p90: scale(period.p90, 1 / days), gmv50: scale(period.gmv50, 1 / days) };
  const po = m.per_order;
  return {
    days,
    perDay,
    period,
    perOrder: po ? { basis: po.basis, orders: po.orders_in_period, cost: po.certain.cost, certain: po.certain.dprofit, p10: po.total.p10.dprofit, p50: po.total.p50.dprofit, p90: po.total.p90.dprofit } : null,
  };
}

/** "đơn dùng voucher" for a voucher, "đơn" otherwise. */
export const perOrderNoun = (u: Units): string => (u.perOrder?.basis === "voucher_use" ? "đơn dùng voucher" : "đơn");

/** "Δ lợi nhuận V1 +300đ – +900đ/ngày (trong 14 ngày: +4.000đ – +12.000đ)" for a card list line. */
export function profitLine(u: Units): string {
  return `${srange(u.perDay.p10, u.perDay.p90)}/ngày (trong ${fmt(u.days)} ngày: ${srange(u.period.p10, u.period.p90)})`;
}

/** Expected orders per day and over the period (low – high), from the model layer. */
export function ordersText(card: Pick<Card, "predicted">): { readonly perDay: string; readonly period: string; readonly changes: boolean } | null {
  const o = card.predicted.money_per_month.orders;
  if (!o) return null;
  const rng = (lo: N, hi: N, d: number) => (num(lo) && num(hi) ? (Math.round(lo * 10 ** d) === Math.round(hi * 10 ** d) ? fmt(lo, d) : `${fmt(Math.min(lo, hi), d)} – ${fmt(Math.max(lo, hi), d)}`) : DASH);
  return {
    perDay: `${rng(o.total.p10.per_day, o.total.p90.per_day, 1)} đơn/ngày`,
    period: `${rng(o.total.p10.period, o.total.p90.period, 0)} đơn`,
    changes: o.total.p50.changes,
  };
}

export function aovText(card: Pick<Card, "predicted">): { readonly range: string; readonly certain: string } | null {
  const a = card.predicted.money_per_month.aov;
  if (!a || !num(a.total.p10) || !num(a.total.p90)) return null;
  const lo = Math.min(a.total.p10, a.total.p90);
  const hi = Math.max(a.total.p10, a.total.p90);
  return { range: Math.round(lo / 100) === Math.round(hi / 100) ? um(lo) : `${um(lo)} – ${um(hi)}`, certain: "AOV giữ nguyên ở lớp chắc chắn" };
}

export type { MoneyAt };
