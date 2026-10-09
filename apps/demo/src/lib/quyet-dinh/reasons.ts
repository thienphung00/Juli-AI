/**
 * The three reason lists (ADR-109 Amendment 1 d.7; contract §2) — labels
 * character for character from `Decline.dc.html` / `Revert.dc.html`, codes
 * from the contract table, in the artboards' order. Exactly one is required.
 */

export interface ReasonOption {
  readonly code: string;
  readonly label: string;
}

/** Từ chối a card (Đề xuất) → `POST /decisions/{id}/reject`. */
export const REJECT_REASONS: readonly ReasonOption[] = [
  { code: "brand_mismatch", label: "Thay đổi không hợp thương hiệu hoặc giọng văn" },
  { code: "not_convincing", label: "Lý do hoặc số liệu chưa thuyết phục" },
  { code: "editing_myself", label: "Tôi đang tự sửa sản phẩm này" },
  { code: "discontinued", label: "Sản phẩm sắp ngừng bán hoặc hết hàng" },
  { code: "other_campaign", label: "Đang chạy chiến dịch khác cho sản phẩm này" },
  { code: "other", label: "Khác" },
];

/** Không thực hiện at the consent step → `POST /runs/{id}/decline`. */
export const DECLINE_REASONS: readonly ReasonOption[] = [
  { code: "wrong_info", label: "Nội dung sai thông tin sản phẩm" },
  { code: "tone", label: "Văn phong chưa phù hợp" },
  { code: "too_much_change", label: "Thay đổi quá nhiều so với hiện tại" },
  { code: "changed_mind", label: "Đổi ý, chưa muốn thay đổi lúc này" },
  { code: "other", label: "Khác" },
];

/** Hoàn tác → `POST /runs/{id}/revert` with `{reason_code, note?}`. */
export const REVERT_REASONS: readonly ReasonOption[] = [
  { code: "metrics_dropped", label: "Doanh số hoặc chỉ số giảm" },
  { code: "bad_feedback", label: "Khách phản hồi không tốt" },
  { code: "wrong_info", label: "Nội dung sai thông tin sản phẩm" },
  { code: "off_brand", label: "Không hợp giọng thương hiệu" },
  { code: "tiktok_warning", label: "TikTok cảnh báo sản phẩm" },
  { code: "other", label: "Khác" },
];

/** Note limit (contract §2). */
export const REASON_NOTE_MAX = 300;

export interface ReasonChoice {
  readonly reason_code: string;
  readonly note?: string;
}
