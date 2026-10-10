/**
 * Phân tích number formats (ADR-109 Amendment 2 artboards,
 * `docs/product/design/phan-tich/`): "3,6 tr ₫", "−250k ₫", "▲ 7,6 %".
 * Vietnamese separators ("." thousands, "," decimals) as `vn-format.ts`.
 */

import { num } from "../vn-format";

export const DASH = "—";

export type Tone = "up" | "down" | "flat";

export interface DeltaChip {
  readonly text: string;
  readonly tone: Tone;
}

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Unsigned short money: `3,6 tr ₫` from one million, else `620k ₫` (rounded to the thousand). */
export function kMoney(value: number | null | undefined): string {
  if (!finite(value)) return DASH;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${num(abs / 1e9, 2)} tỷ ₫`;
  if (abs >= 1e6) return `${num(abs / 1e6, 1)} tr ₫`;
  return `${num(Math.round(abs / 1e3), 0)}k ₫`;
}

/** Signed short money: `+620k ₫`, `−1,4 tr ₫`; a value that rounds to 0k reads `0k ₫`. */
export function signedKMoney(value: number | null | undefined): string {
  if (!finite(value)) return DASH;
  const text = kMoney(value);
  if (text === "0k ₫") return text;
  return `${value >= 0 ? "+" : "−"}${text}`;
}

/** `+250k ₫/ngày`. */
export function perDay(value: number | null | undefined): string {
  return finite(value) ? `${signedKMoney(value)}/ngày` : DASH;
}

/** The relative change chip: `▲ 7,6 %` / `▼ 15,2 %`; `—` without both sides. */
export function deltaChip(prior: number | null | undefined, last: number | null | undefined): DeltaChip {
  if (!finite(prior) || !finite(last) || prior === 0) return { text: DASH, tone: "flat" };
  const ratio = last / prior - 1;
  const text = `${num(Math.abs(ratio) * 100, 1)} %`;
  if (ratio > 0) return { text: `▲ ${text}`, tone: "up" };
  if (ratio < 0) return { text: `▼ ${text}`, tone: "down" };
  return { text: "0,0 %", tone: "flat" };
}

/** A whole-percent change for the h1: "15" for −15,2 %. */
export function roundedPercent(prior: number | null | undefined, last: number | null | undefined): string | null {
  if (!finite(prior) || !finite(last) || prior === 0) return null;
  return num(Math.round(Math.abs(last / prior - 1) * 100), 0);
}

/** Percent with `decimals` places: `4,44 %`. */
export function percent(value: number | null | undefined, decimals: number): string {
  return finite(value) ? `${num(value * 100, decimals)} %` : DASH;
}

/** Count with "k" from ten thousand: `54,6k`, `1.310`. */
export function count(value: number | null | undefined): string {
  if (!finite(value)) return DASH;
  if (Math.abs(value) >= 10_000) return `${num(value / 1e3, 1)}k`;
  return num(Math.round(value), 0);
}

/** `2026-09-21` → `21/09`. */
export function dayMonth(iso: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  return match ? `${match[3]}/${match[2]}` : DASH;
}

/** `2026-09-09` → `9.9` (how sellers name a double-day sale). */
export function saleDayName(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return match ? `${Number(match[3])}.${Number(match[2])}` : iso;
}
