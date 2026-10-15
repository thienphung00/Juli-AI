import Link from "next/link";

import { CtaLink } from "../../components/cta-link";
import { SiteHeader } from "../../components/ui/site-header";
import { SiteFooter } from "../../components/ui/site-footer";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY, DEMO_URL } from "../../lib/site";

export const metadata = buildMetadata("/about");

const PRINCIPLES = [
  {
    title: "Người bán quyết định",
    body: "Juli đề xuất, người bán phê duyệt. Không có thay đổi nào trên shop nếu chưa có sự đồng ý của chủ shop.",
  },
  {
    title: "Minh bạch về dữ liệu",
    body: "Chỉ đọc dữ liệu cần thiết để phân tích, nói rõ dữ liệu được dùng ra sao, và không bán dữ liệu cho bên thứ ba.",
  },
  {
    title: "Đo bằng kết quả",
    body: "Mỗi đề xuất gắn với một chỉ số cụ thể, để người bán thấy rõ tác động lên GMV sau mỗi tháng.",
  },
  {
    title: "Thiết kế cho điện thoại",
    body: "Phần lớn người bán vận hành shop trên điện thoại, nên Juli được thiết kế để dùng tốt trên màn hình nhỏ trước tiên.",
  },
] as const;

export default function AboutPage() {
  const companyFacts = [
    { label: "Tên doanh nghiệp", value: COMPANY.name },
    { label: "Mã số thuế", value: COMPANY.taxId },
    { label: "Trụ sở", value: COMPANY.address },
    { label: "Email", value: COMPANY.email, href: `mailto:${COMPANY.email}` },
    { label: "Website", value: "app-juli.com", href: "https://app-juli.com" },
    { label: "Sản phẩm", value: "Juli AI — trợ lý tăng trưởng cho người bán TikTok Shop", href: "/san-pham" },
  ];

  return (
    <>
      <JsonLd data={breadcrumbSchema("/about")} />
      <SiteHeader />
      <main className="lp-main">
        <section aria-labelledby="about-heading" className="lp-page-hero">
          <p className="lp-page-hero__eyebrow">Giới thiệu</p>
          <h1 className="lp-page-hero__heading" id="about-heading">
            Về Juli AI
          </h1>
          <p className="lp-page-hero__lead">
            Juli AI được phát triển và vận hành bởi {COMPANY.name}, một công ty công nghệ
            có trụ sở tại Thành phố Hồ Chí Minh. Chúng tôi xây dựng phần mềm giúp người bán
            hàng trên TikTok Shop tăng trưởng ổn định và vận hành tinh gọn hơn nhờ phân tích
            dữ liệu và AI.
          </p>
        </section>

        <section aria-labelledby="mission-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="mission-heading">
            Sứ mệnh
          </h2>
          <p className="lp-page-section__body">
            Thương mại điện tử qua video và livestream đang phát triển nhanh tại Việt Nam,
            nhưng phần lớn người bán nhỏ và vừa không có đội phân tích dữ liệu hay ngân sách
            thuê agency. Sứ mệnh của Juli AI là đưa năng lực phân tích và tối ưu vận hành ở
            mức chuyên nghiệp đến với mọi người bán, với chi phí phù hợp và cách dùng đơn
            giản.
          </p>
        </section>

        <section aria-labelledby="principles-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="principles-heading">
            Nguyên tắc của chúng tôi
          </h2>
          <div className="lp-page-grid">
            {PRINCIPLES.map((item) => (
              <article className="lp-page-card" key={item.title}>
                <h3 className="lp-page-card__title">{item.title}</h3>
                <p className="lp-page-card__body">{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="company-heading" className="lp-page-section">
          <h2 className="lp-page-section__heading" id="company-heading">
            Thông tin doanh nghiệp
          </h2>
          <dl aria-labelledby="company-heading" className="lp-page-facts">
            {companyFacts.map((fact) => (
              <div className="lp-page-facts__row" key={fact.label}>
                <dt className="lp-page-facts__label">{fact.label}</dt>
                <dd className="lp-page-facts__value">
                  {fact.href ? (
                    <a className="lp-legal__contact-link" href={fact.href}>
                      {fact.value}
                    </a>
                  ) : (
                    fact.value
                  )}
                </dd>
              </div>
            ))}
          </dl>
          <p className="lp-page-section__body">
            Cách chúng tôi xử lý dữ liệu được nêu tại{" "}
            <Link className="lp-legal__contact-link" href="/privacy">
              Chính sách bảo mật
            </Link>{" "}
            và{" "}
            <Link className="lp-legal__contact-link" href="/terms">
              Điều khoản dịch vụ
            </Link>
            .
          </p>
        </section>

        <section aria-labelledby="about-cta-heading" className="lp-page-section lp-page-section--cta">
          <h2 className="lp-page-section__heading" id="about-cta-heading">
            Xem Juli làm việc
          </h2>
          <div className="lp-page-hero__actions">
            <CtaLink href={DEMO_URL} size="large">
              Trải nghiệm Demo
            </CtaLink>
            <CtaLink href="/contact" size="large" variant="secondary">
              Liên hệ với chúng tôi
            </CtaLink>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
