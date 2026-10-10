import type { AuditEntry } from "../../lib/ops/types";

/** One audit row as a sentence (artboard "Nhật ký"). */
export function auditWho(entry: AuditEntry): string {
  if (entry.actor_email === "system") return "hệ thống";
  return entry.actor_email.split("@")[0];
}

export function auditWhat(entry: AuditEntry): string {
  const after = (entry.after ?? {}) as Record<string, unknown>;
  switch (entry.action) {
    case "settings_update": {
      const keys = Object.keys(after).filter(
        (k) => JSON.stringify(after[k]) !== JSON.stringify(((entry.before ?? {}) as Record<string, unknown>)[k]),
      );
      if (keys.includes("openai_monthly_cap_usd") && after.openai_monthly_cap_usd !== null)
        return `đặt trần chi phí OpenAI $${String(after.openai_monthly_cap_usd)}/tháng`;
      if (keys.includes("stage")) return `chuyển giai đoạn: ${STAGE_VI[String(after.stage)] ?? String(after.stage)}`;
      if (keys.includes("card_daily_limit") && after.card_daily_limit !== null)
        return `đổi giới hạn thẻ: ${String(after.card_daily_limit)} thẻ mới/ngày`;
      return `đổi cài đặt: ${keys.join(", ") || "—"}`;
    }
    case "settings_reset":
      return "đưa cài đặt riêng về mặc định";
    case "view_as_view":
      return "mở Xem như shop";
    case "shop_disconnect":
      return `huỷ kết nối shop: ${String(after.reason ?? "")}`;
    case "view_as_exit":
      return "thoát Xem như shop";
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
    case "staff_upsert":
      return `cập nhật nhân viên ${String(after.email ?? "")}`;
    default:
      return entry.action;
  }
}

const STAGE_VI: Record<string, string> = { trial: "Thử nghiệm", self: "Tự vận hành", pilot: "Pilot đặc biệt" };

export function auditWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const v = new Date(d.getTime() + 7 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(v.getUTCDate())}/${p(v.getUTCMonth() + 1)} ${p(v.getUTCHours())}:${p(v.getUTCMinutes())}`;
}
