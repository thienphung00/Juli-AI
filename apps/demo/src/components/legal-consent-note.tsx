/**
 * The privacy policy and terms, linked where a seller signs in (Google or
 * email). Google's OAuth policy requires the privacy policy to be prominently
 * reachable inside the app, not only on the marketing homepage. Both pages
 * live on the main domain, served by apps/landing.
 */
export const PRIVACY_POLICY_URL = "https://app-juli.com/privacy";
export const TERMS_OF_SERVICE_URL = "https://app-juli.com/terms";

export function LegalConsentNote() {
  return (
    <p className="demo-legal-note" data-testid="legal-consent-note">
      Bằng việc đăng nhập, bạn đồng ý với{" "}
      <a href={TERMS_OF_SERVICE_URL}>Điều khoản dịch vụ</a> và{" "}
      <a href={PRIVACY_POLICY_URL}>Chính sách bảo mật</a> của Juli.
    </p>
  );
}
