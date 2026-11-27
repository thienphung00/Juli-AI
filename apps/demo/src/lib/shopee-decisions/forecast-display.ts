// F7.8: the one display of a forecast / measurement amount. Every card shows ONE amount per metric
// ("dự kiến") plus the baseline ("hiện tại") and the change against it; the P10 / P90 band is never shown.
// Pure: no components.

import { metricLabel, roundHalfAway } from "../metrics";
import { DASH, dayMonth, fmt } from "../shopee-analytics/format";
import { NOISE_TAG } from "./card-rows";
import type { OptionResult } from "./option-result";

type N = number | null;
const MINUS = "−";

export type MetricKey = "profit" | "gmv" | "orders" | "aov";
export const METRIC_KEYS: readonly MetricKey[] = ["profit", "gmv", "orders", "aov"];

/** One `forecast.metrics.<key>` block of the API. `low` / `high` ride along on the wire and are never shown. */
export interface ForecastMetric {
  readonly hien_tai: N;
  readonly du_kien: N;
  readonly delta: N;
  readonly delta_pct: N;
  readonly low?: N;
  readonly high?: N;
  readonly days?: N;
}

export interface ForecastBlock {
  readonly metrics?: Partial<Record<MetricKey | "margin_pct", ForecastMetric>> | null;
  readonly schema?: string;
  readonly estimable?: boolean;
  /** F5 / D4: the metrics whose change is inside the normal swing (the server's field); see `isNoisy`. */
  readonly within_noise?: readonly string[] | null;
  /** F2 (forecast/2): the cost over the same days and how sure the forecast is. */
  readonly cost?: N;
  readonly evidence?: string | null;
  /** F1: "27/30 ngày có dữ liệu" of hiện tại. */
  readonly coverage?: { readonly days_with_data: number; readonly window_days: number; readonly label: string } | null;
  readonly data_through?: string | null;
  readonly days?: N;
  readonly reason_code?: string | null;
  readonly reason_text?: string | null;
}

/** `measurement.actual.metrics.<key>`: the running Thực tế against hiện tại. */
export interface ActualMetric {
  readonly thuc_te: N;
  readonly hien_tai: N;
  readonly delta: N;
  readonly delta_pct: N;
  readonly days_measured?: N;
  readonly days?: N;
}

export interface MeasureVerdictBlock {
  readonly key?: string;
  readonly label?: string;
}

export interface ActualBlock {
  readonly metrics?: Partial<Record<MetricKey | "margin_pct", ActualMetric>> | null;
  readonly days_measured?: N;
  readonly days?: N;
  readonly label?: string | null;
  readonly final?: boolean;
  readonly verdict?: MeasureVerdictBlock | null;
}

/** The card's `measurement` (list / detail) and the Đo lường row's flat fields. */
export interface MeasurementBlock {
  readonly actual?: ActualBlock | null;
  readonly label?: string | null;
  readonly verdict?: MeasureVerdictBlock | string | null;
  readonly group?: unknown;
  readonly clean?: boolean | null;
  readonly measured_with?: readonly string[] | null;
}

const ok = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

export function amountText(key: MetricKey, n: N | undefined): string {
  if (!ok(n)) return DASH;
  const r = roundHalfAway(n);
  return key === "orders" ? `${fmt(r, 0)} đơn` : `${fmt(r, 0)} đ`;
}

const signed = (n: number, text: string): string => `${n < 0 && roundHalfAway(n) !== 0 ? MINUS : "+"}${text}`;

/** "−3.000 đ" / "+4 đơn" (the unit follows the metric). */
export function deltaText(key: MetricKey, d: N | undefined): string {
  if (!ok(d)) return DASH;
  const body = key === "orders" ? `${fmt(Math.abs(roundHalfAway(d)), 0)}` : `${fmt(Math.abs(roundHalfAway(d)), 0)} đ`;
  return signed(d, body);
}

