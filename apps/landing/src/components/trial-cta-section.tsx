import { DEMO_URL, LOGIN_URL } from "../lib/site";
import { CtaLink } from "./cta-link";

/** Who the 3-month trial is for — the four segments the sales outreach targets. */
const AUDIENCES = [
  "Nhà bán hàng",
  "Affiliate",
  "Đội vận hành sàn",
  "Agency",
] as const;

/**
 * Closing trial CTA: names the audience and the offer (3 months free, then
 * from 500K/month), then repeats the hero's paired Demo + Login/Signup CTAs.
 */
export function TrialCtaSection() {
  return (
    <section aria-labelledby="trial-cta-heading" className="lp-curiosity">
      <h2 className="lp-curiosity__heading" id="trial-cta-heading">
        Tăng trưởng tinh gọn và ổn định, bắt đầu miễn phí.
      </h2>
      <p className="lp-curiosity__audience">
        Dành cho {AUDIENCES.join(" · ")}
      </p>
      <p className="lp-curiosity__body">
        Miễn phí thử nghiệm 3 tháng, sau đó chỉ từ 500K/tháng.
      </p>
      <div className="lp-curiosity__actions">
        <CtaLink data-testid="trial-demo-cta" href={DEMO_URL} size="large">
          Trải nghiệm Demo
        </CtaLink>
        <CtaLink
          data-testid="trial-login-cta"
          href={LOGIN_URL}
          size="large"
          variant="secondary"
        >
          Đăng nhập / Đăng ký
        </CtaLink>
      </div>
    </section>
  );
}
