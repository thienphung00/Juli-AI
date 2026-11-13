import { dayMonth, DASH } from "./format";

/**
 * P99b: any Shopee screen may answer HTTP 409 `rows_not_materialized` ({code, message, window{from,to},
 * missing_days (a count), first_missing}) when the window has data days without stored daily rows. The
 * screen then shows this notice and NO figures. Shared by the analytics client, the Quyết định clients and
 * the Kế hoạch client, so every screen says it the same way.
 */
export const ROWS_NOT_MATERIALIZED = "rows_not_materialized";

export interface NotMaterialized {
  readonly message: string;
  /** "01/11–30/11" or null when the answer carried no window. */
  readonly window: string | null;
  readonly missingDays: number | null;
  readonly firstMissing: string | null;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

/** The notice of a `rows_not_materialized` refusal, or null for any other error. */
export function notMaterializedOf(error: unknown): NotMaterialized | null {
  if (!(error instanceof Error)) return null;
  const e = error as Error & { code?: unknown; detail?: unknown };
  if (e.code !== ROWS_NOT_MATERIALIZED) return null;
  const d = isObj(e.detail) ? e.detail : {};
  const w = isObj(d["window"]) ? d["window"] : null;
  const from = w && typeof w["from"] === "string" ? w["from"] : null;
  const to = w && typeof w["to"] === "string" ? w["to"] : null;
  const md = d["missing_days"];
  const missing = typeof md === "number" ? md : Array.isArray(md) ? md.length : null;
  return {
    message: e.message && !/^HTTP \d+$/.test(e.message) ? e.message : "Số liệu của kỳ này chưa sẵn sàng.",
    window: from && to ? `${dayMonth(from)}–${dayMonth(to)}` : null,
    missingDays: missing,
    firstMissing: typeof d["first_missing"] === "string" ? d["first_missing"] : null,
  };
}

/** One line for places that only have a string (inline errors): message, window, missing days. */
export function notMaterializedLine(n: NotMaterialized): string {
  const parts = [n.message];
  if (n.window) parts.push(`Kỳ ${n.window}`);
  if (n.missingDays !== null) parts.push(`thiếu ${n.missingDays} ngày${n.firstMissing ? `, từ ${dayMonth(n.firstMissing)}` : ""}`);
  return `${parts[0]} ${parts.slice(1).join(" · ")}`.trim();
}

export { DASH };
