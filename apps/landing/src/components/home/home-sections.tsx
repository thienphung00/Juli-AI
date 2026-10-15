import Link from "next/link";

import {
  COMPANY,
  DEMO_URL,
  PRODUCT_PAGES,
  SECTION_IDS,
  SIGNUP_URL,
  TRIAL_CTA_LABEL,
} from "../../lib/site";
import { CtaLink } from "../cta-link";
import {
  AUDIENCES,
  CAPABILITIES,
  HOME_FAQ,
  HOW_IT_WORKS,
  PROBLEMS,
  SAFETY,
} from "./home-content";
import { HeroVideo } from "./hero-video";

/**
 * Homepage sections (D43.2, AC-33.5). Heading outline: one H1 in the hero, one
 * H2 per section, H3 for items inside a section — never deeper.
 */

const CAPABILITY_LINKS = {
  analysis: PRODUCT_PAGES.analysis,
  actions: PRODUCT_PAGES.actions,
  measurement: PRODUCT_PAGES.measurement,
} as const;

export function HomeHero() {
  return (
    <section aria-labelledby="hero-heading" className="lp-home-hero">
      <div className="lp-home-hero__copy">
        <h1 className="lp-home-hero__heading" id="hero-heading">
          Juli AI — trợ lý AI vận hành cho nhà bán TikTok Shop: phân tích, đề xuất, thực thi sau
          khi bạn duyệt, đo GMV
        </h1>
        <p className="lp-home-hero__lead">
          Juli đọc dữ liệu shop qua TikTok Shop Open API, tìm sản phẩm và chỉ số đang làm hụt
          GMV, rồi đề xuất việc cụ thể. Bạn duyệt, Juli cập nhật trang sản phẩm và đo kết quả
          sau 7 và 14 ngày.
        </p>
        <div className="lp-home-hero__actions">
          <CtaLink data-testid="hero-trial-cta" href={SIGNUP_URL} size="large">
            {TRIAL_CTA_LABEL}
          </CtaLink>
          <CtaLink data-testid="hero-demo-cta" href={DEMO_URL} size="large" variant="secondary">
            Xem demo
          </CtaLink>
        </div>
        <p className="lp-home-hero__note">
          Không cần thẻ thanh toán · sau đó từ 500K/tháng · Demo dùng dữ liệu mẫu, không cần đăng ký
        </p>
        <p className="lp-home-hero__consent" data-testid="hero-consent-note">
          Khi đăng ký, bạn đồng ý với{" "}
          <Link className="lp-home-hero__consent-link" href="/terms">
            Điều khoản dịch vụ
          </Link>{" "}
          và{" "}
          <Link className="lp-home-hero__consent-link" href="/privacy">
            Chính sách bảo mật
          </Link>{" "}
          của Juli.
        </p>
      </div>
      <div className="lp-home-hero__visual">
        <HeroVideo />
      </div>
    </section>
  );
}

/** D42.6: TikTok Shop is live; Shopee is named in text as being integrated, never as live. */
export function MarketplaceStrip() {
  return (
    <section aria-labelledby="marketplace-heading" className="lp-home-band">
      <div className="lp-home-inner">
        <h2 className="lp-home-band__heading" id="marketplace-heading">
          Sàn thương mại điện tử Juli kết nối
        </h2>
        <ul className="lp-home-markets">
          <li className="lp-home-market" data-testid="market-tiktok">
            <h3 className="lp-home-market__name">TikTok Shop</h3>
            <p className="lp-home-market__status lp-home-market__status--live">Đang hoạt động</p>
            <p className="lp-home-market__body">
              Kết nối chính thức qua TikTok Shop Open API. Bạn cấp quyền trên trang của TikTok
              Shop.{" "}
              <Link className="lp-home-link" href={PRODUCT_PAGES.tiktokShop.href}>
                Cách kết nối TikTok Shop
              </Link>
            </p>
          </li>
          <li className="lp-home-market" data-testid="market-shopee">
            <h3 className="lp-home-market__name">Shopee</h3>
            <p className="lp-home-market__status">Đang tích hợp</p>
            <p className="lp-home-market__body">
              Shopee đang tích hợp qua Shopee Open Platform. Hiện chưa kết nối được shop Shopee.
            </p>
          </li>
        </ul>
      </div>
    </section>
  );
}

