import type { DiagKey, OverrideKey, ShopSettings } from "./types";

/**
 * D27.5: a settings change as "before → after" rows (artboard OpsConfirm.dc.html),
 * shared by the draft bar, the save dialog and the Nhật ký sentence.
 */

export const STREAM_NAMES: Readonly<Record<string, string>> = {
  product_card: "Thẻ sản phẩm",
  shop_tab: "Tab cửa hàng",
  seller_video: "Video",
  seller_live: "LIVE",
};

export const ACTION_NAMES: Readonly<Record<string, string>> = {
  cover_image: "Ảnh bìa",
  title: "Tiêu đề",
  description: "Mô tả",
  product_discount: "Giảm giá SP",
  buy_more_save_more: "Mua nhiều giảm nhiều",
  flash_sale: "Flash sale",
  shipping_discount: "Giảm phí ship",
  video_script: "Kịch bản video",
  live_script: "Kịch bản LIVE",
};

export const STAGE_NAMES: Readonly<Record<string, string>> = { trial: "Thử nghiệm", self: "Tự vận hành", pilot: "Pilot đặc biệt" };

/** Display order of the editable keys (the page's row order). */
export const SETTING_KEYS: readonly OverrideKey[] = [
  "card_daily_limit",
  "card_weekly_limit",
  "card_open_limit",
  "enabled_streams",
  "enabled_actions",
  "content_cards_enabled",
  "promotion_api_enabled",
  "openai_model",
  "openai_monthly_cap_usd",
  "diag_windows",
  "diag_min_events",
  "kpi_min_band_mult",
  "kpi_max_band_mult",
  "guard_band_mult",
  "volatile_cv",
];

/** P23 (D29.11): the "Chẩn đoán & KPI" keys, in row order. */
export const DIAG_KEYS: readonly DiagKey[] = [
  "diag_windows",
  "diag_min_events",
  "kpi_min_band_mult",
  "kpi_max_band_mult",
  "guard_band_mult",
  "volatile_cv",
];

export const SETTING_LABELS: Readonly<Record<string, string>> = {
  stage: "Giai đoạn",
  card_daily_limit: "Giới hạn thẻ/ngày",
  card_weekly_limit: "Giới hạn thẻ/tuần",
  card_open_limit: "Thẻ mở cùng lúc",
  enabled_streams: "Luồng",
  enabled_actions: "Hành động",
  content_cards_enabled: "Thẻ nội dung",
  promotion_api_enabled: "API khuyến mãi",
  openai_model: "Model OpenAI",
  openai_monthly_cap_usd: "Trần chi phí OpenAI",
  diag_windows: "Cửa sổ chẩn đoán",
  diag_min_events: "Dữ liệu tối thiểu",
  kpi_min_band_mult: "KPI tối thiểu",
  kpi_max_band_mult: "KPI tối đa",
  guard_band_mult: "Ngưỡng giữ ổn định",
  volatile_cv: "Ngưỡng lưu lượng ổn định",
};

const MULT_KEYS = new Set(["kpi_min_band_mult", "kpi_max_band_mult", "guard_band_mult"]);

const comma = (n: number) => String(n).replace(".", ",");

const LIST_NAMES: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  enabled_streams: STREAM_NAMES,
  enabled_actions: ACTION_NAMES,
};

export interface ChangeRow {
  /** Left column of the dialog ("Luồng", "API khuyến mãi"). */
  readonly k: string;
  readonly before: string;
  readonly after: string;
  /** One phrase for the bar / Nhật ký ("tắt LIVE", "API khuyến mãi: Tắt → Bật"). */
  readonly short: string;
}

function usd(n: number): string {
  return `$${String(n).replace(".", ",")}`;
}

