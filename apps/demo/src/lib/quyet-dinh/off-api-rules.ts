/**
 * P14-F: the rule fields for what no TikTok API gives Juli (contract
 * `fasttrack/contracts/p14-rules-and-cost.md` §3; backend
 * `services/shop_rules/rules.py`). Labels, help text and the LIVE-slot text
 * format the editor reads and writes.
 */

import type { RuleValueItem, ShopRules } from "./types";

export type OffApiRuleKey =
  | "sku_cost"
  | "default_gross_margin_pct"
  | "default_max_discount_pct"
  | "program_fee_pct"
  | "joins_platform_campaigns"
  | "platform_campaign_note"
  | "target_roas"
  | "gmv_max_daily_budget"
  | "live_schedule";

export interface LiveSlotWire {
  readonly days: readonly string[];
  readonly start: string;
  readonly end: string;
}

export const OFF_API_SECTION_TITLE = "Thông tin TikTok không cung cấp";
export const OFF_API_SECTION_LEDE =
  "TikTok không trả các thông tin này qua API. Bạn điền thì Juli tính lợi nhuận và đề xuất sát hơn; để trống thì Juli không đoán.";
export const OFF_API_SAMPLE_NOTE = "Bản minh họa: đây là giá trị mẫu. Đăng nhập để đặt các ô này cho shop của bạn.";

/** Label and one-line help per field, in the editor's order. */
export const OFF_API_FIELDS: ReadonlyArray<{ readonly key: OffApiRuleKey; readonly label: string; readonly help: string }> = [
  {
    key: "sku_cost",
    label: "Giá vốn theo SKU",
    help: "Giá vốn của từng biến thể. Ưu tiên hơn giá vốn theo sản phẩm.",
  },
  {
    key: "default_gross_margin_pct",
    label: "Biên lợi nhuận gộp mặc định",
    help: "Dùng cho sản phẩm chưa có giá vốn, để Juli vẫn tính được lợi nhuận.",
  },
  {
    key: "default_max_discount_pct",
    label: "Trần giảm giá tối đa (toàn shop)",
    help: "Juli không đề xuất giảm sâu hơn mức này cho SKU chưa có trần riêng.",
  },
  {
    key: "program_fee_pct",
    label: "Phí tham gia chương trình",
    help: "Voucher Xtra, phí dịch vụ Flash Sale… TikTok chỉ báo phí này sau khi đơn đã quyết toán.",
  },
  {
    key: "joins_platform_campaigns",
    label: "Tham gia chiến dịch sàn",
    help: "TikTok chưa có API cho biết shop đăng ký chiến dịch nào.",
  },
  {
    key: "platform_campaign_note",
    label: "Chiến dịch đang đăng ký",
    help: "Ví dụ: 11.11 — giảm 15 % cho 5 sản phẩm chủ lực.",
  },
  {
    key: "target_roas",
    label: "Mục tiêu ROAS",
    help: "GMV ÷ chi phí quảng cáo bạn muốn đạt với GMV Max.",
  },
  {
    key: "gmv_max_daily_budget",
    label: "Ngân sách GMV Max hằng ngày",
    help: "Juli chưa đọc được tài khoản quảng cáo (chưa có Business API).",
  },
  {
    key: "live_schedule",
    label: "Khung giờ LIVE thường xuyên",
    help: "Mỗi dòng một khung, ví dụ: T2 T4 T6 20:00-22:00 hoặc T7-CN 21:00-23:00.",
  },
];

export const OFF_API_LABELS: Readonly<Record<OffApiRuleKey, string>> = Object.freeze(
  Object.fromEntries(OFF_API_FIELDS.map((field) => [field.key, field.label])) as Record<OffApiRuleKey, string>,
);

/** 422 → the field's own range, in Vietnamese (the backend's text is English). */
export const OFF_API_ERROR_COPY: Readonly<Record<OffApiRuleKey, string>> = Object.freeze({
  sku_cost: "Giá vốn phải là số từ 0 trở lên, kèm mã SKU.",
  default_gross_margin_pct: "Biên lợi nhuận gộp phải lớn hơn 0 và nhỏ hơn 100 %.",
  default_max_discount_pct: "Trần giảm giá phải từ 0 đến 100 %.",
  program_fee_pct: "Phí chương trình phải từ 0 đến dưới 100 %.",
  joins_platform_campaigns: "Chọn Có hoặc Không.",
  platform_campaign_note: "Ghi chú không được để trống và tối đa 500 ký tự.",
  target_roas: "ROAS phải lớn hơn 0 và không quá 100.",
  gmv_max_daily_budget: "Ngân sách phải là số từ 0 trở lên (₫/ngày).",
  live_schedule: "Tối đa 14 khung, mỗi khung gồm ngày (T2…CN) và giờ HH:MM-HH:MM.",
});

