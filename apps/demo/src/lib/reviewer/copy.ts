/**
 * Copy of the partner trial account (fast track P32-A, D42). Mirrors
 * dictionary.md `reviewer.*`; nothing here is authored twice.
 */

/** dictionary.md `reviewer.banner` — the persistent strip on every page. */
export const REVIEWER_BANNER_COPY =
  "Tài khoản dùng thử cho đối tác · dữ liệu shop đã ẩn tên · thao tác chỉ mô phỏng";

/**
 * dictionary.md `reviewer.banner_sample` — the strip when no shop is pinned
 * (P32-D, D42 amendment): the reviewer sees the bundled sample shop.
 */
export const REVIEWER_SAMPLE_BANNER_COPY =
  "Tài khoản dùng thử cho đối tác · dữ liệu mẫu · thao tác chỉ mô phỏng";

/** dictionary.md `reviewer.read_only_title` — tooltip of a write control. */
export const REVIEWER_READ_ONLY_TITLE = "Tài khoản dùng thử: thao tác chỉ mô phỏng";

/** dictionary.md `reviewer.simulated` — the label of every simulated result. */
export const REVIEWER_SIMULATED_LABEL = "Mô phỏng · không gửi tới TikTok";

/** dictionary.md `reviewer.execute` — the simulated execute button. */
export const REVIEWER_EXECUTE_LABEL = "Thực thi (mô phỏng)";

/** dictionary.md `reviewer.expires` — "Hết hạn {date}". */
export function reviewerExpiryCopy(expiresAt: string | null): string | null {
  if (!expiresAt) return null;
  const date = new Date(expiresAt);
  if (Number.isNaN(date.getTime())) return null;
  return `Hết hạn ${date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })}`;
}

/** Platform label shown beside the banner ("Shopee"). */
export function platformLabel(platform: string): string {
  if (!platform) return "";
  return platform.charAt(0).toUpperCase() + platform.slice(1);
}

/**
 * dictionary.md `reviewer.simulated_settings` — P32-E (D42 amendment 2): the
 * label of a simulated settings save (Quy tắc) in the sample shop.
 */
export const REVIEWER_SIMULATED_SETTINGS_LABEL = "Mô phỏng · không lưu";

/** dictionary.md `reviewer.sample_notice` — P32-E: Quyết định's notice in the sample shop. */
export const REVIEWER_SAMPLE_NOTICE =
  "Mọi thao tác ở đây — duyệt, từ chối, sửa nội dung, ảnh, Seller Center, kịch bản, hoàn tác — chạy trong trình duyệt trên dữ liệu mẫu.";

/** dictionary.md `reviewer.reset` — P32-E: start the sample shop over. */
export const REVIEWER_RESET_LABEL = "Đặt lại dữ liệu mẫu";

/** dictionary.md `reviewer.continue_run` — P32-E: from the simulated Thực thi to the sample run. */
export const REVIEWER_CONTINUE_LABEL = "Theo dõi lượt chạy (mô phỏng) ›";

/** dictionary.md `reviewer.fast_forward` — P32-E: Đo lường's day-7 / day-14 preview. */
export const REVIEWER_FAST_FORWARD_COPY = "Xem trước kết quả đo trên lượt chạy mô phỏng:";

/** dictionary.md `reviewer.video_simulated` — P32-E: the canned "Phân tích video". */
export const REVIEWER_VIDEO_SIMULATED_NOTE =
  "Tệp không được tải lên — Juli hiển thị một phân tích mẫu, tệp không rời trình duyệt.";
