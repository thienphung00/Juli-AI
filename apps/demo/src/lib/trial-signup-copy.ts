/**
 * Trial sign-up door (D43 additions, owner 2026-10-15): the self-connect path.
 * app-juli.com's trial form (`/dang-ky`, P33-F) ends on a thank-you page whose
 * "Tự kết nối shop ngay" button opens `/?dang-ky=dung-thu`; the auth screen
 * then reads as a trial sign-up. Since P34-F (D44.5) it is the same layout as
 * sign-in, copy only, and the same Google / email-code flows: an existing
 * seller still signs in with them. Copy lives in `dictionary.md`
 * (`auth.trial_signup.*`). "Không cần thẻ thanh toán" is true: Juli has no
 * payment integration (Ops grants terms by contract, D28.4/D28.5).
 */

/** The query P33-F's "Tự kết nối shop ngay" button carries. */
export const TRIAL_SIGNUP_PARAM = { name: "dang-ky", value: "dung-thu" } as const;

export const TRIAL_SIGNUP_HEADING = "Dùng thử Juli miễn phí 3 tháng";
export const TRIAL_SIGNUP_BODY = "Không cần thẻ thanh toán. Sau 3 tháng, từ 500.000đ/tháng.";
export const TRIAL_SIGNUP_GOOGLE_LABEL = "Đăng ký bằng Google";
export const TRIAL_SIGNUP_EMAIL_LABEL = "Gửi mã đăng ký";
/** Eyebrow above the OTP view's heading in the trial variant. */
export const TRIAL_SIGNUP_EYEBROW = "Dùng thử miễn phí 3 tháng";
export const TRIAL_SIGNUP_CODE_LEGEND = "Mã đăng ký";
export const TRIAL_SIGNUP_CONFIRM_LABEL = "Xác nhận và tạo tài khoản";
/** Under the column: back to plain sign-in. */
export const TRIAL_SIGNUP_SWITCH_TEXT = "Đã có tài khoản?";
export const TRIAL_SIGNUP_SWITCH_LINK = "Đăng nhập";

export function isTrialSignupSearch(search: string): boolean {
  return new URLSearchParams(search).get(TRIAL_SIGNUP_PARAM.name) === TRIAL_SIGNUP_PARAM.value;
}