export const WEEKDAY_LABELS: Readonly<Record<string, string>> = Object.freeze({
  mon: "T2",
  tue: "T3",
  wed: "T4",
  thu: "T5",
  fri: "T6",
  sat: "T7",
  sun: "CN",
});

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const DAY_BY_LABEL: Readonly<Record<string, string>> = Object.freeze(
  Object.fromEntries(Object.entries(WEEKDAY_LABELS).map(([day, label]) => [label, day])),
);

function isSlot(value: unknown): value is LiveSlotWire {
  if (!value || typeof value !== "object") return false;
  const slot = value as Record<string, unknown>;
  return Array.isArray(slot.days) && typeof slot.start === "string" && typeof slot.end === "string";
}

export function liveSlots(item: RuleValueItem | null | undefined): LiveSlotWire[] {
  return Array.isArray(item?.value) ? (item.value as unknown[]).filter(isSlot) : [];
}

/** `{days:["mon","wed"], start, end}` → `T2 T4 20:00-22:00`. */
export function formatLiveSlot(slot: LiveSlotWire): string {
  return `${slot.days.map((day) => WEEKDAY_LABELS[day] ?? day).join(" ")} ${slot.start}-${slot.end}`;
}

function parseDays(token: string): string[] {
  const range = token.split("-");
  if (range.length === 2) {
    const from = WEEKDAYS.indexOf(DAY_BY_LABEL[range[0]] as (typeof WEEKDAYS)[number]);
    const to = WEEKDAYS.indexOf(DAY_BY_LABEL[range[1]] as (typeof WEEKDAYS)[number]);
    if (from < 0 || to < 0 || to < from) throw new Error(`vi:Không hiểu ngày “${token}”. Dùng T2…T7, CN.`);
    return WEEKDAYS.slice(from, to + 1);
  }
  const day = DAY_BY_LABEL[token];
  if (!day) throw new Error(`vi:Không hiểu ngày “${token}”. Dùng T2…T7, CN.`);
  return [day];
}

const CLOCK = /^([01]?\d|2[0-3]):([0-5]\d)$/;

function clock(text: string, line: string): string {
  const match = CLOCK.exec(text);
  if (!match) throw new Error(`vi:Giờ ở dòng “${line}” phải dạng HH:MM-HH:MM.`);
  return `${match[1].padStart(2, "0")}:${match[2]}`;
}

/** One slot per non-empty line; throws `vi:` messages the editor shows inline. */
export function parseLiveSchedule(text: string): LiveSlotWire[] {
  const slots: LiveSlotWire[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const tokens = line.replace(/[–—]/g, "-").replace(/,/g, " ").toUpperCase().split(/\s+/).filter(Boolean);
    const times = tokens.pop() ?? "";
    const [start, end, extra] = times.split("-");
    if (!start || !end || extra !== undefined) throw new Error(`vi:Giờ ở dòng “${line}” phải dạng HH:MM-HH:MM.`);
    if (tokens.length === 0) throw new Error(`vi:Dòng “${line}” thiếu ngày (T2…CN).`);
    const days = new Set(tokens.flatMap(parseDays));
    slots.push({ days: WEEKDAYS.filter((day) => days.has(day)), start: clock(start, line), end: clock(end, line) });
  }
  return slots;
}

const vnd = new Intl.NumberFormat("vi-VN");

/** The value as the read-only sample shows it ("—" when unset). */
export function displayOffApiValue(key: OffApiRuleKey, rules: ShopRules): string {
  if (key === "sku_cost") {
    const entries = Object.entries(rules.sku_cost ?? {}).filter(([, item]) => item.set_by);
    return entries.length > 0
      ? entries.map(([sku, item]) => `SKU ${sku}: ${vnd.format(Number(item.value))} ₫`).join(" · ")
      : "—";
  }
  const item = rules[key] as RuleValueItem | null | undefined;
  if (!item || !item.set_by || item.value === null || item.value === undefined) return "—";
  switch (key) {
    case "joins_platform_campaigns":
      return item.value === true ? "Có" : "Không";
    case "live_schedule":
      return liveSlots(item).map(formatLiveSlot).join(" · ") || "—";
    case "gmv_max_daily_budget":
      return `${vnd.format(Number(item.value))} ₫/ngày`;
    case "target_roas":
      return `${String(item.value)} lần`;
    case "platform_campaign_note":
      return String(item.value);
    default:
      return `${String(item.value)} %`;
  }
}
