/**
 * Vietnamese number formatting — "." thousands, "," decimals — mirroring the
 * shop diagnosis page's formatters (backend `shop_diagnosis/render.py`
 * `num` / `money` / `pct` / `change`), so the app and the owner-approved page
 * print the same figure the same way.
 */

const DASH = "—";

function grouped(value: number, decimals: number): string {
  const fixed = Math.abs(value).toFixed(decimals);
  const [whole, fraction] = fixed.split(".");
  const withDots = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const sign = value < 0 && Number(fixed) !== 0 ? "-" : "";
  return sign + (fraction ? `${withDots},${fraction}` : withDots);
}

export function num(value: number | null | undefined, decimals?: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const places = decimals ?? (Math.abs(value) >= 100 ? 0 : 1);
  return grouped(value, places);
}

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${grouped(Math.round(value), 0)} ₫`;
}

export function signedMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return (value >= 0 ? "+" : "−") + money(Math.abs(value));
}

export function pct(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${grouped(value * 100, decimals)} %`;
}

export type ChangeTone = "up" | "down" | "flat";

/** Relative change `last / prior − 1`, as text plus a tone. */
export function change(
  prior: number | null | undefined,
  last: number | null | undefined,
): { text: string; tone: ChangeTone } {
  if (
    prior === null ||
    prior === undefined ||
    last === null ||
    last === undefined ||
    prior === 0
  ) {
    return { text: DASH, tone: "flat" };
  }
  const ratio = last / prior - 1;
  const tone: ChangeTone = ratio > 0.005 ? "up" : ratio < -0.005 ? "down" : "flat";
  const sign = ratio >= 0 ? "+" : "−";
  return { text: `${sign}${grouped(Math.abs(ratio) * 100, 1)} %`, tone };
}

/** `2026-10-06` → `06/10/2026`; anything else is returned unchanged. */
export function slashDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : iso;
}

/** `2026-10-06` → `06/10` (chart ticks and date ranges inside a 60-day view). */
export function shortDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return match ? `${match[3]}/${match[2]}` : iso;
}
