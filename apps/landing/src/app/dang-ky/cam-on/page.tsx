import { NextSteps } from "../../../components/signup/next-steps";
import { SignupConversion } from "../../../components/signup/signup-conversion";
import {
  SELF_CONNECT_LABEL,
  SELF_CONNECT_URL,
  THANKS_H1,
} from "../../../components/signup/signup-content";
import styles from "../../../components/signup/signup.module.css";
import { BirdGlyph, Eyebrow, Heading, LinkButton } from "../../../components/ui";
import { SiteFooter } from "../../../components/ui/site-footer";
import { SiteHeader } from "../../../components/ui/site-header";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../../lib/seo";
import { COMPANY } from "../../../lib/site";

/** noindex (registry `noindex: true`), not in the sitemap. */
export const metadata = buildMetadata("/dang-ky/cam-on");

/** `/dang-ky/cam-on` — after a trial sign-up (P33-F; calm confirmation, P34-E). */
export default function SignupThanksPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/dang-ky/cam-on")} />
      <SignupConversion />
      <SiteHeader />
      <main>
        <section aria-labelledby="thanks-heading" className={styles.thanks}>
          <div className={styles.thanksHead}>
            <BirdGlyph height={39} />
            <Eyebrow>Đã nhận đăng ký</Eyebrow>
            <Heading className={styles.h1} id="thanks-heading" level={1} size="page">
              {THANKS_H1}
            </Heading>
            <p className={styles.lead}>
              Đội ngũ Juli sẽ liên hệ với bạn qua điện thoại hoặc Zalo để thiết lập kết nối shop
              TikTok và bàn giao tài khoản dùng thử 3 tháng.
            </p>
          </div>

          <div className={styles.thanksCard}>
            <h2 className={styles.asideTitle}>Tiếp theo</h2>
            <NextSteps />
          </div>

          <div className={styles.thanksHead}>
            <h2 className={styles.asideTitle}>Không muốn chờ?</h2>
            <p className={styles.small}>
              Bạn có thể tự kết nối TikTok Shop ngay bây giờ trên ứng dụng Juli.
            </p>
            <div className={styles.actions}>
              <LinkButton blockOnMobile data-testid="self-connect-cta" href={SELF_CONNECT_URL}>
                {SELF_CONNECT_LABEL}
              </LinkButton>
              <LinkButton blockOnMobile data-testid="thanks-home-link" href="/" variant="secondary">
                Về trang chủ
              </LinkButton>
            </div>
          </div>

          <p className={styles.small}>
            Cần hỗ trợ? Email <a href={`mailto:${COMPANY.email}`}>{COMPANY.email}</a>.
          </p>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
