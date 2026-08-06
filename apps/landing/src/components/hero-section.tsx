import Image from "next/image";

import heroMascot from "@juli/brand/assets/hero-mascot.webp";

import { DEMO_URL, SECTION_IDS } from "../lib/site";
import { CtaLink } from "./cta-link";

export function HeroSection() {
  return (
    <section aria-labelledby="hero-heading" className="lp-hero">
      <div className="lp-hero__copy">
        <p className="lp-hero__badge">TikTok Shop Partner ✓</p>
        <h1 className="lp-hero__heading" id="hero-heading">
          Mất doanh thu vì nhập hàng chậm, hoàn tiền, quảng cáo kém hiệu quả?
        </h1>
        <p className="lp-hero__body">
          Những vấn đề này có thể âm thầm làm chậm tăng trưởng của bạn. Juli tự
          động theo dõi cửa hàng và đề xuất hành động phù hợp — bạn phê duyệt,
          Juli thực hiện.
        </p>
        <p className="lp-hero__flow">
          Nhập hàng đúng lúc → xử lý hoàn tiền → tối ưu ngân sách quảng cáo →
          đẩy mạnh sản phẩm tiềm năng
        </p>
        <div className="lp-hero__actions">
          <CtaLink data-testid="hero-demo-cta" href={DEMO_URL} size="large">
            Trải nghiệm Demo
          </CtaLink>
          <CtaLink href={`#${SECTION_IDS.features}`} size="large" variant="secondary">
            Tìm hiểu tính năng
          </CtaLink>
        </div>
        <p className="lp-hero__reassurance">
          Miễn phí trải nghiệm · Dễ sử dụng · Tiến độ và kết quả minh bạch
        </p>
      </div>
      <div className="lp-hero__visual">
        <Image
          alt="Linh vật Juli giới thiệu bảng điều khiển Juli AI trên điện thoại với các chỉ số doanh thu và tồn kho"
          className="lp-hero__photo"
          placeholder="blur"
          priority
          src={heroMascot}
        />
      </div>
    </section>
  );
}
