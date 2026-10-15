import { SiteHeader } from "../../components/ui/site-header";
import { SiteFooter } from "../../components/ui/site-footer";
import {
  SIGNUP_H1,
  SIGNUP_LEAD,
  SIGNUP_VALUES,
} from "../../components/signup/signup-content";
import { SignupForm } from "../../components/signup/signup-form";
import styles from "../../components/signup/signup.module.css";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";

export const metadata = buildMetadata("/dang-ky");

/** `/dang-ky` — the free 3-month trial sign-up (P33-F, D43). */
export default function SignupPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/dang-ky")} />
      <SiteHeader variant="signup" />
      <main className="lp-main">
        <section aria-labelledby="signup-heading" className={styles.layout}>
          <div className={styles.intro}>
            <p className={styles.eyebrow}>Dùng thử Juli AI</p>
            <h1 className={styles.h1} id="signup-heading">
              {SIGNUP_H1}
            </h1>
            <p className={styles.lead}>{SIGNUP_LEAD}</p>
            <ul aria-label="Bạn nhận được gì" className={styles.values} data-testid="signup-values">
              {SIGNUP_VALUES.map((value) => (
                <li key={value}>{value}</li>
              ))}
            </ul>
          </div>
          <div className={styles.card}>
            <SignupForm />
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
