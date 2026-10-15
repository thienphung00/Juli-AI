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
