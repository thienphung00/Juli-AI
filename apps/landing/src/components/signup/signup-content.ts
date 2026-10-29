/**
 * `/dang-ky` — the free 3-month trial sign-up (P33-F, D43). Copy and constants
 * in one place so the page, the form, the thank-you page and the tests agree.
 */

export const SIGNUP_PATH = "/dang-ky";
export const SIGNUP_THANKS_PATH = "/dang-ky/cam-on";
/** The landing's own server route the form posts to (proxies to the Juli API). */
export const SIGNUP_SUBMIT_PATH = "/dang-ky/gui";

/**
 * "Tự kết nối shop ngay" on the thank-you page: the demo app opened as a trial
 * sign-up (P33-B's door reads `?dang-ky=dung-thu`). Overridable per environment.
 */
export const SELF_CONNECT_URL =
  process.env.NEXT_PUBLIC_SIGNUP_SELF_CONNECT_URL ?? "https://app.app-juli.com/?dang-ky=dung-thu";

export const SIGNUP_EYEBROW = "Miễn phí 3 tháng · không cần thẻ thanh toán";
export const SIGNUP_H1 = "Đăng ký dùng thử Juli";

export const SIGNUP_LEAD =
  "Để lại thông tin, đội ngũ Juli sẽ liên hệ qua điện thoại hoặc Zalo và cùng bạn kết nối TikTok Shop.";

/** "Muốn tự kết nối ngay?" under the form → the demo's trial door ({@link SELF_CONNECT_URL}). */
export const SELF_CONNECT_PROMPT = "Muốn tự kết nối ngay?";
export const SELF_CONNECT_LINK_LABEL = "Tạo tài khoản và kết nối shop →";

/** "Sau khi bạn đăng ký" (Signup.dc.html) — also the thank-you page's next steps. */
export const NEXT_STEPS: readonly { title: string; body: string }[] = [
  {
    title: "Juli gọi hoặc nhắn Zalo cho bạn",
    body: "Trong giờ làm việc, để hiểu shop và cách bạn vận hành.",
  },
  {
    title: "Cùng kết nối TikTok Shop",
    body: "Uỷ quyền chính thức qua TikTok, không cần mật khẩu shop.",
  },
  {
    title: "Nhận đề xuất đầu tiên",
    body: "Juli quét nhanh shop và gửi những thẻ đề xuất đầu tiên để bạn duyệt.",
  },
];

/** Field names: identical to the API body (`POST /v1/trial-signups`). */
export const FIELDS = {
  fullName: "full_name",
  phone: "phone",
  email: "email",
  shop: "shop",
  role: "role",
  note: "note",
  consent: "consent",
  honeypot: "website",
} as const;

export const ROLE_OPTIONS: readonly { value: string; label: string }[] = [
  { value: "seller", label: "Nhà bán" },
  { value: "affiliate", label: "Affiliate" },
  { value: "shop_operator", label: "Đội vận hành sàn" },
  { value: "agency", label: "Agency" },
];

export const LABELS = {
  fullName: "Họ và tên",
  phone: "Số điện thoại / Zalo",
  phoneHint: "Số di động Việt Nam, ví dụ 0912 345 678.",
  email: "Email",
  shop: "Tên hoặc link shop TikTok",
  shopHint: "Ví dụ: tiktok.com/@tenshop hoặc tên shop của bạn.",
  role: "Bạn là",
  note: "Ghi chú (không bắt buộc)",
  noteHint: "Ngành hàng, số đơn mỗi ngày, điều bạn muốn Juli giúp…",
  submit: "Đăng ký dùng thử",
  submitting: "Đang gửi…",
} as const;

/** Server answers the form shows (also the no-JS `#anchor` notices on /dang-ky). */
export const NOTICES = {
  invalid: {
    id: "loi-du-lieu",
    text: "Thông tin chưa đúng. Vui lòng kiểm tra lại các ô được đánh dấu rồi gửi lại.",
  },
  rateLimited: {
    id: "loi-gioi-han",
    text: "Bạn đã gửi đăng ký nhiều lần. Đội ngũ Juli đã nhận thông tin và sẽ liên hệ với bạn, hoặc bạn có thể gửi email tới lienhe@app-juli.com.",
  },
  failed: {
    id: "loi-he-thong",
    text: "Chưa gửi được đăng ký, vui lòng thử lại sau ít phút hoặc email lienhe@app-juli.com.",
  },
} as const;

export const THANKS_H1 = "Cảm ơn bạn đã đăng ký dùng thử Juli";
export const SELF_CONNECT_LABEL = "Tự kết nối shop ngay";

/** sessionStorage flag: set by the form on success, read once by the thank-you page. */
export const SIGNUP_DONE_FLAG = "juli-trial-signup-done";