/** "−4,2 %" / "+0,0 %". */
export function pctText(p: N | undefined): string {
  if (!ok(p)) return DASH;
  const s = fmt(Math.abs(p), 1);
  return `${p < 0 && s !== "0,0" ? MINUS : "+"}${s} %`;
}

/** "−3.000 đ (−4,2 %)" (the percent is left out without one). */
export function changeText(key: MetricKey, d: N | undefined, p: N | undefined): string {
  if (!ok(d)) return DASH;
  return ok(p) ? `${deltaText(key, d)} (${pctText(p)})` : deltaText(key, d);
}

/** D1: the change is the difference of the two SHOWN (rounded) figures, so 52 → 53 reads "+1", never "+2". */
export function shownDelta(hien: N | undefined, du: N | undefined, fallback: N | undefined): N {
  return ok(hien) && ok(du) ? roundHalfAway(du) - roundHalfAway(hien) : ok(fallback) ? fallback : null;
}

/** The grey line under a headline: "hiện tại: Y đ · −Z đ (−p %)". */
export function baselineLine(key: MetricKey, m: ForecastMetric): string {
  return `hiện tại: ${amountText(key, m.hien_tai)} · ${changeText(key, shownDelta(m.hien_tai, m.du_kien, m.delta), m.delta_pct)}`;
}

/** D2: the card's profit is Lợi nhuận đóng góp (registry label); the other lines keep their short names. */
const LABEL: Record<MetricKey, string> = { profit: `${metricLabel("contribution")} dự kiến`, gmv: "GMV dự kiến", orders: "Đơn dự kiến", aov: "AOV dự kiến" };

export interface MetricView {
  readonly key: MetricKey;
  /** "Lợi nhuận dự kiến (30 ngày)" for profit, "GMV dự kiến" for the others. */
  readonly label: string;
  /** "X đ", "Lỗ X đ" (profit below 0) or "—". */
  readonly value: string;
  /** The grey line, null without an estimate. */
  readonly sub: string | null;
  /** Red only for a profit forecast below 0; never because Δ < 0. */
  readonly loss: boolean;
  /** Hover for a "—". */
  readonly why: string | undefined;
}

export function metricView(key: MetricKey, m: ForecastMetric | null | undefined, opts: { readonly days?: N; readonly why?: string | null; readonly noise?: boolean } = {}): MetricView {
  const days = m?.days ?? opts.days ?? null;
  const label = key === "profit" && ok(days) && days > 0 ? `${LABEL.profit} (${fmt(days, 0)} ngày)` : LABEL[key];
  if (!m || !ok(m.du_kien)) return { key, label, value: DASH, sub: null, loss: false, why: opts.why ?? undefined };
  const loss = key === "profit" && m.du_kien < 0;
  const amount = loss ? `Lỗ ${amountText(key, Math.abs(m.du_kien))}` : amountText(key, m.du_kien);
  // D4 (F5): inside the normal swing the amount is followed by the tag, never printed as a certain number
  const value = opts.noise ? `${amount} ${NOISE_TAG}` : amount;
  return { key, label, value, sub: ok(m.hien_tai) ? baselineLine(key, m) : null, loss, why: undefined };
}

/** D4: only the profit is tagged (the F5 design keeps GMV / đơn plain), and never a profit that goes down (F2: a loss reads as a loss). */
export function isNoisy(f: ForecastBlock | null | undefined, key: MetricKey): boolean {
  const m = f?.metrics?.[key];
  const loses = (n: unknown): boolean => ok(n) && n < 0;
  return key === "profit" && Boolean(f?.within_noise?.includes(key)) && !loses(m?.delta) && !loses(m?.du_kien);
}

/** The forecast of an option result: the server's block (F2). A result stored before forecast/2 carries none: it stays readable from its own columns until the refresh job recomputes it. */
export function forecastOfResult(r: OptionResult | null | undefined): ForecastBlock | null {
  if (!r) return null;
  return r.forecast ?? storedBeforeForecast2(r);
}

