/**
 * Number and date formats exactly as the Quyết định artboards print them
 * (`docs/product/design/quyet-dinh-flows/*.dc.html`): "5,4 %", "▲ 9,3 %",
 * "+2,1 tr ₫/tháng", "+70k ₫/ngày", "9.910", "155k – 165k ₫", "09/10/2026",
 * "16/10". Pure.
 */

import { vnDate } from "./timeline";

function grouped(value: number, decimals: number): string {
  const fixed = Math.abs(value).toFixed(decimals);
  const [whole, fraction] = fixed.split(".");
  const withDots = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return fraction ? `${withDots},${fraction}` : withDots;
}

const MINUS = "−";

function signOf(value: number): string {
  return value < 0 ? MINUS : "";
}

/** A ratio as a percent with one or two decimals: 0.054 → "5,4", 0.0444 → "4,44", 0.06 → "6,0". */
export function pctNumber(ratio: number, minDecimals = 1): string {
  const hundred = Math.round(ratio * 10_000) / 100;
  const two = Math.abs(hundred).toFixed(2);
  const decimals = two.endsWith("0") ? Math.max(1, minDecimals) : 2;
  return signOf(hundred) + grouped(hundred, decimals);
}

/** 0.054 → "5,4 %". */
export function ratioText(ratio: number, minDecimals = 1): string {
  return `${pctNumber(ratio, minDecimals)} %`;
}

/** VND compact without the currency: 2_100_000 → "2,1 tr", 70_000 → "70k", 950 → "950". */
export function compactVndNumber(value: number): string {
  const abs = Math.abs(value);
  const sign = signOf(value);
  if (abs >= 1e9) return `${sign}${grouped(abs / 1e9, 1)} tỷ`;
  if (abs >= 1e6) return `${sign}${grouped(abs / 1e6, 1)} tr`;
  if (abs >= 1e3) return `${sign}${grouped(Math.round(abs / 1e3), 0)}k`;
  return `${sign}${grouped(Math.round(abs), 0)}`;
}

/** 160_000 → "160k ₫". */
export function vndText(value: number): string {
  return `${compactVndNumber(value)} ₫`;
}

/** 2_100_000 → "+2,1 tr ₫"; −6_000 → "−6k ₫". */
export function signedVnd(value: number): string {
  return `${value >= 0 ? "+" : ""}${vndText(value)}`;
}

/** 9910 → "9.910". */
export function countText(value: number): string {
  return signOf(value) + grouped(Math.round(Math.abs(value)), 0);
}

export type ValueUnit = "ratio" | "vnd" | "count";

/** Decimals a ratio prints with (1 or 2), to keep a row's figures aligned ("4,44 %" → "4,40 %"). */
export function ratioDecimals(ratio: number): number {
  return pctNumber(ratio).split(",")[1]?.length ?? 1;
}

export function valueText(value: number, unit: ValueUnit, minDecimals = 1): string {
  if (unit === "ratio") return ratioText(value, minDecimals);
  if (unit === "vnd") return vndText(value);
  return countText(value);
}

/** "5,4 % → 5,9 %" / "182k → 205k ₫" (the artboards drop the first ₫). */
export function kpiPair(current: number, target: number, unit: "ratio" | "vnd"): string {
  if (unit === "vnd") return `${compactVndNumber(current)} → ${compactVndNumber(target)} ₫`;
  return `${ratioText(current)} → ${ratioText(target)}`;
}

/** Band range: "9.613 – 10.207", "4,31 % – 4,57 %", "155k – 165k ₫". */
export function rangeText(low: number, high: number, unit: ValueUnit): string {
  if (unit === "vnd") return `${compactVndNumber(low)} – ${compactVndNumber(high)} ₫`;
  if (unit === "ratio") return `${ratioText(low)} – ${ratioText(high)}`;
  return `${countText(low)} – ${countText(high)}`;
}

/** Relative change as "▲ 9,3 %" / "▼ 4,8 %" (one decimal). */
export function upliftChip(current: number, target: number): string | null {
  if (!Number.isFinite(current) || current === 0) return null;
  const rel = (target - current) / Math.abs(current);
  const arrow = rel >= 0 ? "▲" : "▼";
  return `${arrow} ${grouped(Math.abs(rel) * 100, 1)} %`;
}

/** Signed relative change "+1,2 %" / "−4,8 %". */
export function signedPct(rel: number): string {
  const value = Math.round(rel * 1000) / 10;
  return `${value >= 0 ? "+" : MINUS}${grouped(Math.abs(value), 1)} %`;
}

/** ISO → "09/10/2026" (Vietnam time). */
export function fullDate(iso: string | null | undefined): string {
  return vnDate(iso ?? null);
}

/** ISO or "YYYY-MM-DD" → "16/10". */
export function dayMonth(iso: string | null | undefined): string {
  const full = vnDate(iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T05:00:00Z` : (iso ?? null));
  return full === "—" ? full : full.slice(0, 5);
}

/** "YYYY-MM-DD" or ISO → "16/10/2026". */
export function dateText(value: string | null | undefined): string {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) return vnDate(`${value}T05:00:00Z`);
  return vnDate(value ?? null);
}

/** "Còn hiệu lực 3 giờ 58 phút" from an expiry and now. */
export function validityText(expiresAt: string, nowMs: number | null): string | null {
  if (nowMs === null) return null;
  const left = Date.parse(expiresAt) - nowMs;
  if (!Number.isFinite(left)) return null;
  if (left <= 0) return "Đã hết hiệu lực";
  const minutes = Math.floor(left / 60_000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days >= 1) return `Còn hiệu lực ${days} ngày ${hours % 24} giờ`;
  if (hours >= 1) return `Còn hiệu lực ${hours} giờ ${minutes % 60} phút`;
  return `Còn hiệu lực ${Math.max(1, minutes)} phút`;
}

/**
 * A long text as the artboards summarise it: "180 ký tự, một đoạn" (before)
 * or "640 ký tự · Thành phần · Cách dùng · Bảo quản" (after, its section
 * headings). Short text (≤ 160 chars, one line — already a summary) is returned unchanged.
 */
export function summariseText(text: string, mode: "before" | "after"): string {
  const trimmed = text.trim();
  if (trimmed.length <= 160 && !trimmed.includes("\n")) return trimmed;
  const length = [...trimmed].length;
  if (mode === "after") {
    const headings = [...trimmed.matchAll(/(?:^|\n)\s*([^:\n]{2,30}):/g)].map((m) => m[1].trim());
    return headings.length > 0 ? `${length} ký tự · ${headings.join(" · ")}` : `${length} ký tự`;
  }
  const paragraphs = trimmed.split(/\n\s*\n|\n/).filter((p) => p.trim()).length;
  return `${length} ký tự, ${paragraphs <= 1 ? "một đoạn" : `${paragraphs} đoạn`}`;
}