/** One value in words; `null` is "Mặc định" (or "Không giới hạn" for the cap). */
export function fmtSetting(key: string, value: unknown): string {
  if (key === "stage") return STAGE_NAMES[String(value)] ?? String(value ?? "—");
  if (key === "openai_monthly_cap_usd") return value === null || value === undefined ? "Không giới hạn" : `${usd(Number(value))} / tháng`;
  if (value === null || value === undefined) return "Mặc định";
  if (key === "diag_windows" && Array.isArray(value)) return value.length ? `${[...value].sort((a, b) => Number(a) - Number(b)).join(" · ")} ngày` : "Không có";
  if (MULT_KEYS.has(key)) return `×${comma(Number(value))} dao động`;
  if (key === "volatile_cv") return `CV > ${comma(Math.round(Number(value) * 1000) / 10)} %`;
  if (key === "diag_min_events") return `${String(value)} lượt nhấp/đơn`;
  if (typeof value === "boolean") return value ? "Bật" : "Tắt";
  if (Array.isArray(value)) {
    const names = LIST_NAMES[key] ?? {};
    return value.map((v) => names[String(v)] ?? String(v)).join(" · ") || "Không có";
  }
  return String(value);
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/**
 * Rows for one key going from `before` to `after` (effective values). A list
 * gives one row per item switched on or off. `resetToDefault` marks an override
 * removed: when the value itself does not move, the row says "Ghi đè → Mặc định".
 */
export function changeRows(key: string, before: unknown, after: unknown, resetToDefault = false): ChangeRow[] {
  const label = SETTING_LABELS[key] ?? key;
  const names = LIST_NAMES[key];
  if (names && Array.isArray(before) && Array.isArray(after)) {
    const rows: ChangeRow[] = [];
    for (const id of before) {
      if (!after.includes(id)) {
        const n = names[String(id)] ?? String(id);
        rows.push({ k: label, before: n, after: "Tắt", short: `tắt ${n}` });
      }
    }
    for (const id of after) {
      if (!before.includes(id)) {
        const n = names[String(id)] ?? String(id);
        rows.push({ k: label, before: `${n} tắt`, after: "Bật", short: `bật ${n}` });
      }
    }
    if (rows.length > 0) return rows;
  } else if (!same(before, after)) {
    const b = fmtSetting(key, before);
    const a = fmtSetting(key, after);
    const afterText = resetToDefault && key !== "openai_monthly_cap_usd" ? `Mặc định (${a})` : a;
    if (typeof after === "boolean" && !resetToDefault) {
      return [{ k: label, before: b, after: afterText, short: `${after ? "bật" : "tắt"} ${label}` }];
    }
    return [{ k: label, before: b, after: afterText, short: `${label}: ${b} → ${afterText}` }];
  }
  if (resetToDefault) return [{ k: label, before: "Ghi đè", after: "Mặc định", short: `${label} về mặc định` }];
  return [];
}

function effective(settings: ShopSettings, key: OverrideKey, override: unknown): unknown {
  return override === null || override === undefined ? settings.defaults[key] : override;
}

/** The draft (override key → new override, `null` = về mặc định) as dialog rows. */
export function draftRows(settings: ShopSettings, draft: Partial<Record<OverrideKey, unknown>>): ChangeRow[] {
  const rows: ChangeRow[] = [];
  for (const key of SETTING_KEYS) {
    if (!(key in draft)) continue;
    const next = draft[key];
    const saved = settings.overrides[key];
    const reset = next === null && saved !== null && saved !== undefined;
    rows.push(...changeRows(key, effective(settings, key, saved), effective(settings, key, next), reset));
  }
  return rows;
}

/** "LIVE → Tắt · API khuyến mãi: Tắt → Bật · …" for the draft bar (first three rows). */
export function draftSummary(rows: readonly ChangeRow[]): string {
  const parts = rows.slice(0, 3).map((r) => (r.after === "Tắt" || r.after === "Bật") && r.before !== "Tắt" && r.before !== "Bật"
    ? `${r.before.replace(/ tắt$/, "")} → ${r.after}`
    : `${r.k}: ${r.before} → ${r.after}`);
  return parts.join(" · ") + (rows.length > 3 ? " …" : "");
}

/** Nhật ký sentence for a `settings_update` row (before/after are override snapshots). */
export function describeSettingsAudit(before: unknown, after: unknown): string {
  const b = (before ?? {}) as Record<string, unknown>;
  const a = (after ?? {}) as Record<string, unknown>;
  const keys = ["stage", ...SETTING_KEYS].filter((k) => k in a || k in b);
  const rows: ChangeRow[] = [];
  for (const k of keys) {
    const bv = k === "stage" ? (b.stage ?? "trial") : b[k];
    const av = k === "stage" ? (a.stage ?? "trial") : a[k];
    if (same(bv, av)) continue;
    rows.push(...changeRows(k, bv, av));
  }
  if (rows.length === 0) return "lưu cài đặt (không đổi gì)";
  if (rows.length === 1) {
    const r = rows[0];
    return r.short.startsWith("tắt ") || r.short.startsWith("bật ") ? `${r.k}: ${r.short}` : `${r.k}: ${r.before} → ${r.after}`;
  }
  return `Lưu ${rows.length} thay đổi: ${rows.map((r) => r.short).join(" · ")}`;
}
