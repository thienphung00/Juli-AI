import { DASH, fmt, vnCount, vnd } from "../../../lib/shopee-analytics/format";

/** Signed forms of the P98 option card: real minus (U+2212), vi-VN grouping, `null` = "—". */

const MINUS = "−";

function ok(n: number | null | undefined): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** "+120.000đ" / "−5.000đ" / "+0đ". */
export function signedMoney(n: number | null | undefined): string {
  if (!ok(n)) return DASH;
  const r = Math.round(n);
  return `${r < 0 ? MINUS : "+"}${vnd(Math.abs(r))}`;
}

/** A percent number: 1.7 → "+1,7%"; −3 → "−3,0%". */
export function signedPct(n: number | null | undefined): string {
  if (!ok(n)) return DASH;
  const s = fmt(Math.abs(n), 1);
  return `${n < 0 && s !== "0,0" ? MINUS : "+"}${s}%`;
}

/** An orders count: 12 → "+12", 0 → "+0", 2.5 → "+2,5". */
export function signedCount(n: number | null | undefined): string {
  if (!ok(n)) return DASH;
  const s = vnCount(Math.abs(n));
  return `${n < 0 && s !== "0" && s !== "0,0" ? MINUS : "+"}${s}`;
}

/** "money · pct" (the pct dropped when unknown). */
export function moneyPct(value: number | null | undefined, pct: number | null | undefined): string {
  return ok(pct) ? `${signedMoney(value)} · ${signedPct(pct)}` : signedMoney(value);
}

export function countPct(value: number | null | undefined, pct: number | null | undefined): string {
  return ok(pct) ? `${signedCount(value)} · ${signedPct(pct)}` : signedCount(value);
}
