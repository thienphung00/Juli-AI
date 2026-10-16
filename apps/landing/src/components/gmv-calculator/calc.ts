/**
 * Pure maths of the free GMV calculator (`/cong-cu/tinh-gmv`, D49.1, P43).
 * No DOM, no network: the page runs it in the browser and nothing leaves it.
 *
 * GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU), the identity that
 * follows from TikTok's own metric definitions (CTR = Lượt nhấp ÷ Lượt hiển
 * thị, CTOR = Đơn hàng SKU ÷ Lượt nhấp, AOV (SKU) = GMV ÷ Đơn hàng SKU), see
 * the "GMV là gì" post. Rates are carried as fractions (0.03 = 3 %).
 */

/* ————— Vietnamese number parsing ————— */

export type ParseResult =
  | { ok: true; value: number }
  | { ok: false; reason: "empty" | "invalid" | "negative" };

const GROUPED = /^\d{1,3}(?:[.]\d{3})+$/;
const GROUPED_COMMA = /^\d{1,3}(?:,\d{3}){2,}$/;

/**
 * Reads a number the way a Vietnamese seller types it: "." groups thousands
 * ("50.000", "1.250.000"), "," is the decimal mark ("3,5"); spaces, "₫", "đ",
 * "%" and "VND" are ignored. A lone "." followed by anything other than
 * exactly three digits is read as a decimal point too ("3.5" → 3,5), since
 * that is what someone typing a CTR means; "1.500" stays 1.500 (one thousand
 * five hundred). Several "," in 3-digit groups ("1,250,000") are thousands.
 */
export function parseVietnameseNumber(raw: string): ParseResult {
  let text = raw
    .replace(/[\s  ]/g, "")
    .replace(/vnd|vnđ|₫|đ|%/gi, "");
  if (text === "") return { ok: false, reason: "empty" };
  let negative = false;
  if (text.startsWith("-") || text.startsWith("−")) {
    negative = true;
    text = text.slice(1);
  }
  if (!/^[\d.,]+$/.test(text) || !/\d/.test(text)) return { ok: false, reason: "invalid" };

  let normalised: string;
  const dots = (text.match(/\./g) ?? []).length;
  const commas = (text.match(/,/g) ?? []).length;
  if (dots > 0 && commas > 0) {
    // 1.234,5: dots group, the single comma is the decimal mark.
    const [intPart, fraction, ...rest] = text.split(",");
    if (rest.length > 0 || commas !== 1 || !GROUPED.test(intPart!) || !/^\d+$/.test(fraction!)) {
      return { ok: false, reason: "invalid" };
    }
    normalised = `${intPart!.replace(/\./g, "")}.${fraction}`;
  } else if (dots > 0) {
    if (GROUPED.test(text)) normalised = text.replace(/\./g, "");
    else if (dots === 1 && /^\d*\.\d+$/.test(text)) normalised = text;
    else return { ok: false, reason: "invalid" };
  } else if (commas > 0) {
    if (GROUPED_COMMA.test(text)) normalised = text.replace(/,/g, "");
    else if (commas === 1 && /^\d*,\d+$/.test(text)) normalised = text.replace(",", ".");
    else return { ok: false, reason: "invalid" };
  } else {
    normalised = text;
  }

  const value = Number(normalised);
  if (!Number.isFinite(value)) return { ok: false, reason: "invalid" };
  if (negative && value !== 0) return { ok: false, reason: "negative" };
  return { ok: true, value };
}

/* ————— Vietnamese number formatting ————— */

/**
 * `1234567.891` → "1.234.567,89" (dấu chấm nghìn, dấu phẩy thập phân), rounded
 * half away from zero to at most `maxFractionDigits`, trailing zeros dropped.
 * Written by hand so the output does not depend on the runtime's ICU data.
 */
export function formatVietnameseNumber(value: number, maxFractionDigits = 0): string {
  if (!Number.isFinite(value)) return "";
  const factor = 10 ** maxFractionDigits;
  const rounded = Math.round(Math.abs(value) * factor + Number.EPSILON * factor) / factor;
  const sign = value < 0 && rounded !== 0 ? "-" : "";
  const [intPart, fraction = ""] = rounded.toFixed(maxFractionDigits).split(".");
  const grouped = intPart!.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const trimmed = fraction.replace(/0+$/, "");
  return `${sign}${grouped}${trimmed ? `,${trimmed}` : ""}`;
}

/** "10.800.000 ₫" (whole đồng). */
export function formatVnd(value: number): string {
  return `${formatVietnameseNumber(value, 0)} ₫`;
}

/** A fraction as a percentage: 0.0325 → "3,25 %". */
export function formatPercent(fraction: number, maxFractionDigits = 2): string {
  return `${formatVietnameseNumber(fraction * 100, maxFractionDigits)} %`;
}

/** A count, whole: 1499.6 → "1.500". */
export function formatCount(value: number): string {
  return formatVietnameseNumber(value, 0);
}

