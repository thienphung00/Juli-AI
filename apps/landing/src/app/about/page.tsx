import Link from "next/link";

import {
  BirdGlyph,
  Card,
  Container,
  Eyebrow,
  Heading,
  LinkButton,
  Section,
  SectionIntro,
} from "../../components/ui";
import { SiteFooter } from "../../components/ui/site-footer";
import { SiteHeader } from "../../components/ui/site-header";
import { breadcrumbSchema, buildMetadata, JsonLd } from "../../lib/seo";
import { COMPANY, DEMO_URL } from "../../lib/site";

import styles from "./info.module.css";

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

/** `/about` — company page (D43, redesigned to D44 by P34-E; facts unchanged). */
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
      <main>
        <section aria-labelledby="about-heading" className={styles.hero}>
          <Container>
            <div className={styles.heroInner}>
              <BirdGlyph className={styles.bird} height={39} />
              <Eyebrow>Giới thiệu</Eyebrow>
              <Heading id="about-heading" level={1} size="page">
                Về Juli AI
              </Heading>
              <p className={styles.lead}>
                Juli AI được phát triển và vận hành bởi {COMPANY.name}, một công ty công nghệ
                có trụ sở tại Thành phố Hồ Chí Minh. Chúng tôi xây dựng phần mềm giúp người bán
                hàng trên TikTok Shop tăng trưởng ổn định và vận hành tinh gọn hơn nhờ phân tích
                dữ liệu và AI.
              </p>
            </div>
          </Container>
        </section>

        <Section labelledBy="mission-heading" spacing="compact">
          <div className={styles.split}>
            <Heading id="mission-heading" level={2} size="feature">
              Sứ mệnh
            </Heading>
            <p className="ui-body">
              Thương mại điện tử qua video và livestream đang phát triển nhanh tại Việt Nam,
              nhưng phần lớn người bán nhỏ và vừa không có đội phân tích dữ liệu hay ngân sách
              thuê agency. Sứ mệnh của Juli AI là đưa năng lực phân tích và tối ưu vận hành ở
              mức chuyên nghiệp đến với mọi người bán, với chi phí phù hợp và cách dùng đơn
              giản.
            </p>
          </div>
        </Section>

        <Section labelledBy="principles-heading" tone="alt">
          <SectionIntro title="Nguyên tắc của chúng tôi" titleId="principles-heading" />
          <ul className={`${styles.grid} ${styles.gridTwo}`}>
            {PRINCIPLES.map((item) => (
              <Card as="li" key={item.title}>
                <Heading level={3} size="card">
                  {item.title}
                </Heading>
                <p>{item.body}</p>
              </Card>
            ))}
          </ul>
        </Section>

        <Section labelledBy="company-heading">
          <div className={styles.split}>
            <div className={styles.stack}>
              <Heading id="company-heading" level={2} size="feature">
                Thông tin doanh nghiệp
              </Heading>
              <p className="ui-body">
                Cách chúng tôi xử lý dữ liệu được nêu tại{" "}
                <Link className={styles.inlineLink} href="/privacy">
                  Chính sách bảo mật
                </Link>{" "}
                và{" "}
                <Link className={styles.inlineLink} href="/terms">
                  Điều khoản dịch vụ
                </Link>
                .
              </p>
            </div>
            <div className={styles.company} data-testid="about-company-card">
              <div className={styles.companyHead}>
                <BirdGlyph height={26} loading="lazy" />
                <p className={styles.companyName}>{COMPANY.name}</p>
              </div>
              <dl aria-labelledby="company-heading" className={styles.facts}>
                {companyFacts.map((fact) => (
                  <div className={styles.fact} key={fact.label}>
                    <dt>{fact.label}</dt>
                    <dd>{fact.href ? <a href={fact.href}>{fact.value}</a> : fact.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </Section>

        <Section labelledBy="about-cta-heading" spacing="compact" tone="dark">
          <div className={styles.ctaIntro}>
            <Heading id="about-cta-heading" level={2} onDark size="feature">
              Xem Juli làm việc
            </Heading>
            <div className={styles.actions}>
              <LinkButton blockOnMobile data-testid="about-demo-cta" href={DEMO_URL} variant="on-dark">
                Trải nghiệm Demo
              </LinkButton>
              <LinkButton
                blockOnMobile
                data-testid="about-contact-cta"
                href="/contact"
                variant="on-dark-secondary"
              >
                Liên hệ với chúng tôi
              </LinkButton>
            </div>
          </div>
        </Section>
      </main>
      <SiteFooter />
    </>
  );
}
