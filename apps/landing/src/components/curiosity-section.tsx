import { DEMO_URL } from "../lib/site";
import { CtaLink } from "./cta-link";

/**
 * Curiosity CTA — the direct psychological trigger into the Demo
 * (CONTEXT.md `apps/landing`): invite the seller to find out how their own
 * shop is doing, answered by the Demo on sample data with zero friction.
 */
export function CuriositySection() {
  return (
    <section aria-labelledby="curiosity-heading" className="lp-curiosity">
      <h2 className="lp-curiosity__heading" id="curiosity-heading">
        Shop của bạn đang vận hành thế nào?
      </h2>
      <p className="lp-curiosity__body">
        Xem Juli phân tích một cửa hàng thật trên dữ liệu mẫu — không cần đăng
        ký, không cần kết nối cửa hàng.
      </p>
      <CtaLink data-testid="curiosity-demo-cta" href={DEMO_URL} size="large">
        Khám phá hiệu suất shop của bạn
      </CtaLink>
    </section>
  );
}
