import { CtaLink } from "../../components/cta-link";
import { LandingHeader } from "../../components/landing-header";
import { SiteFooter } from "../../components/site-footer";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY, DEMO_URL } from "../../lib/site";

export const metadata = buildMetadata("/contact");

const TOPICS = [
  {
    title: "Tư vấn sử dụng",
    body: "Bạn muốn biết Juli phù hợp với shop của mình thế nào, hoặc cần hướng dẫn kết nối TikTok Shop.",
  },
  {
    title: "Hỗ trợ tài khoản",
    body: "Câu hỏi về tài khoản, thanh toán, ngắt kết nối shop hoặc yêu cầu xoá dữ liệu.",
  },
  {
    title: "Hợp tác",
    body: "Agency, đối tác vận hành sàn hoặc nhà cung cấp muốn hợp tác cùng Juli AI.",
  },
] as const;

export default function ContactPage() {
  return (
    <>
      <JsonLd data={breadcrumbSchema("/contact")} />
      <LandingHeader />
      <main className="lp-main">
        <section aria-labelledby="contact-heading" className="lp-page-hero">
          <p className="lp-page-hero__eyebrow">Liên hệ</p>
          <h1 className="lp-page-hero__heading" id="contact-heading">
            Liên hệ Juli AI
          </h1>
          <p className="lp-page-hero__lead">
            Gửi email cho chúng tôi về mọi câu hỏi liên quan đến sản phẩm, tài khoản hoặc
            hợp tác. Vui lòng ghi rõ tên shop (nếu có) để chúng tôi hỗ trợ nhanh hơn.
          </p>
        </section>

        <section aria-labelledby="channels-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="channels-heading">
            Thông tin liên hệ
          </h2>
          <div className="lp-page-grid">
            <article className="lp-page-card" data-testid="contact-email">
              <h3 className="lp-page-card__title">Email</h3>
              <p className="lp-page-card__body">
                <a className="lp-legal__contact-link" href={`mailto:${COMPANY.email}`}>
                  {COMPANY.email}
                </a>
              </p>
            </article>
            <article className="lp-page-card" data-testid="contact-address">
              <h3 className="lp-page-card__title">Địa chỉ</h3>
              <p className="lp-page-card__body">
                {COMPANY.name}
                <br />
                {COMPANY.address}
                <br />
                Mã số thuế: {COMPANY.taxId}
              </p>
            </article>
          </div>
        </section>

        <section aria-labelledby="topics-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="topics-heading">
            Chúng tôi có thể giúp gì
          </h2>
          <div className="lp-page-grid lp-page-grid--three">
            {TOPICS.map((item) => (
              <article className="lp-page-card" key={item.title}>
                <h3 className="lp-page-card__title">{item.title}</h3>
                <p className="lp-page-card__body">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="contact-cta-heading" className="lp-page-section lp-page-section--cta">
          <h2 className="lp-page-section__heading" id="contact-cta-heading">
            Muốn xem trước khi liên hệ?
          </h2>
          <p className="lp-page-section__body">
            Bản Demo chạy trên dữ liệu mẫu, không cần đăng ký.
          </p>
          <div className="lp-page-hero__actions">
            <CtaLink href={DEMO_URL} size="large">
              Trải nghiệm Demo
            </CtaLink>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
