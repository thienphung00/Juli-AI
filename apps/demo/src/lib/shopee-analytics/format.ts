/**
 * Number formats of the Shopee shop artboards (docs/product/design/shopee-shop/README.md):
 * `1.234.567đ`, `3,66%`, a real minus (U+2212) and an explicit sign on changes. `null` is "not
 * known" and always prints "—", never 0.
 */

export const DASH = "—";
const MINUS = "−";

function finite(n: number | null | undefined): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** 1234567.891 → "1.234.568"; with `d` decimals "1.234.567,89". */
export function fmt(n: number | null | undefined, d = 0): string {
  if (!finite(n)) return DASH;
  const s = Math.abs(n).toFixed(d);
  const [whole = "0", frac] = s.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (n < 0 && Number(s) !== 0 ? MINUS : "") + grouped + (frac ? `,${frac}` : "");
}

/** "1.234.567đ". */
export function vnd(n: number | null | undefined): string {
  return finite(n) ? `${fmt(Math.round(n))}đ` : DASH;
}

/** "+1.234đ" / "−1.234đ". */
export function sv(n: number | null | undefined): string {
  if (!finite(n)) return DASH;
  const r = Math.round(n);
  return `${r >= 0 ? "+" : MINUS}${fmt(Math.abs(r))}đ`;
}

/** A fraction as a percent: 0.0366 → "3,66%". */
export function pc(x: number | null | undefined, d = 2): string {
  return finite(x) ? `${fmt(x * 100, d)}%` : DASH;
}

/** Percent points as a percent: 18.4 → "18,4%". */
export function pp(x: number | null | undefined, d = 1): string {
  return finite(x) ? `${fmt(x, d)}%` : DASH;
}

export function count(n: number | null | undefined): string {
  return fmt(n, 0);
}

export type Tone = "up" | "down" | "flat";
export interface Chip {
  readonly text: string;
  /** `null` = flat / unknown. */
  readonly up: boolean | null;
  /** The relative change (fraction) or the point change. */
  readonly r: number;
}

/** "▲ 12,3%" for a relative change of `now` against `before`. */
export function chipOf(before: number | null | undefined, now: number | null | undefined): Chip {
  if (!finite(before) || !finite(now) || before === 0) return { text: DASH, up: null, r: 0 };
  const r = now / before - 1;
  if (Math.abs(r) < 0.0005) return { text: "0,0%", up: null, r };
  return { text: `${r > 0 ? "▲" : "▼"} ${fmt(Math.abs(r) * 100, 1)}%`, up: r > 0, r };
}

/** "▲ 1,2 điểm" for two percent-point figures (margin, discount). */
export function chipPt(before: number | null | undefined, now: number | null | undefined): Chip {
  if (!finite(before) || !finite(now)) return { text: DASH, up: null, r: 0 };
  const d = now - before;
  if (Math.abs(d) < 0.05) return { text: "0,0 điểm", up: null, r: d };
  return { text: `${d > 0 ? "▲" : "▼"} ${fmt(Math.abs(d), 1)} điểm`, up: d > 0, r: d };
}

/** A percent-point change reported by the API (`change_pct`) as a chip. */
export function chipFromChange(changePct: number | null | undefined): Chip {
  if (!finite(changePct)) return { text: DASH, up: null, r: 0 };
  if (Math.abs(changePct) < 0.05) return { text: "0,0%", up: null, r: 0 };
  return {
    text: `${changePct > 0 ? "▲" : "▼"} ${fmt(Math.abs(changePct), 1)}%`,
    up: changePct > 0,
    r: changePct / 100,
  };
}

export function toneOfChip(chip: Chip, invert = false): Tone {
  if (chip.up === null) return "flat";
  return chip.up !== invert ? "up" : "down";
}

/** "01/11" from "2026-11-01". */
export function dayMonth(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const [, m, d] = iso.slice(0, 10).split("-");
  return m && d ? `${d}/${m}` : DASH;
}

/** "01/11–30/11". */
export function rangeText(w: { from: string; to: string } | null | undefined): string {
  return w ? `${dayMonth(w.from)}–${dayMonth(w.to)}` : DASH;
}
