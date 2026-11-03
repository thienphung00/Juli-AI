import type { InputUnit } from "./types";

const dot = (n: number): string => Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");

export function fmtVnd(value: number): string {
  return `${dot(value)}đ`;
}

export function fmtPct(value: number): string {
  return `${String(Math.round(value * 10) / 10).replace(".", ",")}%`;
}

export function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

export const GROUP_LABEL: Readonly<Record<string, string>> = { thuong_hieu: "Thương hiệu", phan_phoi: "Phân phối" };
export const STATUS_LABEL: Readonly<Record<string, string>> = {
  ban: "Đang bán",
  tam_dung: "Tạm dừng",
  ngung: "Ngừng bán",
  xa_hang: "Xả hàng",
};

/** A stored value in words, by its unit; `(chưa có)` for nothing. */
export function fmtValue(value: unknown, unit: InputUnit): string {
  if (value === null || value === undefined) return "(chưa có)";
  if (unit === "vnd" && typeof value === "number") return fmtVnd(value);
  if (unit === "pct" && typeof value === "number") return fmtPct(value);
  if (unit === "count" && typeof value === "number") return dot(value);
  if (unit === "date" && typeof value === "string") return fmtDate(value);
  if (unit === "group") return GROUP_LABEL[String(value)] ?? String(value);
  if (unit === "status") return STATUS_LABEL[String(value)] ?? String(value);
  return String(value);
}

/** Rule key -> label and unit, for the version table. */
export const RULE_FIELDS: Readonly<Record<string, { label: string; unit: InputUnit }>> = {
  sku_cost: { label: "Giá vốn", unit: "vnd" },
  packaging_cost: { label: "Đóng gói", unit: "vnd" },
  max_discount_pct: { label: "Giảm tối đa", unit: "pct" },
  stock: { label: "Tồn", unit: "count" },
  restock_date: { label: "Nhập lại", unit: "date" },
  product_group: { label: "Nhóm", unit: "group" },
  item_status: { label: "", unit: "status" },
};

export function fmtChanges(values: Readonly<Record<string, unknown>>): string {
  return Object.entries(RULE_FIELDS)
    .filter(([key]) => key in values)
    .map(([key, f]) => `${f.label ? `${f.label} ` : ""}${fmtValue(values[key], f.unit)}`)
    .join(" · ");
}

export const GOAL_FIELDS: readonly { key: string; label: string; unit: InputUnit }[] = [
  { key: "monthly_gmv_target", label: "GMV", unit: "vnd" },
  { key: "monthly_orders_target", label: "Đơn", unit: "count" },
  { key: "monthly_aov_target", label: "AOV", unit: "vnd" },
  { key: "monthly_margin_target", label: "Biên mục tiêu", unit: "pct" },
  { key: "daily_marketing_cap", label: "Trần chi marketing/ngày", unit: "vnd" },
];

/** `2026-12` -> `T12/2026`. */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  return `T${m}/${y}`;
}

export function fmtWhen(iso: string): string {
  // The API sends naive UTC; Vietnam is UTC+7 all year.
  const d = new Date(new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime() + 7 * 3_600_000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

export function fmtKb(bytes: number): string {
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
