import Image from "next/image";

import heroMascot from "@juli/brand/assets/hero-mascot.webp";

import { DEMO_URL, LOGIN_URL } from "../lib/site";
import { CtaLink } from "./cta-link";

export function HeroSection() {
  return (
    <section aria-labelledby="hero-heading" className="lp-hero">
      <div className="lp-hero__copy">
        <p className="lp-hero__badge">TikTok Shop Partner ✓</p>
        <h1 className="lp-hero__heading" id="hero-heading">
          Shop của bạn đang mất tiền ở đâu?
        </h1>
        <p className="lp-hero__body">
          Nhập hàng chậm, đơn hoàn chồng chất, quảng cáo đốt ngân sách vào sai
          sản phẩm. Những khoản thất thoát này trực tiếp ảnh hưởng vào lợi
          nhuận. Juli theo dõi 24/7.
        </p>
        <p className="lp-hero__flow">
          Xem ngay ở Demo: Chặn thất thoát: tồn kho, đơn hoàn, phí ẩn → Tăng
          doanh thu: quảng cáo, sản phẩm tiềm năng, giá bán.
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
