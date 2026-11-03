// Popup wording for the backfill and a refused shop (pure, unit-tested). The
// seller's on-screen vocabulary only (D31.8): no endpoint or backend terms.

import type { Backfill, ReaderSchedule } from "../background/state";

export const CONSENT_REQUIRED_MESSAGE =
  "Shop này chưa được cấp quyền đồng bộ dữ liệu với Juli, nên tiện ích đã tạm dừng gửi số liệu. " +
  "Liên hệ Juli để bật quyền, rồi bấm “Đồng bộ hôm qua”.";

/** One line about the 30-day backfill, or null before it starts. */
export function backfillLabel(backfill: Backfill | null | undefined): string | null {
  if (!backfill) return null;
  const total = backfill.days.length;
  const done = backfill.done.length;
  if (backfill.status === "done") return `Đã lấy đủ số liệu ${total} ngày trước`;
  if (backfill.status === "stopped") {
    switch (backfill.stop?.reason) {
      case "session":
        return `Tạm dừng lấy số liệu ${total} ngày trước (${done}/${total} ngày): đăng nhập lại Seller Centre để tiếp tục`;
      case "consent_required":
        return `Tạm dừng lấy số liệu ${total} ngày trước (${done}/${total} ngày): shop chưa được cấp quyền đồng bộ`;
      case "unpaired":
        return `Tạm dừng lấy số liệu ${total} ngày trước (${done}/${total} ngày): kết nối lại với Juli để tiếp tục`;
      default:
        return `Tạm dừng lấy số liệu ${total} ngày trước (${done}/${total} ngày): Seller Centre đã thay đổi`;
    }
  }
  if (backfill.needsDataPage) {
    return `Đang lấy số liệu ${total} ngày trước: ${done}/${total} ngày · mở mục Dữ liệu trong Seller Centre để tiếp tục`;
  }
  return `Đang lấy số liệu ${total} ngày trước: ${done}/${total} ngày · cần mở Seller Centre`;
}

/**
 * One line about the scheduled reading of the report pages (sản phẩm, quảng cáo, voucher, sức khỏe
 * shop), or null before the first run. A stop says what the seller has to do.
 */
export function readersLabel(readers: ReaderSchedule | null | undefined, nowMs: number = Date.now()): string | null {
  if (!readers) return null;
  if (readers.blocked && readers.blocked.until > nowMs) {
    return readers.blocked.reason === "captcha"
      ? "Tạm dừng đọc các trang báo cáo: Seller Centre yêu cầu xác minh (CAPTCHA). Mở Seller Centre, xác minh, rồi bấm “Đồng bộ hôm qua”."
      : "Tạm dừng đọc các trang báo cáo: đăng nhập lại Seller Centre để tiếp tục.";
  }
  if (readers.run) return "Đang đọc các trang báo cáo của Seller Centre trong một tab nền…";
  if (readers.lastRun) return `Đọc các trang báo cáo gần nhất: ${readers.lastRun.day}`;
  return null;
}
