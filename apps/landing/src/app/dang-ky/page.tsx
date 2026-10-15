import { CAP_KN_KET_NOI_MOBILE } from "../../components/product/screens";
import { NextSteps } from "../../components/signup/next-steps";
import {
  SELF_CONNECT_LINK_LABEL,
  SELF_CONNECT_PROMPT,
  SELF_CONNECT_URL,
  SIGNUP_EYEBROW,
  SIGNUP_H1,
  SIGNUP_LEAD,
} from "../../components/signup/signup-content";
import { SignupForm } from "../../components/signup/signup-form";
import styles from "../../components/signup/signup.module.css";
import { Eyebrow, Heading, ShotFrame } from "../../components/ui";
import { SiteFooter } from "../../components/ui/site-footer";
import { SiteHeader } from "../../components/ui/site-header";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";

export const metadata = buildMetadata("/dang-ky");

/** `/dang-ky` — the free 3-month trial sign-up (P33-F, D43; Signup.dc.html, P34-E). */
export default function SignupPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/dang-ky")} />
      <SiteHeader variant="signup" />
      <main className={styles.page}>
        <section aria-labelledby="signup-heading" className={styles.formColumn}>
          <div className={styles.intro}>
            <Eyebrow>{SIGNUP_EYEBROW}</Eyebrow>
            <Heading className={styles.h1} id="signup-heading" level={1} size="page">
              {SIGNUP_H1}
            </Heading>
            <p className={styles.lead}>{SIGNUP_LEAD}</p>
          </div>
          <SignupForm />
          <p className={styles.selfConnect}>
            {SELF_CONNECT_PROMPT}{" "}
            <a data-testid="signup-self-connect-link" href={SELF_CONNECT_URL}>
              {SELF_CONNECT_LINK_LABEL}
            </a>
          </p>
        </section>

        <aside aria-labelledby="after-signup-heading" className={styles.aside}>
          <h2 className={styles.asideTitle} id="after-signup-heading">
            Sau khi bạn đăng ký
          </h2>
          <NextSteps />
          <ShotFrame
            as="figure"
            caption="Dữ liệu mẫu"
            images={{
              variants: CAP_KN_KET_NOI_MOBILE,
              alt: "Màn hình kết nối TikTok Shop trong Juli (dữ liệu mẫu)",
            }}
            sizes="(min-width: 1200px) 460px, (min-width: 960px) 40vw, 100vw"
          />
        </aside>
      </main>
      <SiteFooter />
    </>
  );
}
