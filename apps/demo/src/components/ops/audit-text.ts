import { fmtDate, fmtUsd } from "../../lib/ops/format";
import { describeSettingsAudit } from "../../lib/ops/setting-changes";
import type { AuditEntry, AuditKind } from "../../lib/ops/types";
import { RULE_LABELS } from "../../lib/quyet-dinh/copy";

type Obj = Record<string, unknown>;

function obj(value: unknown): Obj {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Obj) : {};
}

function ruleLabel(key: unknown): string {
  return RULE_LABELS[String(key)] ?? String(key ?? "—");
}

function num(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function capText(value: unknown): string {
  const n = num(value);
  return n === null ? "mặc định" : `${fmtUsd(n)} / tháng`;
}

const SOURCE_LABELS: Readonly<Record<string, string>> = { contract: "hợp đồng", payment: "thanh toán" };
const ROLE_LABELS: Readonly<Record<string, string>> = { viewer: "Xem", operator: "Vận hành", admin: "Admin" };

/** One audit row as a sentence (artboard "Nhật ký"). */
export function auditWho(entry: AuditEntry): string {
  if (entry.actor_email === "system") return "hệ thống";
  return entry.actor_email.split("@")[0];
}

/** `subscription_period_added`: "Gia hạn gói 30 ngày · 12/10/2026 → 10/11/2026 · theo hợp đồng HĐ-12". */
function periodText(after: Obj): string {
  const period = obj(after.period);
  const days = num(period.days);
  const range = period.starts_on && period.ends_on ? ` · ${fmtDate(String(period.starts_on))} → ${fmtDate(String(period.ends_on))}` : "";
  const source = SOURCE_LABELS[String(period.source)];
  const ref = period.reference ? ` ${String(period.reference)}` : "";
  return `Gia hạn ${days ? `gói ${days} ngày` : "thời hạn"}${range}${source ? ` · theo ${source}${ref}` : ""}`;
}

/**
 * Every action the backend writes (`audit.record(...)` under
 * `backend/src/juli_backend`): settings_update, settings_reset,
 * openai_shop_cap_set, openai_system_cap_set, system_openai_alert_sent,
 * view_as_view, view_as_exit, data_refresh, shop_disconnect, invite_create,
 * invite_accept, scenario_*, rule_set, rule_unset, staff_upsert,
 * subscription_period_added. An unknown action still reads as a sentence.
 */
export function auditWhat(entry: AuditEntry): string {
  const after = obj(entry.after);
  const before = obj(entry.before);
  switch (entry.action) {
    case "settings_update":
      return describeSettingsAudit(entry.before, entry.after);
    case "settings_reset":
      return "Đưa cài đặt riêng về mặc định";
    case "openai_shop_cap_set":
      return `Trần OpenAI của shop: ${capText(before.openai_monthly_cap_usd)} → ${capText(after.openai_monthly_cap_usd)}`;
    case "openai_system_cap_set":
      return `Trần OpenAI toàn hệ thống: ${capText(before.openai_system_cap_usd)} → ${capText(after.openai_system_cap_usd)}`;
    case "system_openai_alert_sent": {
      const level = num(after.level);
      return `Gửi email cảnh báo chi phí OpenAI${level ? ` · đã dùng ${level} % trần tháng${after.month ? ` ${String(after.month)}` : ""}` : ""}`;
    }
    case "view_as_view":
      return "Xem như shop";
    case "view_as_exit":
      return "Thoát Xem như shop";
    case "data_refresh":
      return after.target === "simulation"
        ? `Làm mới số liệu Mô phỏng${num(after.window) ? ` (${num(after.window)} ngày)` : ""}`
        : "Làm mới số liệu Tổng quan";
    case "shop_disconnect":
      return `Huỷ kết nối · lý do: ${String(after.reason ?? "")}`;
    case "invite_create":
      return `Mời seller ${String(after.email ?? "")}`;
    case "invite_accept":
      return "Seller nhận shop";
    case "scenario_create":
      return "Lưu kịch bản mô phỏng";
    case "scenario_set_target":
      return "Đặt kịch bản làm mục tiêu shop";
    case "scenario_update":
      return "Sửa kịch bản mô phỏng";
    case "scenario_delete":
      return "Xoá kịch bản mô phỏng";
    case "rule_set":
      return `Quy tắc · ${ruleLabel(after.rule_key ?? before.rule_key)}: đặt giá trị mới`;
    case "rule_unset":
      return `Quy tắc · ${ruleLabel(before.rule_key)}: về mặc định`;
    case "staff_upsert": {
      const role = ROLE_LABELS[String(after.role)];
      const off = after.active === false ? " · tắt quyền" : "";
      return `Cập nhật nhân viên ${String(after.email ?? "")}${role ? ` · ${role}` : ""}${off}`;
    }
    case "subscription_period_added":
      return periodText(after);
    default:
      return `Thao tác khác (${entry.action})`;
  }
}

/**
 * The row's group in the Nhật ký filter: "Xem như shop" = the view-as session
 * rows; "Hệ thống" = jobs (`system_*`, actor "system") and "Làm mới số liệu"
 * (`data_refresh`, which the backend files under its `view` kind); everything
 * else "Cấu hình". Read off the action first, so a refresh never shows under
 * "Xem như shop"; an action not known here keeps the backend's `kind`.
 */
export function auditKind(entry: AuditEntry): AuditKind {
  if (entry.action.startsWith("view_as_")) return "view";
  if (entry.action.startsWith("system_") || entry.action === "data_refresh" || entry.actor_email === "system") return "system";
  return entry.kind ?? "config";
}

/** Which backend `kind` queries hold a UI group's rows (the backend files data_refresh under `view`). */
export function auditQueryKinds(filter: AuditKind | "all"): readonly (AuditKind | null)[] {
  if (filter === "all") return [null];
  if (filter === "system") return ["system", "view"];
  return [filter];
}

export function auditWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const v = new Date(d.getTime() + 7 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(v.getUTCDate())}/${p(v.getUTCMonth() + 1)} ${p(v.getUTCHours())}:${p(v.getUTCMinutes())}`;
}
