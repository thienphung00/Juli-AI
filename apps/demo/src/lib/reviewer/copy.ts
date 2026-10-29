/**
 * Copy of the partner trial account (fast track P32-A, D42). Mirrors
 * dictionary.md `reviewer.*`; nothing here is authored twice.
 */

/** dictionary.md `reviewer.banner` — the persistent strip on every page. */
export const REVIEWER_BANNER_COPY =
  "Tài khoản đối tác · dữ liệu shop thật đã ẩn tên · chỉ xem, duyệt chỉ mô phỏng";

/**
 * dictionary.md `reviewer.banner_sample` — the strip when no shop is pinned
 * (P32-D, D42 amendment): the reviewer sees the bundled sample shop.
 */
export const REVIEWER_SAMPLE_BANNER_COPY =
  "Tài khoản đối tác · thao tác chỉ mô phỏng";

/** dictionary.md `reviewer.read_only_title` — tooltip of a write control. */
export const REVIEWER_READ_ONLY_TITLE = "Tài khoản đối tác: thao tác chỉ mô phỏng";

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

/**
 * dictionary.md `reviewer.sample_notice` — P32-E: Quyết định's notice in the
 * sample shop, after `reviewer.simulated` ("Mô phỏng · không gửi tới TikTok ·
 * không thay đổi dữ liệu thật"). P41 (D47.7): short, one line.
 */
export const REVIEWER_SAMPLE_NOTICE = "không thay đổi dữ liệu thật";

/** dictionary.md `reviewer.reset` — P32-E: start the sample shop over. */
export const REVIEWER_RESET_LABEL = "Đặt lại mô phỏng";

/** dictionary.md `reviewer.continue_run` — P32-E: from the simulated Thực thi to the sample run. */
export const REVIEWER_CONTINUE_LABEL = "Theo dõi lượt chạy (mô phỏng) ›";

/** dictionary.md `reviewer.fast_forward` — P32-E: Đo lường's day-7 / day-14 preview. */
export const REVIEWER_FAST_FORWARD_COPY = "Xem trước kết quả đo:";

/** dictionary.md `reviewer.video_simulated` — P32-E: the canned "Phân tích video". */
export const REVIEWER_VIDEO_SIMULATED_NOTE = "tệp không được tải lên, đây là phân tích mô phỏng";

/** dictionary.md `reviewer.simulated_settings_note` — P41 (D47.7): after "Mô phỏng · không lưu" on Quy tắc. */
export const REVIEWER_SIMULATED_SETTINGS_NOTE = "chỉ giữ trong phiên này";

/**
 * dictionary.md `reviewer.simulation_note` — P41 (D47.7): the one line under the
 * simulated Thực thi, per executor (mirrors the backend's
 * `services/reviewer/simulation.py` `_NOTES`). No endpoint, no method name: the
 * dialog's label is the single "simulation" disclaimer.
 */
export const REVIEWER_SIMULATION_NOTES: Readonly<Record<string, string>> = {
  juli: "Với shop thật, Juli ghi thay đổi này lên TikTok Shop sau khi bạn xác nhận, rồi đo ở ngày 7 và 14.",
  juli_with_photo: "Với shop thật, Juli đổi ảnh bìa trên TikTok Shop sau khi bạn gửi ảnh và xác nhận, rồi đo ở ngày 7 và 14.",
  juli_drafts: "Với shop thật, Juli soạn kịch bản, bạn quay và đăng; Juli không ghi gì lên TikTok, chỉ đo ở ngày 7 và 14.",
  seller_center: "Bạn tự áp dụng trên Seller Center; Juli không ghi gì lên TikTok, chỉ đo ở ngày 7 và 14.",
};

/**
 * P64 (D73): the strip when the reviewer is pinned to Juli's live TikTok
 * sandbox shop — real data, real writes (no sample, no simulation).
 */
export const REVIEWER_SANDBOX_BANNER_COPY = "shop sandbox TikTok";

/** "Tài khoản đối tác Shopee · shop sandbox TikTok · hết hạn 25/11/2026". */
export function sandboxBannerText(platform: string, expiry: string | null): string {
  const head = platform ? `Tài khoản đối tác ${platform}` : "Tài khoản đối tác";
  const tail = expiry ? ` · ${expiry.charAt(0).toLowerCase()}${expiry.slice(1)}` : "";
  return `${head} · ${REVIEWER_SANDBOX_BANNER_COPY}${tail}`;
}

/** P64: tooltip of a control that stays read-only in the sandbox account. */
export const REVIEWER_SANDBOX_READ_ONLY_TITLE = "Tài khoản đối tác: mục này chỉ để xem";

export const SANDBOX_CONNECTION_TITLE = "Kết nối TikTok Shop";
export const SANDBOX_CONNECTED_LABEL = "Đã kết nối";
export const SANDBOX_NEEDS_REAUTH_LABEL = "Cần ủy quyền lại";

export const SANDBOX_SYNC_LABEL = "Đồng bộ ngay";
export const SANDBOX_SYNCING = "Đang đồng bộ…";
export const SANDBOX_SYNC_UNAVAILABLE = "Chưa xếp lịch đồng bộ được. Vui lòng thử lại sau.";
export const SANDBOX_SYNC_ERROR = "Chưa đồng bộ được. Vui lòng thử lại.";
export const SANDBOX_LOAD_ERROR = "Chưa tải được trạng thái kết nối TikTok.";

/** P64: no traffic in the sandbox (D73): orders and products are still live. */
export const SANDBOX_NO_TRAFFIC_COPY =
  "TikTok sandbox chưa có lượt xem/traffic — số liệu đơn hàng và sản phẩm vẫn lấy trực tiếp từ TikTok";