function storedBeforeForecast2(r: OptionResult): ForecastBlock {
  const days = r.after?.days || r.days;
  const b = r.detail.before;
  const l = r.estimable ? r.detail.likely : null;
  const block = (hien: N, du: N, relative = true): ForecastMetric => {
    if (du === null || hien === null) return { hien_tai: hien, du_kien: null, delta: null, delta_pct: null, days };
    // D1: the change is the difference of the shown figures; the percent stays on the unrounded pair
    const delta = roundHalfAway(du) - roundHalfAway(hien);
    return { hien_tai: hien, du_kien: du, delta, delta_pct: relative && hien > 0 ? ((du - hien) / hien) * 100 : null, days };
  };
  const aov = (g: N, o: N): N => (g !== null && o !== null && o > 0 ? g / o : null);
  return {
    days,
    within_noise: r.estimable ? (r.within_noise ?? []) : [],
    reason_code: r.reason_code ?? null,
    reason_text: r.reason_text ?? null,
    metrics: {
      profit: block(b.profit, l ? l.profit : null),
      gmv: block(b.gmv, l ? l.gmv : null),
      orders: block(b.orders, l ? l.orders : null),
      aov: block(aov(b.gmv, b.orders), l ? aov(l.gmv, l.orders) : null),
    },
  };
}

/** The forecast a screen shows: the server's `forecast`, else the one built from the stored result. */
export function forecastOf(card: { readonly forecast?: ForecastBlock | null; readonly result?: { readonly option?: OptionResult | null } | null }): ForecastBlock | null {
  return card.forecast ?? forecastOfResult(card.result?.option ?? null);
}

/** "Số liệu đến 18/11" (null without a day). */
export function dataThroughText(iso: string | null | undefined): string | null {
  const d = iso ? dayMonth(iso) : DASH;
  return d === DASH ? null : `Số liệu đến ${d}`;
}

/** The newest data day of a list of cards (for one header). */
export function newestDataThrough(cards: readonly { readonly data_through?: string | null; readonly forecast?: ForecastBlock | null }[]): string | null {
  let best: string | null = null;
  for (const c of cards) {
    const d = c.data_through ?? c.forecast?.data_through ?? null;
    if (d && (best === null || d > best)) best = d;
  }
  return best;
}

// ── Đo lường: Thực tế ───────────────────────────────────────────────────

export interface ActualView {
  readonly key: MetricKey;
  /** "Thực tế: A đ · hiện tại: B đ · +Δ (+p %)" */
  readonly text: string;
}

export function actualText(key: MetricKey, m: ActualMetric | null | undefined): string {
  if (!m || !ok(m.thuc_te)) return `Thực tế: ${DASH}`;
  const base = ok(m.hien_tai) ? ` · hiện tại: ${amountText(key, m.hien_tai)} · ${changeText(key, m.delta, m.delta_pct)}` : "";
  return `Thực tế: ${amountText(key, m.thuc_te)}${base}`;
}

/** "Đã đo k/N ngày": the server's label, else built from the days. */
export function measuredLabel(a: ActualBlock | null | undefined, fallback?: string | null): string | null {
  if (a?.label) return a.label;
  if (fallback) return fallback;
  return a && ok(a.days_measured) && ok(a.days) ? `Đã đo ${fmt(a.days_measured, 0)}/${fmt(a.days, 0)} ngày` : null;
}

/** The verdict text, only when the measurement is final. */
export function finalVerdict(a: ActualBlock | null | undefined): string | null {
  return a?.final && a.verdict?.label ? a.verdict.label : null;
}

/** "đo chung với GIA-1, DS-01b" (null when the list is empty). */
export function measuredWithText(codes: readonly string[] | null | undefined): string | null {
  const list = (codes ?? []).filter(Boolean);
  return list.length ? `đo chung với ${list.join(", ")}` : null;
}
