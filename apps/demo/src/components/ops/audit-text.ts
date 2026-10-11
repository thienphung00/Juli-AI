import { describeSettingsAudit } from "../../lib/ops/setting-changes";
import type { AuditEntry } from "../../lib/ops/types";
import { RULE_LABELS } from "../../lib/quyet-dinh/copy";

function ruleLabel(key: unknown): string {
  return RULE_LABELS[String(key)] ?? String(key ?? "—");
}

/** One audit row as a sentence (artboard "Nhật ký"). */
export function auditWho(entry: AuditEntry): string {
  if (entry.actor_email === "system") return "hệ thống";
  return entry.actor_email.split("@")[0];
}

export function auditWhat(entry: AuditEntry): string {
  const after = (entry.after ?? {}) as Record<string, unknown>;
  switch (entry.action) {
    case "settings_update":
      return describeSettingsAudit(entry.before, entry.after);
    case "settings_reset":
      return "Đưa cài đặt riêng về mặc định";
    case "view_as_view":
      return "Xem như shop";
    case "shop_disconnect":
      return `Huỷ kết nối · lý do: ${String(after.reason ?? "")}`;
    case "view_as_exit":
      return "Thoát Xem như shop";
    case "invite_create":
      return `mời seller ${String(after.email ?? "")}`;
    case "invite_accept":
      return "seller nhận shop";
    case "scenario_create":
      return "lưu kịch bản mô phỏng";
    case "scenario_set_target":
      return "đặt kịch bản làm mục tiêu shop";
    case "scenario_update":
      return "sửa kịch bản mô phỏng";
    case "scenario_delete":
      return "xoá kịch bản mô phỏng";
    case "rule_set":
      return `Quy tắc · ${ruleLabel(after.rule_key ?? (entry.before as Record<string, unknown> | null)?.rule_key)}: đặt giá trị mới`;
    case "rule_unset":
      return `Quy tắc · ${ruleLabel((entry.before as Record<string, unknown> | null)?.rule_key)}: về mặc định`;
    case "staff_upsert":
      return `cập nhật nhân viên ${String(after.email ?? "")}`;
    default:
      return entry.action;
  }
}

export function auditWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const v = new Date(d.getTime() + 7 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(v.getUTCDate())}/${p(v.getUTCMonth() + 1)} ${p(v.getUTCHours())}:${p(v.getUTCMinutes())}`;
}
