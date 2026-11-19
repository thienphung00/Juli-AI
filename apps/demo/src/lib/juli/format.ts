/**
 * Number and direction helpers of the Juli tab (U10a): đồng with dot thousands, comma decimals,
 * ▲ / ▼ with `+` / `−`. Direction is never colour alone: the glyph or sign always comes with the class.
 */
import type { JuliDeltaDir } from "@juli/contracts";

const MINUS = "−";

function group(n: number): string {
  return Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** 8728160 -> "8.728.160đ". */
export function formatDong(value: number): string {
  const rounded = Math.round(value);
  return `${rounded < 0 ? MINUS : ""}${group(Math.abs(rounded))}đ`;
}

/** 15833 -> "+15.833đ", -665 -> "−665đ", 0 -> "0đ". */
export function formatSignedDong(value: number): string {
  const rounded = Math.round(value);
  if (rounded === 0) return "0đ";
  return `${rounded > 0 ? "+" : MINUS}${group(Math.abs(rounded))}đ`;
}

/** 16.14 -> "16,1%". */
export function formatPercent(value: number, digits = 1): string {
  return `${value.toFixed(digits).replace(".", ",")}%`;
}

export function dirOfNumber(value: number | null | undefined): JuliDeltaDir {
  if (value === null || value === undefined || Math.round(value) === 0) return "flat";
  return value > 0 ? "up" : "down";
}

export function dirOfChange(before: number | null, after: number | null): JuliDeltaDir {
  if (before === null || after === null) return "flat";
  const diff = Math.round((after - before) * 10) / 10;
  return diff === 0 ? "flat" : diff > 0 ? "up" : "down";
}

/** The class that carries the direction colour (success-text / destructive-text). */
export function dirClass(dir: JuliDeltaDir): string {
  return dir === "up" ? "juli-up" : dir === "down" ? "juli-down" : "juli-flat";
}

export function dirGlyph(dir: JuliDeltaDir): string {
  return dir === "up" ? "▲" : dir === "down" ? "▼" : "";
}

/** "12/11" from an ISO date. */
export function formatDayMonth(iso: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[2]}/${m[1]}` : iso;
}

/** "15:40" from an ISO timestamp (Asia/Ho_Chi_Minh). */
export function formatClock(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
}

/** History row time: "Hôm nay 14:20" or "16/11". */
export function formatHistoryTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = (x: Date) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Ho_Chi_Minh" }).format(x);
  if (day(d) === day(now)) return `Hôm nay ${formatClock(iso)}`;
  return formatDayMonth(day(d));
}