export function ProblemSection() {
  return (
    <section aria-labelledby="problem-heading" className="lp-home-section">
      <div className="lp-home-inner">
        <h2 className="lp-home-section__heading" id="problem-heading">
          GMV giảm, nhưng hụt ở đâu?
        </h2>
        <p className="lp-home-section__lead">
          Nhà bán TikTok Shop thường phải đoán. Juli thay phần đoán bằng số liệu của chính shop.
        </p>
        <div className="lp-home-grid lp-home-grid--three">
          {PROBLEMS.map((item) => (
            <article className="lp-home-card" key={item.title}>
              <h3 className="lp-home-card__title">{item.title}</h3>
              <p className="lp-home-card__body">{item.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function HowItWorksSection() {
  return (
    <section
      aria-labelledby="how-heading"
      className="lp-home-section lp-home-section--tinted"
      id={SECTION_IDS.howItWorks}
    >
      <div className="lp-home-inner">
        <h2 className="lp-home-section__heading" id="how-heading">
          Juli làm việc thế nào: Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường
        </h2>
        <ol className="lp-home-steps">
          {HOW_IT_WORKS.map((step, index) => (
            <li className="lp-home-step" key={step.key}>
              <span aria-hidden="true" className="lp-home-step__number">
                {index + 1}
              </span>
              <h3 className="lp-home-step__title">{step.title}</h3>
              <p className="lp-home-step__body">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function CapabilitiesSection() {
  return (
    <section
      aria-labelledby="capabilities-heading"
      className="lp-home-section"
      id={SECTION_IDS.capabilities}
    >
      <div className="lp-home-inner">
        <h2 className="lp-home-section__heading" id="capabilities-heading">
          Ba năng lực chính của Juli
        </h2>
        <div className="lp-home-grid lp-home-grid--three">
          {CAPABILITIES.map((item) => {
            const page = CAPABILITY_LINKS[item.key];
            return (
              <article className="lp-home-card lp-home-card--capability" key={item.key}>
                <h3 className="lp-home-card__title">{item.title}</h3>
                <p className="lp-home-card__body">{item.body}</p>
                <ul className="lp-home-list">
                  {item.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
                <Link
                  className="lp-home-link lp-home-card__more"
                  data-testid={`capability-link-${item.key}`}
                  href={page.href}
                >
                  Xem chi tiết: {page.label} ›
                </Link>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function SafetySection() {
  return (
    <section aria-labelledby="safety-heading" className="lp-home-section lp-home-section--tinted">
      <div className="lp-home-inner">
        <h2 className="lp-home-section__heading" id="safety-heading">
          Dữ liệu an toàn, quyền quyết định là của bạn
        </h2>
        <div className="lp-home-grid">
          {SAFETY.map((item) => (
            <article className="lp-home-card" key={item.title}>
              <h3 className="lp-home-card__title">{item.title}</h3>
              <p className="lp-home-card__body">{item.body}</p>
            </article>
          ))}
        </div>
        <p className="lp-home-section__lead">
          Juli đọc gì, lưu bao lâu và chia sẻ với ai được nêu đầy đủ tại{" "}
          <Link className="lp-home-link" href="/privacy">
            Chính sách bảo mật
          </Link>
          .
        </p>
      </div>
    </section>
  );
}

export function AudienceSection() {
  return (
    <section aria-labelledby="audience-heading" className="lp-home-section">
      <div className="lp-home-inner">
        <h2 className="lp-home-section__heading" id="audience-heading">
          Juli dành cho ai
        </h2>
        <div className="lp-home-grid lp-home-grid--four">
          {AUDIENCES.map((item) => (
            <article className="lp-home-card" key={item.title}>
              <h3 className="lp-home-card__title">{item.title}</h3>
              <p className="lp-home-card__body">{item.body}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/** D43.3: transparency instead of proof — method, labelled sample data, company. */
export function TransparencySection() {
  return (
    <section
      aria-labelledby="transparency-heading"
      className="lp-home-section lp-home-section--tinted"
    >
      <div className="lp-home-inner">
        <h2 className="lp-home-section__heading" id="transparency-heading">
          Minh bạch thay cho lời quảng cáo
        </h2>
        <p className="lp-home-section__lead">
          Juli còn mới. Chúng tôi chưa đăng lời chứng thực hay con số kết quả nào: chỉ công bố
          khi đo được trên shop thật, bằng cách đo dưới đây.
        </p>
        <div className="lp-home-grid lp-home-grid--three">
          <article className="lp-home-card">
            <h3 className="lp-home-card__title">Cách Juli đo GMV tăng thêm</h3>
            <p className="lp-home-card__body">
              Mỗi thay đổi có một mức GMV dự kiến được ghi lại trước khi thực thi. Juli so sản
              phẩm đã thay đổi với các sản phẩm tương tự chưa thay đổi trong cùng shop, đọc sơ bộ
              ở ngày 7 và chốt ở ngày 14. Kết quả được ghi là &quot;Thay đổi rõ&quot;, &quot;Có
              thể thay đổi&quot; hoặc &quot;Trong dao động&quot;, không làm tròn thành thành công.
            </p>
            <Link className="lp-home-link" href={PRODUCT_PAGES.measurement.href}>
              Chi tiết cách đo ›
            </Link>
          </article>
          <article className="lp-home-card">
            <h3 className="lp-home-card__title">Dữ liệu mẫu được ghi rõ</h3>
            <p className="lp-home-card__body">
              Bản Demo chạy trên một shop mẫu, có nhãn &quot;dữ liệu mẫu&quot;. Ảnh giao diện trên
              website cũng dùng dữ liệu mẫu. Không có con số nào trên trang này là kết quả của một
              khách hàng.
            </p>
            <a className="lp-home-link" href={DEMO_URL}>
              Mở bản Demo ›
            </a>
          </article>
          <article className="lp-home-card" data-testid="home-company">
            <h3 className="lp-home-card__title">Ai đứng sau Juli</h3>
            <p className="lp-home-card__body">
              Juli AI do {COMPANY.name} phát triển và vận hành. Mã số thuế {COMPANY.taxId}. Trụ sở:{" "}
              {COMPANY.address}. Liên hệ:{" "}
              <a className="lp-home-link" href={`mailto:${COMPANY.email}`}>
                {COMPANY.email}
              </a>
              .
            </p>
            <Link className="lp-home-link" href="/about">
              Về công ty ›
            </Link>
          </article>
        </div>
      </div>
    </section>
  );
}

export function PricingFaqSection() {
  return (
    <>
      <section aria-labelledby="pricing-heading" className="lp-home-section">
        <div className="lp-home-inner lp-home-pricing">
          <h2 className="lp-home-section__heading" id="pricing-heading">
            Chi phí: dùng thử miễn phí 3 tháng, sau đó từ 500K/tháng
          </h2>
          <p className="lp-home-section__lead">
            Tài khoản mới được dùng thử miễn phí 3 tháng kể từ ngày đăng ký, với đầy đủ phân tích,
            đề xuất, thực thi và đo lường. Không cần thẻ thanh toán. Sau đó từ 500K/tháng, huỷ bất
            cứ lúc nào.{" "}
            <Link className="lp-home-link" href="/san-pham#bang-gia">
              Xem chi tiết bảng giá
            </Link>
          </p>
          <CtaLink data-testid="pricing-trial-cta" href={SIGNUP_URL} size="large">
            {TRIAL_CTA_LABEL}
          </CtaLink>
        </div>
      </section>
      <section
        aria-labelledby="faq-heading"
        className="lp-home-section lp-home-section--tinted"
        id={SECTION_IDS.faq}
      >
        <div className="lp-home-inner">
          <h2 className="lp-home-section__heading" id="faq-heading">
            Câu hỏi thường gặp
          </h2>
          <dl className="lp-page-faq">
            {HOME_FAQ.map((item) => (
              <div className="lp-page-faq__item" key={item.question}>
                <dt className="lp-page-faq__question">{item.question}</dt>
                <dd className="lp-page-faq__answer">{item.answer}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>
    </>
  );
}

export function FinalCta() {
  return (
    <section aria-labelledby="final-cta-heading" className="lp-home-final">
      <h2 className="lp-home-final__heading" id="final-cta-heading">
        Xem shop của bạn đang hụt GMV ở đâu
      </h2>
      <p className="lp-home-final__body">
        Dành cho Nhà bán hàng · Affiliate · Đội vận hành sàn · Agency. Miễn phí 3 tháng, không cần
        thẻ thanh toán, sau đó từ 500K/tháng.
      </p>
      <div className="lp-home-hero__actions lp-home-final__actions">
        <CtaLink data-testid="trial-signup-cta" href={SIGNUP_URL} size="large">
          {TRIAL_CTA_LABEL}
        </CtaLink>
        <CtaLink data-testid="trial-demo-cta" href={DEMO_URL} size="large" variant="secondary">
          Xem demo
        </CtaLink>
      </div>
    </section>
  );
}
