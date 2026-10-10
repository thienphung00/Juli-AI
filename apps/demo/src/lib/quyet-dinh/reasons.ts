/**
 * The three reason lists (ADR-109 Amendment 1 d.7; contract §2) — labels
 * character for character from `Decline.dc.html` / `Revert.dc.html`, codes
 * from the contract table, in the artboards' order. Exactly one is required.
 */

export interface ReasonOption {
  readonly code: string;
  readonly label: string;
  /** "Lý do giúp Juli đưa ra đề xuất tốt hơn: …" in the completion message (`reasonLearn`, a0382006). */
  readonly learn: string;
}

/** Từ chối a card (Đề xuất) → `POST /decisions/{id}/reject`. */
export const REJECT_REASONS: readonly ReasonOption[] = [
  { code: "brand_mismatch", label: "Thay đổi không hợp thương hiệu hoặc giọng văn", learn: "Juli bám sát giọng văn và từ cấm trong Quy tắc của bạn." },
  { code: "not_convincing", label: "Lý do hoặc số liệu chưa thuyết phục", learn: "Juli chỉ đề xuất khi số liệu đủ rõ và giải thích kỹ hơn." },
  { code: "editing_myself", label: "Tôi đang tự sửa sản phẩm này", learn: "Juli chờ thay đổi của bạn có kết quả rồi mới đề xuất lại." },
  { code: "discontinued", label: "Sản phẩm sắp ngừng bán hoặc hết hàng", learn: "Juli bỏ qua sản phẩm này ở các đề xuất sau." },
  { code: "other_campaign", label: "Đang chạy chiến dịch khác cho sản phẩm này", learn: "Juli chờ chiến dịch kết thúc để không lẫn kết quả." },
  { code: "other", label: "Khác", learn: "Juli ghi lại ghi chú của bạn để xem xét ở đề xuất sau." },
];

/** Không thực hiện at the consent step → `POST /runs/{id}/decline`. */
export const DECLINE_REASONS: readonly ReasonOption[] = [
  { code: "wrong_info", label: "Nội dung sai thông tin sản phẩm", learn: "Juli kiểm kỹ thông tin sản phẩm trước khi soạn." },
  { code: "tone", label: "Văn phong chưa phù hợp", learn: "Juli soạn theo văn phong gần với nội dung hiện tại của bạn hơn." },
  { code: "too_much_change", label: "Thay đổi quá nhiều so với hiện tại", learn: "Juli đề xuất thay đổi nhỏ hơn, giữ phần bạn đã viết." },
  { code: "changed_mind", label: "Đổi ý, chưa muốn thay đổi lúc này", learn: "Juli đề xuất lại sau 7 ngày với số liệu mới." },
  { code: "other", label: "Khác", learn: "Juli ghi lại ghi chú của bạn để xem xét ở đề xuất sau." },
];

/** Hoàn tác → `POST /runs/{id}/revert` with `{reason_code, note?}`. */
export const REVERT_REASONS: readonly ReasonOption[] = [
  { code: "metrics_dropped", label: "Doanh số hoặc chỉ số giảm", learn: "lần sau Juli đặt mức kỳ vọng thận trọng hơn cho loại thay đổi này." },
  { code: "bad_feedback", label: "Khách phản hồi không tốt", learn: "Juli đọc thêm đánh giá và tin nhắn của khách trước khi soạn." },
  { code: "wrong_info", label: "Nội dung sai thông tin sản phẩm", learn: "Juli kiểm kỹ thông tin sản phẩm trước khi soạn." },
  { code: "off_brand", label: "Không hợp giọng thương hiệu", learn: "Juli bám sát giọng văn và từ cấm trong Quy tắc của bạn." },
  { code: "tiktok_warning", label: "TikTok cảnh báo sản phẩm", learn: "Juli kiểm tra chính sách TikTok kỹ hơn trước khi đề xuất." },
  { code: "other", label: "Khác", learn: "Juli ghi lại ghi chú của bạn để xem xét ở đề xuất sau." },
];

/** Note limit (contract §2). */
export const REASON_NOTE_MAX = 300;

export interface ReasonChoice {
  readonly reason_code: string;
  readonly note?: string;
}

/** The option a stored code (or an already-mapped label) stands for; "Khác" when unknown. */
export function reasonOption(list: readonly ReasonOption[], codeOrLabel: string | null | undefined): ReasonOption {
  const other = list.find((r) => r.code === "other") as ReasonOption;
  if (!codeOrLabel) return other;
  return list.find((r) => r.code === codeOrLabel || r.label === codeOrLabel) ?? other;
}