/* ————— Inputs and validation ————— */

export type FactorKey = "impressions" | "ctr" | "ctor" | "aov";

export const FACTOR_ORDER: readonly FactorKey[] = ["impressions", "ctr", "ctor", "aov"];

export const FACTOR_LABELS: Record<FactorKey, string> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "CTR",
  ctor: "CTOR",
  aov: "AOV (SKU)",
};

/** Mode A: the four factors. */
export interface RateInputs {
  impressions: string;
  ctrPercent: string;
  ctorPercent: string;
  aov: string;
}

/** Mode B: counts; GMV or AOV, whichever the seller has. */
export interface CountInputs {
  impressions: string;
  clicks: string;
  orders: string;
  money: "gmv" | "aov";
  gmv: string;
  aov: string;
}

export type FieldErrors<K extends string> = Partial<Record<K, string>>;

export interface Funnel {
  impressions: number;
  /** Lượt nhấp; in rate mode it is derived and may carry decimals (shown rounded). */
  clicks: number;
  /** Đơn hàng SKU; derived in rate mode. */
  orders: number;
  gmv: number;
  /** Fractions; `null` when undefined (no clicks → no CTOR; no orders → no AOV). */
  ctr: number | null;
  ctor: number | null;
  aov: number | null;
  /** The first factor that is 0: GMV is 0 because of it. */
  zeroFactor: FactorKey | null;
  /** Data that is possible but worth a second look (Vietnamese, shown under the result). */
  warnings: string[];
}

export type CalcResult<K extends string> =
  | { ok: true; funnel: Funnel }
  | { ok: false; errors: FieldErrors<K> };

const MESSAGES = {
  empty: (label: string) => `Nhập ${label}.`,
  invalid: (label: string) =>
    `${label} chưa đúng định dạng số. Ví dụ: 50.000 hoặc 3,5 (dấu chấm ngăn hàng nghìn, dấu phẩy cho phần thập phân).`,
  negative: (label: string) => `${label} không thể là số âm.`,
  whole: (label: string) => `${label} là số đếm, cần là số nguyên (không có phần thập phân).`,
  positive: (label: string) => `${label} cần lớn hơn 0.`,
} as const;

function read(
  raw: string,
  label: string,
  { whole = false, positive = false }: { whole?: boolean; positive?: boolean } = {},
): { value: number } | { error: string } {
  const parsed = parseVietnameseNumber(raw);
  if (!parsed.ok) return { error: MESSAGES[parsed.reason](label) };
  if (whole && !Number.isInteger(parsed.value)) return { error: MESSAGES.whole(label) };
  if (positive && parsed.value <= 0) return { error: MESSAGES.positive(label) };
  return { value: parsed.value };
}

function zeroFactorOf(f: Pick<Funnel, "impressions" | "ctr" | "ctor" | "aov">): FactorKey | null {
  if (f.impressions === 0) return "impressions";
  if (f.ctr === 0) return "ctr";
  if (f.ctor === 0) return "ctor";
  if (f.aov === 0) return "aov";
  return null;
}

const CTOR_OVER_100 =
  "CTOR trên 100 % nghĩa là số Đơn hàng SKU nhiều hơn số Lượt nhấp. Điều này có thể xảy ra khi một khách đặt nhiều SKU, nhưng hãy kiểm tra lại rằng mọi số lấy trên cùng sản phẩm, cùng luồng và cùng kỳ.";

/** Mode A: Lượt hiển thị, CTR %, CTOR %, AOV ₫ → the funnel. */
export function calculateFromRates(input: RateInputs): CalcResult<keyof RateInputs> {
  const errors: FieldErrors<keyof RateInputs> = {};
  const impressions = read(input.impressions, "Lượt hiển thị sản phẩm", { whole: true, positive: true });
  const ctr = read(input.ctrPercent, "CTR");
  const ctor = read(input.ctorPercent, "CTOR");
  const aov = read(input.aov, "AOV", { positive: true });
  if ("error" in impressions) errors.impressions = impressions.error;
  if ("error" in ctr) errors.ctrPercent = ctr.error;
  else if (ctr.value > 100) errors.ctrPercent = "CTR không thể quá 100 %: số lượt nhấp không vượt quá số lượt hiển thị.";
  if ("error" in ctor) errors.ctorPercent = ctor.error;
  if ("error" in aov) errors.aov = aov.error;
  if (Object.keys(errors).length > 0 || "error" in impressions || "error" in ctr || "error" in ctor || "error" in aov) {
    return { ok: false, errors };
  }

  const ctrFraction = ctr.value / 100;
  const ctorFraction = ctor.value / 100;
  const clicks = impressions.value * ctrFraction;
  const orders = clicks * ctorFraction;
  const funnel: Funnel = {
    impressions: impressions.value,
    clicks,
    orders,
    gmv: orders * aov.value,
    ctr: ctrFraction,
    ctor: ctorFraction,
    aov: aov.value,
    zeroFactor: null,
    warnings: ctorFraction > 1 ? [CTOR_OVER_100] : [],
  };
  funnel.zeroFactor = zeroFactorOf(funnel);
  return { ok: true, funnel };
}

