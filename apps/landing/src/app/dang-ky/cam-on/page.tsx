import { CtaLink } from "../../../components/cta-link";
import { LandingHeader } from "../../../components/landing-header";
import { SiteFooter } from "../../../components/site-footer";
import { SignupConversion } from "../../../components/signup/signup-conversion";
import {
  SELF_CONNECT_LABEL,
  SELF_CONNECT_URL,
  THANKS_H1,
} from "../../../components/signup/signup-content";
import styles from "../../../components/signup/signup.module.css";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../../lib/seo";

/** noindex (registry `noindex: true`), not in the sitemap. */
export const metadata = buildMetadata("/dang-ky/cam-on");

/** `/dang-ky/cam-on` — after a trial sign-up (P33-F). */
export default function SignupThanksPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/dang-ky/cam-on")} />
      <SignupConversion />
      <LandingHeader />
      <main className="lp-main">
        <section aria-labelledby="thanks-heading" className={styles.thanks}>
          <p className={styles.eyebrow}>Đã nhận đăng ký</p>
          <h1 className={styles.h1} id="thanks-heading">
            {THANKS_H1}
          </h1>
          <p className={styles.lead}>
            Đội ngũ Juli sẽ liên hệ với bạn qua điện thoại hoặc Zalo để thiết lập kết nối shop
            TikTok và bàn giao tài khoản dùng thử 3 tháng.
          </p>
          <h2 className={styles.h2}>Tiếp theo</h2>
          <ol className={styles.steps}>
            <li>Juli gọi hoặc nhắn Zalo cho bạn theo số đã đăng ký.</li>
            <li>Cùng bạn kết nối TikTok Shop với Juli (bạn cấp quyền trên TikTok Shop).</li>
            <li>Juli bắt đầu đọc dữ liệu shop và gửi những đề xuất đầu tiên để bạn duyệt.</li>
          </ol>
          <h2 className={styles.h2}>Không muốn chờ?</h2>
          <p className={styles.small}>
            Bạn có thể tự kết nối TikTok Shop ngay bây giờ trên ứng dụng Juli.
          </p>
          <div className={styles.actions}>
            <CtaLink data-testid="self-connect-cta" href={SELF_CONNECT_URL} size="large">
              {SELF_CONNECT_LABEL}
            </CtaLink>
            <CtaLink href="/" variant="secondary" size="large">
              Về trang chủ
            </CtaLink>
          </div>
          <p className={styles.small}>
            Cần hỗ trợ? Email <a href="mailto:lienhe@app-juli.com">lienhe@app-juli.com</a>.
          </p>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
