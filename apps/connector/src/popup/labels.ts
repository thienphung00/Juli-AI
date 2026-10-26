// Popup wording for the backfill and a refused shop (pure, unit-tested). The
// seller's on-screen vocabulary only (D31.8): no endpoint or backend terms.

import type { Backfill } from "../background/state";

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