/** Mode B: Lượt hiển thị, Lượt nhấp, Đơn hàng SKU and GMV or AOV → the rates. */
export function calculateFromCounts(input: CountInputs): CalcResult<"impressions" | "clicks" | "orders" | "gmv" | "aov"> {
  type Key = "impressions" | "clicks" | "orders" | "gmv" | "aov";
  const errors: FieldErrors<Key> = {};
  const impressions = read(input.impressions, "Lượt hiển thị sản phẩm", { whole: true, positive: true });
  const clicks = read(input.clicks, "Lượt nhấp", { whole: true });
  const orders = read(input.orders, "Đơn hàng SKU", { whole: true });
  const money =
    input.money === "gmv" ? read(input.gmv, "GMV") : read(input.aov, "AOV", { positive: true });
  if ("error" in impressions) errors.impressions = impressions.error;
  if ("error" in clicks) errors.clicks = clicks.error;
  if ("error" in orders) errors.orders = orders.error;
  if ("error" in money) errors[input.money] = money.error;
  if ("error" in impressions || "error" in clicks || "error" in orders || "error" in money) {
    return { ok: false, errors };
  }

  if (clicks.value > impressions.value) {
    errors.clicks = "Lượt nhấp không thể nhiều hơn Lượt hiển thị sản phẩm. Kiểm tra lại hai số này có cùng sản phẩm, cùng luồng và cùng kỳ không.";
  }
  if (clicks.value === 0 && orders.value > 0) {
    errors.orders = "Có Đơn hàng SKU thì cần có Lượt nhấp. Kiểm tra lại số Lượt nhấp.";
  }
  if (input.money === "gmv" && orders.value === 0 && money.value > 0) {
    errors.gmv = "Có GMV thì cần có Đơn hàng SKU. Kiểm tra lại số Đơn hàng SKU.";
  }
  if (input.money === "gmv" && orders.value > 0 && money.value === 0) {
    errors.gmv = "Có Đơn hàng SKU thì GMV cần lớn hơn 0.";
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };

  const ctr = clicks.value / impressions.value;
  const ctor = clicks.value > 0 ? orders.value / clicks.value : null;
  let aov: number | null;
  let gmv: number;
  if (input.money === "gmv") {
    gmv = money.value;
    aov = orders.value > 0 ? gmv / orders.value : null;
  } else {
    aov = money.value;
    gmv = orders.value * aov;
  }
  const funnel: Funnel = {
    impressions: impressions.value,
    clicks: clicks.value,
    orders: orders.value,
    gmv,
    ctr,
    ctor,
    aov,
    zeroFactor: null,
    warnings: ctor !== null && ctor > 1 ? [CTOR_OVER_100] : [],
  };
  funnel.zeroFactor = zeroFactorOf(funnel);
  return { ok: true, funnel };
}

/* ————— What-if ————— */

export interface Uplift {
  factor: FactorKey;
  /** The factor before and after (impressions as a count, rates as fractions, AOV in ₫). */
  from: number;
  to: number;
  gmv: number;
  gain: number;
}

/** The factor's current value, or `null` when it is undefined for this funnel. */
export function factorValue(funnel: Funnel, factor: FactorKey): number | null {
  return factor === "impressions" ? funnel.impressions : funnel[factor];
}

/**
 * GMV when only `factor` moves to `to`, the other three held where they are.
 * `null` when the funnel has no value for another factor (e.g. no orders, so
 * no AOV): then GMV cannot be rebuilt from the factors.
 */
export function gmvWithFactor(funnel: Funnel, factor: FactorKey, to: number): number | null {
  let product = 1;
  for (const key of FACTOR_ORDER) {
    const value = key === factor ? to : factorValue(funnel, key);
    if (value === null) return null;
    product *= value;
  }
  return product;
}

/**
 * +`percent` % on each factor in turn, the rest unchanged. Because GMV is a
 * product, every row gives the same GMV: (1 + p) × GMV. That equality is the
 * point the page makes instead of naming a "low" metric without a benchmark.
 */
export function equalUplifts(funnel: Funnel, percent: number): Uplift[] {
  const multiplier = 1 + percent / 100;
  return FACTOR_ORDER.flatMap((factor) => {
    const from = factorValue(funnel, factor);
    if (from === null) return [];
    const to = from * multiplier;
    const gmv = gmvWithFactor(funnel, factor, to);
    if (gmv === null) return [];
    return [{ factor, from, to, gmv, gain: gmv - funnel.gmv }];
  });
}

/** Relative GMV change as a fraction; `null` from a GMV of 0. */
export function relativeChange(before: number, after: number): number | null {
  return before === 0 ? null : (after - before) / before;
}
