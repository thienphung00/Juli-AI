import type { Metadata } from "next";

import { CtaLink } from "../components/cta-link";
import { LandingHeader } from "../components/landing-header";
import { SiteFooter } from "../components/site-footer";

export const metadata: Metadata = {
  title: "Không tìm thấy trang — Juli AI",
};

export default function NotFound() {
  return (
    <>
      <LandingHeader />
      <main className="lp-main">
        <section aria-labelledby="not-found-heading" className="lp-page-hero lp-page-hero--center">
          <p className="lp-page-hero__eyebrow">Lỗi 404</p>
          <h1 className="lp-page-hero__heading" id="not-found-heading">
            Không tìm thấy trang này
          </h1>
          <p className="lp-page-hero__lead">
            Đường dẫn có thể đã thay đổi hoặc không còn tồn tại. Bạn có thể quay lại trang
            chủ hoặc tìm hiểu về Juli AI tại các trang dưới đây.
          </p>
          <div className="lp-page-hero__actions">
            <CtaLink href="/" size="large">
              Về trang chủ
            </CtaLink>
            <CtaLink href="/product" size="large" variant="secondary">
              Xem sản phẩm
            </CtaLink>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
