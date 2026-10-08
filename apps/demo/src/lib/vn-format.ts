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

/**
 * Short money for KPI cards and matrix cells, as the sales demo video prints
 * it: `1,14 tỷ ₫`, `9,7 tr ₫`, `240k ₫`.
 */
export function compactMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${grouped(value / 1e9, 2)} tỷ ₫`;
  if (abs >= 1e6) return `${grouped(value / 1e6, 1)} tr ₫`;
  if (abs >= 1e3) return `${grouped(Math.round(value / 1e3), 0)}k ₫`;
  return money(value);
}

const VN_TIME_ZONE = "Asia/Ho_Chi_Minh";

/** An ISO timestamp → `HH:MM` in Vietnam time; `null` when it does not parse. */
export function vnClock(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: VN_TIME_ZONE,
  }).formatToParts(new Date(time));
  const hour = parts.find((p) => p.type === "hour")?.value ?? "00";
  const minute = parts.find((p) => p.type === "minute")?.value ?? "00";
  return `${hour}:${minute}`;
}

const VN_WEEKDAYS = ["Chủ nhật", "Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy"];

/** An ISO timestamp → `Thứ tư, 07/10` in Vietnam time; `null` when it does not parse. */
export function vnWeekdayDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: VN_TIME_ZONE,
  }).formatToParts(new Date(time));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const weekday = new Date(Date.UTC(Number(get("year")), Number(get("month")) - 1, Number(get("day")))).getUTCDay();
  return `${VN_WEEKDAYS[weekday]}, ${get("day")}/${get("month")}`;
}
