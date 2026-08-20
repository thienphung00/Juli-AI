import Image from "next/image";

import heroMascot from "@juli/brand/assets/hero-mascot.webp";

import { DEMO_URL, LOGIN_URL } from "../lib/site";
import { CtaLink } from "./cta-link";

/** The outcome triplet, rendered one promise per line under the problem copy. */
const PROMISES = [
  "Ít việc thủ công hơn.",
  "Ít chi phí thất thoát hơn.",
  "Nhiều lợi nhuận hơn.",
] as const;

export function HeroSection() {
  return (
    <section aria-labelledby="hero-heading" className="lp-hero">
      <div className="lp-hero__copy">
        <p className="lp-hero__badge">TikTok Shop Partner ✓</p>
        <h1 className="lp-hero__heading" id="hero-heading">
          Trợ lý AI giúp bạn tự động hóa vận hành, giảm chi phí và tối ưu lợi
          nhuận.
        </h1>
        <p className="lp-hero__body">
          Juli theo dõi shop 24/7, tự động phát hiện vấn đề, tìm cơ hội tối ưu
          và đề xuất những việc cần làm để bạn không phải làm mọi thứ thủ công.
        </p>
        <p className="lp-hero__flow">
          Sản phẩm cần tối ưu. Nhập hàng chậm. Đơn hoàn chồng chất. Quảng cáo
          đốt ngân sách. Những công việc vận hành lặp lại khiến bạn mất thời
          gian và những sai sót nhỏ có thể trực tiếp ăn vào lợi nhuận và chi
          phí.
        </p>
        <p className="lp-hero__promise">
          {PROMISES.map((promise) => (
            <span className="lp-hero__promise-line" key={promise}>
              {promise}
            </span>
          ))}
        </p>
        <p className="lp-hero__hook">
          Đăng nhập ngay để biết chính xác 3 điều shop bạn cần cải thiện.
        </p>
        <div className="lp-hero__actions">
          <CtaLink data-testid="hero-demo-cta" href={DEMO_URL} size="large">
            Trải nghiệm Demo
          </CtaLink>
          <CtaLink
            data-testid="hero-login-cta"
            href={LOGIN_URL}
            size="large"
            variant="secondary"
          >
            Đăng nhập / Đăng ký
          </CtaLink>
        </div>
        <p className="lp-hero__reassurance">
          Miễn phí trải nghiệm · Dành cho điện thoại · Kết quả trực tiếp
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
