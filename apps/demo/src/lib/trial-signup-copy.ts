/**
 * Trial sign-up door (D43 additions, owner 2026-10-15): the self-connect path.
 * app-juli.com's trial form (`/dang-ky`, P33-F) ends on a thank-you page whose
 * "Tự kết nối shop ngay" button opens `/?dang-ky=dung-thu`; the landing's
 * sign-in door then reads as a trial sign-up. Same Google / email buttons — an
 * existing seller still signs in with them. Copy lives in `dictionary.md`
 * (`auth.trial_signup.*`). "Không cần thẻ thanh toán" is true: Juli has no
 * payment integration (Ops grants terms by contract, D28.4/D28.5).
 */

/** The query P33-F's "Tự kết nối shop ngay" button carries. */
export const TRIAL_SIGNUP_PARAM = { name: "dang-ky", value: "dung-thu" } as const;

export const TRIAL_SIGNUP_EYEBROW = "Tài khoản mới";
export const TRIAL_SIGNUP_HEADING = "Đăng ký dùng thử miễn phí 3 tháng";
export const TRIAL_SIGNUP_BODY =
  "Tạo tài khoản bằng Google hoặc email, rồi kết nối TikTok Shop. Miễn phí 3 tháng, sau đó từ 500.000đ/tháng. Không cần thẻ thanh toán.";
export const TRIAL_SIGNUP_EXISTING_NOTE =
  "Đã có tài khoản? Đăng nhập bằng đúng Google hoặc email bạn đã dùng.";

export function isTrialSignupSearch(search: string): boolean {
  return new URLSearchParams(search).get(TRIAL_SIGNUP_PARAM.name) === TRIAL_SIGNUP_PARAM.value;
}
