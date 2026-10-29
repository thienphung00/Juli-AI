/**
 * The demo's sign-in screen (P34-F, D44.5, `fasttrack/design/p34/Auth.dc.html`).
 * Every seller-facing string of the plain sign-in variant, the OTP view, the
 * partner view, the right-hand panel and the footer lives here, and in
 * `dictionary.md` (`auth.screen.*`). The trial variant's strings are in
 * `trial-signup-copy.ts`; GoTrue's errors in `supabase-auth.ts`
 * (`EMAIL_OTP_ERROR_COPY`, `PASSWORD_SIGN_IN_ERROR_COPY`).
 */

export const AUTH_HEADING = "Đăng nhập vào Juli";
export const AUTH_SUB = "Chưa có tài khoản? Juli tự tạo cho bạn ở bước này.";
export const AUTH_GOOGLE_LABEL = "Tiếp tục với Google";
export const AUTH_DIVIDER = "hoặc dùng email";
export const AUTH_EMAIL_LABEL = "Email";
export const AUTH_EMAIL_PLACEHOLDER = "ten@shopcuaban.vn";
export const AUTH_EMAIL_SEND_LABEL = "Gửi mã đăng nhập";
export const AUTH_EMAIL_SENDING = "Đang gửi mã…";
export const authEmailCooldownLabel = (seconds: number) => `Gửi mã sau ${seconds} giây`;

/** The sample-demo door: a link-styled button, enters the sample demo in place. */
export const AUTH_SAMPLE_ENTRY = "Xem thử với dữ liệu mẫu, không cần tài khoản →";
export const AUTH_SWITCH_TEXT = "Mới dùng Juli?";
export const AUTH_SWITCH_LINK = "Dùng thử miễn phí 3 tháng";

/* OTP view ---------------------------------------------------------------- */
export const AUTH_OTP_HEADING = "Nhập mã 6 chữ số";
export const AUTH_OTP_LEGEND = "Mã đăng nhập";
export const AUTH_OTP_CONFIRM = "Xác nhận";
export const AUTH_OTP_CONFIRMING = "Đang xác nhận…";
export const AUTH_OTP_INCOMPLETE = "Nhập đủ 6 chữ số trong email.";
export const AUTH_OTP_CHANGE_EMAIL = "← Đổi email";
export const AUTH_OTP_RESEND = "Gửi lại mã";
export const authOtpResendCountdown = (seconds: number) => `Gửi lại mã sau ${seconds} giây`;
export const AUTH_OTP_NEW_CODE = "Gửi mã mới";
export const AUTH_OTP_SIGNED_IN = "Đăng nhập thành công. Đang chuyển tới Kết nối TikTok Shop…";
export const authOtpDigitLabel = (index: number) => `Số ${index + 1}`;

/** "Juli đã gửi mã tới {masked}. …" — the address is masked, the code never shown. */
export const AUTH_OTP_SENT_PREFIX = "Juli đã gửi mã tới";
export const AUTH_OTP_SENT_SUFFIX = ". Nhập mã bên dưới, hoặc bấm nút đăng nhập trong email.";

/* Partner view ------------------------------------------------------------ */
export const AUTH_PARTNER_LINK = "Tài khoản đối tác";
/**
 * The partner entry at the TOP of the sign-in column (D47.6, amends D44.5): a
 * quiet pill above the heading, so a partner reviewer (Shopee ISV) finds it
 * without scrolling. One link; its accessible name is lead + action.
 */
export const AUTH_PARTNER_TOP_LEAD = "Đối tác thẩm định?";
export const AUTH_PARTNER_TOP_ACTION = "Đăng nhập bằng tài khoản đối tác";
export const AUTH_PARTNER_EYEBROW = "Tài khoản đối tác";
export const AUTH_PARTNER_HEADING = "Đăng nhập bằng mật khẩu";
export const AUTH_PARTNER_SUB =
  "Dành cho đối tác và đơn vị thẩm định được Juli cấp tài khoản. Người bán đăng nhập bằng Google hoặc email.";
export const AUTH_PARTNER_BACK = "← Quay lại đăng nhập cho người bán";
/** Where the top and footer links go when the partner form is not on this page (`/`). */
export const AUTH_PARTNER_HREF = "/auth/email#doi-tac";

/* Right-hand panel (desktop) ---------------------------------------------- */
export const AUTH_PANEL_LABEL = "Juli làm gì";
export const AUTH_PANEL_EYEBROW = "Sau khi kết nối TikTok Shop";
export const AUTH_PANEL_HEADLINE =
  "Juli chỉ ra luồng và sản phẩm đang kéo GMV xuống, kèm một thay đổi cụ thể để bạn duyệt.";
export const AUTH_PANEL_IMAGE_ALT = "Thẻ đề xuất của Juli: Mặt nạ đất sét 100g, CTOR 5,4 % lên 5,9 %";
export const AUTH_PANEL_CAPTION = "Ví dụ thẻ đề xuất";
export const AUTH_PANEL_PROOF = [
  "Kết nối chính thức qua TikTok Shop Open API",
  "Chỉ thực hiện khi bạn duyệt",
  "Miễn phí 3 tháng",
] as const;

/* Footer ------------------------------------------------------------------ */
export const AUTH_FOOTER_TERMS = "Điều khoản";
export const AUTH_FOOTER_PRIVACY = "Chính sách bảo mật";
export const AUTH_FOOTER_COPYRIGHT = "© 2026 Công ty TNHH Công Nghệ Juli AI";
export const AUTH_HOME_URL = "https://app-juli.com";
export const AUTH_LOGO_LABEL = "Juli AI, về trang chủ app-juli.com";

/**
 * "chushop@vi-du.vn" → "ch***@vi-du.vn" (the OTP view names the address the
 * code went to without printing all of it on screen). A local part of one or
 * two characters keeps only its first.
 */
export function maskEmail(email: string): string {
  const at = email.lastIndexOf("@");
  if (at <= 0) return email;
  const local = email.slice(0, at);
  const keep = local.length > 2 ? 2 : 1;
  return `${local.slice(0, keep)}***${email.slice(at)}`;
}
